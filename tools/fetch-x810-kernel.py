#!/usr/bin/env python3
"""Fetch the verified public X810 kernel RPM and boot images, and extract modules.

The Arch rootfs uses the public X810 kernel's matching module and boot-image
artifacts. They are staged into the Linux boot set so the installer can
preserve Android's original images, install the verified Linux images, and
read-back-check the new boot chain. Release manifest and asset digests are
checked before use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
BOOT_IMAGE_SIZES = {
    "boot": 100_663_296,
    "init_boot": 8_388_608,
    "vendor_boot": 100_663_296,
    "dtbo": 16_777_216,
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def module_tree_identity(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    modules = sorted(path for path in root.rglob("*.ko*") if path.is_file())
    if not modules:
        raise RuntimeError(f"kernel module tree contains no module objects: {root}")
    for path in modules:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative + b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest(), len(modules)


def write_kernel_receipt(
    path: Path, release: dict[str, Any], manifest: dict[str, Any],
    asset: dict[str, Any], module_root: Path, boot_assets: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    module_sha256, module_count = module_tree_identity(module_root)
    receipt = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "release_tag": release.get("tag_name"),
        "source_commit": manifest.get("source_commit"),
        "kernel_release": KERNEL_RELEASE,
        "kernel_rpm": {
            "sha256": asset["sha256"],
            "size_bytes": asset["size_bytes"],
        },
        "modules": {
            "sha256": module_sha256,
            "file_count": module_count,
        },
        "boot_images": {
            name: {"sha256": record["sha256"], "size_bytes": record["size_bytes"]}
            for name, record in boot_assets.items()
        },
    }
    if (not isinstance(receipt["release_tag"], str) or not receipt["release_tag"]
            or not isinstance(receipt["source_commit"], str)
            or not re.fullmatch(r"[0-9a-f]{40,64}", receipt["source_commit"])):
        raise RuntimeError("X810 release manifest lacks valid release provenance")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return receipt


def validate_kernel_receipt(path: Path, module_root: Path) -> dict[str, Any]:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"could not read kernel receipt: {error}") from error
    if (not isinstance(receipt, dict) or receipt.get("schema_version") != 1
            or receipt.get("repository") != REPOSITORY
            or receipt.get("kernel_release") != KERNEL_RELEASE
            or not isinstance(receipt.get("release_tag"), str) or not receipt["release_tag"]
            or not isinstance(receipt.get("source_commit"), str)
            or not re.fullmatch(r"[0-9a-f]{40,64}", receipt["source_commit"])):
        raise RuntimeError("kernel receipt has invalid X810 release provenance")
    rpm = receipt.get("kernel_rpm")
    modules = receipt.get("modules")
    if (not isinstance(rpm, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(rpm.get("sha256", "")))
            or not isinstance(rpm.get("size_bytes"), int) or rpm["size_bytes"] <= 0
            or not isinstance(modules, dict)
            or not re.fullmatch(r"[0-9a-f]{64}", str(modules.get("sha256", "")))):
        raise RuntimeError("kernel receipt has invalid RPM/module hashes")
    actual_hash, actual_count = module_tree_identity(module_root)
    if actual_hash != modules["sha256"] or actual_count != modules.get("file_count"):
        raise RuntimeError("prepared X810 module tree does not match its receipt")
    if not (module_root / "modules.dep").is_file() or (module_root / "modules.dep").stat().st_size == 0:
        raise RuntimeError("prepared X810 module tree is missing modules.dep")
    boot_images = receipt.get("boot_images")
    if not isinstance(boot_images, dict) or set(boot_images) != set(BOOT_IMAGE_SIZES):
        raise RuntimeError("kernel receipt is missing the complete X810 Linux boot set")
    for name, size in BOOT_IMAGE_SIZES.items():
        record = boot_images[name]
        image = path.parent / "boot" / f"{name}.img"
        if (not isinstance(record, dict) or record.get("size_bytes") != size
                or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))
                or image.is_symlink() or not image.is_file() or image.stat().st_size != size
                or sha256_file(image) != record["sha256"]):
            raise RuntimeError(f"prepared X810 {name}.img does not match its verified release receipt")
    return receipt


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
        raise RuntimeError("latest public X810 kernel release is missing manifest.json or kernel.rpm")
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


def release_boot_assets(release: dict[str, Any], manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    github_assets = release.get("assets")
    records = manifest.get("assets")
    if not isinstance(github_assets, list) or not isinstance(records, list):
        raise RuntimeError("X810 kernel release has no asset inventory")
    github_by_name = {item.get("name"): item for item in github_assets if isinstance(item, dict)}
    records_by_name: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("name"), str):
            records_by_name.setdefault(record["name"], []).append(record)
    result: dict[str, dict[str, Any]] = {}
    for name, expected_size in BOOT_IMAGE_SIZES.items():
        filename = f"{name}.img"
        matches = records_by_name.get(filename, [])
        asset = github_by_name.get(filename)
        if len(matches) != 1 or not isinstance(asset, dict):
            raise RuntimeError(f"X810 release must contain exactly one verified {filename}")
        record = matches[0]
        size = record.get("size_bytes")
        digest = record.get("sha256")
        url = asset.get("browser_download_url")
        if (size != expected_size or asset.get("size") != expected_size
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or asset.get("digest") not in (None, f"sha256:{digest}")
                or not isinstance(url, str) or not url.startswith("https://github.com/")):
            raise RuntimeError(f"X810 release {filename} metadata does not match the expected partition image")
        result[name] = {"name": filename, "size_bytes": size, "sha256": digest, "url": url}
    return result


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
    print(f"Downloading verified {asset['name']} from the public X810 release...", flush=True)
    try:
        with opener(request, timeout=120) as response, temporary.open("xb") as output:
            while True:
                block = response.read(4 * 1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > asset["size_bytes"]:
                    raise RuntimeError(f"{asset['name']} download exceeds its manifest size")
                digest.update(block)
                output.write(block)
        if size != asset["size_bytes"] or digest.hexdigest() != asset["sha256"]:
            raise RuntimeError(f"{asset['name']} download failed manifest size/SHA-256 verification")
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


def main(argv: list[str] | None = None) -> int:
    project = Path(__file__).resolve().parents[1]
    cache = project / "cache" / "public-kernel"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=cache / "kernel.json")
    parser.add_argument("--verify-prepared", action="store_true",
                        help="verify the cached receipt and module tree without network access")
    args = parser.parse_args(argv)
    try:
        if args.verify_prepared:
            receipt = validate_kernel_receipt(
                args.receipt, cache / "usr/lib/modules" / KERNEL_RELEASE,
            )
            print(f"Verified prepared X810 kernel modules from {receipt['release_tag']}.")
            return 0
        release = fetch_json(RELEASE_API)
        asset, manifest = release_kernel_asset(release)
        boot_assets = release_boot_assets(release, manifest)
        print(f"Using {release['tag_name']} ({manifest.get('source_commit', 'commit not recorded')}).", flush=True)
        rpm = cache / "kernel.rpm"
        if not rpm.is_file() or rpm.is_symlink() or rpm.stat().st_size != asset["size_bytes"] or sha256_file(rpm) != asset["sha256"]:
            download_asset(asset, rpm)
        module_root = extract_modules(rpm, cache)
        boot_cache = cache / "boot"
        for name, boot_asset in boot_assets.items():
            image = boot_cache / boot_asset["name"]
            if (not image.is_file() or image.is_symlink()
                    or image.stat().st_size != boot_asset["size_bytes"]
                    or sha256_file(image) != boot_asset["sha256"]):
                download_asset(boot_asset, image)
        receipt = write_kernel_receipt(args.receipt, release, manifest, asset, module_root, boot_assets)
        print(f"Kernel release: {KERNEL_RELEASE}; RPM SHA-256: {asset['sha256']}")
        print(f"Kernel receipt: {args.receipt}; module objects: {receipt['modules']['file_count']}")
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, KeyError) as error:
        print(f"KERNEL MODULE PREPARATION FAILED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
