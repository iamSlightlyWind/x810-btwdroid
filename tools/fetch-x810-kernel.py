#!/usr/bin/env python3
"""Fetch the public X810 kernel RPM and extract its matching module tree.

The Arch rootfs intentionally uses the module package from the public X810
Fedora release: the tablet's boot/kernel partitions are not touched by the
Arch installer. The GitHub release manifest and asset digest are checked
before the RPM payload is extracted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPOSITORY = "iamSlightlyWind/x810-fedroid"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MODEL = "SM-X810"
CODENAME = "gts9pwifi"
KERNEL_RELEASE = "7.2.0-gts9wifi"
USER_AGENT = "x810-btwdroid-build/1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_json(url: str, opener=urllib.request.urlopen) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    })
    try:
        with opener(request, timeout=60) as response:
            payload = response.read(16 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"could not read public X810 kernel release metadata: {error}") from error
    if len(payload) > 16 * 1024 * 1024:
        raise RuntimeError("X810 kernel release metadata exceeds 16 MiB")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid X810 release metadata: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError("X810 release metadata is not a JSON object")
    return value


def release_kernel_asset(release: dict[str, Any], opener=urllib.request.urlopen) -> tuple[dict[str, Any], dict[str, Any]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("X810 GitHub release has no asset list")
    by_name = {item.get("name"): item for item in assets if isinstance(item, dict)}
    manifest_asset = by_name.get("manifest.json")
    kernel_asset = by_name.get("kernel.rpm")
    if not isinstance(manifest_asset, dict) or not isinstance(kernel_asset, dict):
        raise RuntimeError("latest X810 Fedora release is missing manifest.json or kernel.rpm")
    url = manifest_asset.get("browser_download_url")
    size = manifest_asset.get("size")
    digest = manifest_asset.get("digest")
    if (not isinstance(url, str) or not url.startswith("https://github.com/")
            or not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= 16 * 1024 * 1024):
        raise RuntimeError("X810 release manifest asset metadata is malformed")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=90) as response:
            data = response.read(size + 1)
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"could not download X810 kernel manifest: {error}") from error
    if len(data) != size:
        raise RuntimeError("downloaded X810 kernel manifest has the wrong size")
    if isinstance(digest, str) and digest.startswith("sha256:") and sha256_bytes(data) != digest[7:]:
        raise RuntimeError("X810 kernel manifest does not match GitHub's release-asset digest")
    try:
        manifest = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid X810 kernel manifest: {error}") from error
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("type") != "x810-fedora-release"
            or manifest.get("device") != {"model": MODEL, "codename": CODENAME}
            or manifest.get("release_tag") != release.get("tag_name")):
        raise RuntimeError("X810 kernel manifest targets a different device or release")
    records = manifest.get("assets")
    if not isinstance(records, list):
        raise RuntimeError("X810 kernel manifest has no asset inventory")
    matches = [record for record in records if isinstance(record, dict) and record.get("name") == "kernel.rpm"]
    if len(matches) != 1:
        raise RuntimeError("X810 kernel manifest must record exactly one kernel.rpm")
    record = matches[0]
    record_size = record.get("size_bytes")
    record_digest = record.get("sha256")
    if (not isinstance(record_size, int) or isinstance(record_size, bool) or record_size <= 0
            or not isinstance(record_digest, str) or len(record_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in record_digest)):
        raise RuntimeError("kernel.rpm manifest record is invalid")
    if (kernel_asset.get("size") != record_size
            or kernel_asset.get("digest") not in (None, f"sha256:{record_digest}")):
        raise RuntimeError("GitHub kernel.rpm metadata disagrees with the release manifest")
    kernel_url = kernel_asset.get("browser_download_url")
    if not isinstance(kernel_url, str) or not kernel_url.startswith("https://github.com/"):
        raise RuntimeError("kernel.rpm download URL is not an HTTPS GitHub asset")
    return {"name": "kernel.rpm", "size_bytes": record_size, "sha256": record_digest,
            "url": kernel_url}, manifest


def download_asset(asset: dict[str, Any], destination: Path, opener=urllib.request.urlopen) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.is_symlink():
        raise RuntimeError(f"refusing symlinked kernel RPM cache path: {destination}")
    temporary = destination.with_name(f".{destination.name}.partial-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    request = urllib.request.Request(asset["url"], headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    size = 0
    print("Downloading verified kernel.rpm from the latest public X810 release...", flush=True)
    try:
        with opener(request, timeout=120) as response, temporary.open("xb") as output:
            while True:
                block = response.read(4 * 1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > asset["size_bytes"]:
                    raise RuntimeError("kernel.rpm download exceeds its manifest size")
                digest.update(block)
                output.write(block)
        if size != asset["size_bytes"] or digest.hexdigest() != asset["sha256"]:
            raise RuntimeError("kernel.rpm download failed manifest size/SHA-256 verification")
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def extract_modules(rpm: Path, output_root: Path) -> Path:
    for tool in ("rpm", "rpm2cpio", "cpio"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"required extraction tool is missing: {tool}")
    metadata = subprocess.run(
        ["rpm", "-qp", "--queryformat", "%{NAME} %{VERSION} %{ARCH}", str(rpm)],
        text=True, capture_output=True, check=False,
    )
    if metadata.returncode != 0 or metadata.stdout.strip() != "linux-x810 7.2.0 aarch64":
        raise RuntimeError(f"kernel asset is not the expected AArch64 X810 kernel RPM: {metadata.stdout.strip()}")
    output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_root.is_symlink():
        raise RuntimeError(f"refusing symlinked public kernel cache: {output_root}")
    target = output_root / "usr/lib/modules" / KERNEL_RELEASE
    if target.is_symlink():
        raise RuntimeError(f"refusing symlinked module cache: {target}")
    if target.is_dir() and (target / "modules.dep").is_file():
        print(f"Reusing cached module tree for {KERNEL_RELEASE}.", flush=True)
        return target
    temporary_parent = output_root.parent
    temporary_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="x810-rpm-extract-", dir=temporary_parent) as temporary:
        staging = Path(temporary)
        rpm_process = subprocess.Popen(["rpm2cpio", str(rpm)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert rpm_process.stdout is not None
        try:
            extracted = subprocess.run(
                ["cpio", "-idm", "--no-absolute-filenames"], cwd=staging,
                stdin=rpm_process.stdout, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, check=False,
            )
        finally:
            rpm_process.stdout.close()
        rpm_stderr = rpm_process.stderr.read() if rpm_process.stderr else b""
        rpm_status = rpm_process.wait()
        if rpm_status != 0:
            raise RuntimeError(rpm_stderr.decode(errors="replace").strip() or "rpm2cpio failed")
        if extracted.returncode != 0:
            raise RuntimeError(extracted.stderr.decode(errors="replace").strip() or "cpio extraction failed")
        source = staging / "usr/lib/modules" / KERNEL_RELEASE
        if source.is_symlink() or not source.is_dir() or not (source / "modules.dep").is_file():
            raise RuntimeError(f"kernel RPM does not contain the required module tree {KERNEL_RELEASE}")
        output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        module_parent = output_root / "usr/lib/modules"
        module_parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeError(f"module cache exists but is incomplete; refusing to overwrite: {target}")
        shutil.copytree(source, target, symlinks=True)
    print(f"Extracted matching X810 kernel modules: {target}", flush=True)
    return target


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    cache = project / "cache" / "public-kernel"
    try:
        release = fetch_json(RELEASE_API)
        asset, manifest = release_kernel_asset(release)
        print(f"Using {release['tag_name']} ({manifest.get('source_commit', 'commit not recorded')}).", flush=True)
        rpm = cache / "kernel.rpm"
        if not rpm.is_file() or rpm.is_symlink() or rpm.stat().st_size != asset["size_bytes"] or sha256_file(rpm) != asset["sha256"]:
            download_asset(asset, rpm)
        extract_modules(rpm, cache)
        print(f"Kernel release: {KERNEL_RELEASE}; RPM SHA-256: {asset['sha256']}")
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, KeyError) as error:
        print(f"KERNEL MODULE PREPARATION FAILED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
