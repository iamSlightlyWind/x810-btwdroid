#!/usr/bin/env python3
"""Package the Arch X810 support package as a Tab Companion update bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any


PROJECT = "x810-arch"
MAX_PACKAGE_SIZE = 4 * 1024**3
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,180}")
SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,80}")
SAFE_PACKAGE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9:.+_~-]{0,127}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pacman_package_fields(path: Path) -> dict[str, str]:
    decoder = subprocess.Popen(["zstd", "-q", "-dc", str(path)], stdout=subprocess.PIPE)
    assert decoder.stdout is not None
    metadata: bytes | None = None
    try:
        with tarfile.open(fileobj=decoder.stdout, mode="r|") as archive:
            for member in archive:
                if member.name != ".PKGINFO":
                    continue
                if metadata is not None or not member.isfile():
                    raise ValueError("Arch package must contain exactly one regular .PKGINFO")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("Could not read Arch package metadata")
                metadata = stream.read(64 * 1024 + 1)
                if len(metadata) > 64 * 1024:
                    raise ValueError("Arch package .PKGINFO is unexpectedly large")
    finally:
        decoder.stdout.close()
        status = decoder.wait()
    if status != 0:
        raise ValueError("Could not decompress the Arch package")
    if metadata is None:
        raise ValueError("Arch package must contain exactly one regular .PKGINFO")
    values: dict[str, str] = {}
    for line in metadata.decode("utf-8").splitlines():
        key, separator, value = line.partition(" = ")
        if separator and key in {"pkgname", "pkgver", "arch"}:
            if key in values:
                raise ValueError(f"Arch package has duplicate {key} metadata")
            values[key] = value
    if any(not values.get(key) for key in ("pkgname", "pkgver", "arch")):
        raise ValueError("Arch package metadata is incomplete")
    return values


def build_manifest(package: Path, build_info_path: Path) -> dict[str, Any]:
    if not package.is_file() or package.is_symlink() or not SAFE_NAME.fullmatch(package.name):
        raise ValueError("support package must be a regular file with a safe filename")
    size = package.stat().st_size
    if not 0 < size <= MAX_PACKAGE_SIZE:
        raise ValueError("support package is empty or exceeds the update limit")
    if not build_info_path.is_file() or build_info_path.is_symlink():
        raise ValueError("Arch port build metadata is missing or unsafe")
    info = json.loads(build_info_path.read_text(encoding="utf-8"))
    if (not isinstance(info, dict) or info.get("schema_version") != 1
            or info.get("project") != PROJECT):
        raise ValueError("invalid Arch port build metadata")
    version = info.get("version")
    run_id = info.get("run_id")
    run_number = info.get("run_number")
    commit = info.get("commit")
    branch = info.get("branch")
    if not isinstance(version, str) or not SAFE_VERSION.fullmatch(version):
        raise ValueError("Arch port build metadata has an invalid version")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
           for value in (run_id, run_number)):
        raise ValueError("Arch port build metadata has an invalid Actions run identity")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise ValueError("Arch port build metadata has an invalid source commit")
    if not isinstance(branch, str) or not branch or len(branch) > 200:
        raise ValueError("Arch port build metadata has an invalid branch")
    fields = pacman_package_fields(package)
    if fields != {"pkgname": "x810-device-support", "pkgver": fields.get("pkgver"), "arch": "aarch64"}:
        raise ValueError("unexpected package name or architecture in update artifact")
    if not SAFE_PACKAGE_VERSION.fullmatch(fields["pkgver"]):
        raise ValueError("support package version is invalid")
    if not fields["pkgver"].startswith(version + "-"):
        raise ValueError("support package version does not match port build metadata")
    return {
        "schema_version": 1,
        "project": PROJECT,
        "version": f"{version}+{run_number}",
        "run_id": run_id,
        "run_number": run_number,
        "commit": commit,
        "branch": branch,
        "assets": [{
            "name": package.name,
            "sha256": sha256_file(package),
            "size": size,
            "format": "pacman-local",
            "package_name": fields["pkgname"],
            "package_version": fields["pkgver"],
            "target": {
                "os_id": "archarm",
                "os_version": "rolling",
                "arch": "aarch64",
                "device": "SM-X810",
            },
        }],
    }


def create_bundle(package: Path, build_info_path: Path, output_path: Path) -> dict[str, Any]:
    document = build_manifest(package, build_info_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=output_path.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("tab-companion-update.json", json.dumps(document, indent=2) + "\n")
            archive.write(package, package.name)
        os.replace(temporary, output_path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--build-info", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = create_bundle(args.package, args.build_info, args.output)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, subprocess.SubprocessError,
            tarfile.TarError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    print(f"Wrote Arch X810 port updater bundle for run #{manifest['run_number']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
