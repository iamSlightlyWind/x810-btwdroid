#!/usr/bin/env python3
"""Assemble a matched Arch rootfs and Tab Companion updater release set."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path


HEX = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40,64}")
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,180}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_update_bundle(path: Path, *, run_id: int, run_number: int,
                           commit: str, branch: str,
                           port_version: str) -> tuple[str, int, str]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 4 * 1024**3:
        raise ValueError("update.zip is missing, unsafe, empty, or too large")
    try:
        with zipfile.ZipFile(path, "r") as bundle:
            infos = bundle.infolist()
            if len(infos) != 2 or any(info.is_dir() or not SAFE_NAME.fullmatch(info.filename) for info in infos):
                raise ValueError("update.zip must contain only a flat manifest and package")
            names = {info.filename for info in infos}
            if "tab-companion-update.json" not in names:
                raise ValueError("update.zip is missing tab-companion-update.json")
            info = json.loads(bundle.read("tab-companion-update.json"))
            if (not isinstance(info, dict) or info.get("schema_version") != 1
                    or info.get("project") != "x810-arch"
                    or info.get("run_id") != run_id or info.get("run_number") != run_number
                    or info.get("commit") != commit or info.get("branch") != branch
                    or info.get("version") != f"{port_version}+{run_number}"):
                raise ValueError("update.zip does not match this Arch push identity")
            assets = info.get("assets")
            if not isinstance(assets, list) or len(assets) != 1 or not isinstance(assets[0], dict):
                raise ValueError("update.zip must describe exactly one support package")
            asset = assets[0]
            name = asset.get("name")
            if (not isinstance(name, str) or name not in names or not SAFE_NAME.fullmatch(name)
                    or asset.get("format") != "pacman-local"
                    or asset.get("package_name") != "x810-device-support"
                    or not isinstance(asset.get("package_version"), str)
                    or not asset["package_version"].startswith(port_version + "-")
                    or asset.get("target") != {"os_id": "archarm", "os_version": "rolling",
                                                "arch": "aarch64", "device": "SM-X810"}):
                raise ValueError("update.zip package identity or target is invalid")
            digest = asset.get("sha256")
            size = asset.get("size")
            if (not isinstance(digest, str) or not HEX.fullmatch(digest)
                    or isinstance(size, bool) or not isinstance(size, int) or size <= 0):
                raise ValueError("update.zip package digest or size is invalid")
            package_info = next(item for item in infos if item.filename == name)
            if package_info.file_size != size:
                raise ValueError("update package size disagrees with its manifest")
            package_hash = hashlib.sha256()
            count = 0
            with bundle.open(package_info, "r") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    count += len(block)
                    if count > size:
                        raise ValueError("update package exceeds its declared size")
                    package_hash.update(block)
            if count != size or package_hash.hexdigest() != digest:
                raise ValueError("update package SHA-256/size check failed")
    except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        raise ValueError(f"invalid update.zip: {error}") from error
    return name, size, digest


def assemble(release_dir: Path, update_zip: Path, *, tag: str, run_id: int,
             run_number: int, commit: str, branch: str, input_key: str,
             port_version: str) -> dict:
    if not re.fullmatch(r"x810-arch-build-[0-9]+", tag):
        raise ValueError("release tag is invalid")
    if run_id < 1 or run_number < 1 or not COMMIT.fullmatch(commit) or branch != "main":
        raise ValueError("publication identity is invalid")
    if not HEX.fullmatch(input_key):
        raise ValueError("rootfs build input key is invalid")
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,19})\.(?:0|[1-9][0-9]{0,19})\.(?:0|[1-9][0-9]{0,19})", port_version):
        raise ValueError("port version must be numeric MAJOR.MINOR.PATCH")
    rootfs = release_dir / "rootfs.tar.zst"
    manifest_path = release_dir / "manifest.json"
    if any(path.is_symlink() or not path.is_file() for path in (rootfs, manifest_path)):
        raise ValueError("rootfs release inputs are missing or unsafe")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root_record = manifest.get("rootfs") if isinstance(manifest, dict) else None
    if (not isinstance(root_record, dict)
            or manifest.get("schema_version") != 1
            or manifest.get("type") != "x810-arch-release"
            or manifest.get("release_tag") != tag
            or manifest.get("source_commit") != commit
            or manifest.get("build_inputs_key") != input_key
            or manifest.get("device") != {"model": "SM-X810", "codename": "gts9pwifi"}
            or manifest.get("os") != {"id": "archarm", "arch": "aarch64"}
            or root_record.get("archive") != rootfs.name
            or root_record.get("size_bytes") != rootfs.stat().st_size
            or root_record.get("sha256") != sha256_file(rootfs)):
        raise ValueError("rootfs manifest does not match the planned Arch build")
    package_name, package_size, package_digest = validate_update_bundle(
        update_zip, run_id=run_id, run_number=run_number, commit=commit, branch=branch,
        port_version=port_version,
    )
    update_size = update_zip.stat().st_size
    update_digest = sha256_file(update_zip)
    destination = release_dir / "update.zip"
    if update_zip.resolve() != destination.resolve():
        shutil.copyfile(update_zip, destination)
    root_asset = {"name": rootfs.name, "size_bytes": rootfs.stat().st_size,
                  "sha256": root_record["sha256"]}
    update_asset = {"name": "update.zip", "size_bytes": update_size,
                   "sha256": update_digest}
    manifest["assets"] = [root_asset, update_asset]
    manifest["port_update"] = {
        "archive": "update.zip",
        "package_name": "x810-device-support",
        "package_asset": package_name,
        "package_size_bytes": package_size,
        "package_sha256": package_digest,
        "size_bytes": update_size,
        "sha256": update_digest,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (release_dir / "SHA256SUMS").write_text(
        f"{root_record['sha256']}  rootfs.tar.zst\n{update_digest}  update.zip\n",
        encoding="ascii",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--update-zip", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-number", type=int, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--input-key", required=True)
    parser.add_argument("--port-version", required=True)
    args = parser.parse_args(argv)
    try:
        manifest = assemble(
            args.release_dir, args.update_zip, tag=args.tag, run_id=args.run_id,
            run_number=args.run_number, commit=args.commit, branch=args.branch,
            input_key=args.input_key, port_version=args.port_version,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(f"Assembled complete Arch release {manifest['release_tag']} with rootfs and port updater.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
