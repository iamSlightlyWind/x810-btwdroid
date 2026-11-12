#!/usr/bin/env python3
"""Download the exact Arch Linux ARM bootstrap pinned in ALARM-ROOTFS.lock."""

from __future__ import annotations

import hashlib
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath


USER_AGENT = "x810-btwdroid-build/1"


def parse_lock(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[a-z0-9_]+", key) or key in values:
            raise ValueError(f"invalid or duplicate lock entry at {path.name}:{number}")
        values[key] = value
    return values


def download(url: str, destination: Path, size: int, digest: str) -> None:
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-HTTPS bootstrap URL: {url}")
    if destination.is_symlink():
        raise ValueError(f"refusing symlinked cache input: {destination}")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size == size and sha256_file(destination) == digest:
        print(f"Verified cached {destination.name}.")
        return
    temporary = destination.with_name(f".{destination.name}.partial-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    actual_size = 0
    actual_hash = hashlib.sha256()
    print(f"Downloading {destination.name} from its pinned HTTPS source...", flush=True)
    try:
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open("xb") as output:
            while True:
                block = response.read(4 * 1024 * 1024)
                if not block:
                    break
                actual_size += len(block)
                if actual_size > size:
                    raise ValueError(f"{destination.name} exceeds its pinned size")
                actual_hash.update(block)
                output.write(block)
        if actual_size != size or actual_hash.hexdigest() != digest:
            raise ValueError(f"{destination.name} failed pinned size/SHA-256 verification")
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    lock = parse_lock(project / "docs/ALARM-ROOTFS.lock")
    required = (
        "source_url", "signature_url", "archive_path", "signature_path",
        "archive_size_bytes", "archive_sha256", "signature_size_bytes", "signature_sha256",
    )
    missing = [name for name in required if not lock.get(name)]
    if missing:
        raise SystemExit(f"ALARM-ROOTFS.lock is missing: {', '.join(missing)}")
    try:
        for prefix, url_key in (("archive", "source_url"), ("signature", "signature_url")):
            relative = PurePosixPath(lock[f"{prefix}_path"])
            if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != "cache":
                raise ValueError(f"unsafe {prefix} path in ALARM-ROOTFS.lock")
            size = int(lock[f"{prefix}_size_bytes"])
            digest = lock[f"{prefix}_sha256"]
            if size <= 0 or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"invalid {prefix} size/hash in ALARM-ROOTFS.lock")
            download(lock[url_key], project.joinpath(*relative.parts), size, digest)
        return 0
    except (OSError, ValueError, urllib.error.URLError, TimeoutError) as error:
        print(f"ARCH LINUX ARM BOOTSTRAP DOWNLOAD FAILED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
