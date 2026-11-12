#!/usr/bin/env python3
"""Create the compact manifest consumed by tools/x810-install."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    output = project / "out"
    archive = output / "rootfs.tar.zst"
    tag = os.environ.get("X810_RELEASE_TAG", "x810-arch-build-0")
    source_commit = os.environ.get("GITHUB_SHA", "local")
    if not re.fullmatch(r"x810-arch-build-[0-9]+", tag):
        print("X810_RELEASE_TAG must have the form x810-arch-build-<run-id>", file=sys.stderr)
        return 2
    if not archive.is_file() or archive.is_symlink():
        print(f"public rootfs archive is missing or unsafe: {archive}", file=sys.stderr)
        return 2
    size = archive.stat().st_size
    if size <= 0 or size >= 2_000_000_000:
        print(f"rootfs archive size is outside the GitHub release asset limit: {size}", file=sys.stderr)
        return 2
    digest = sha256_file(archive)
    manifest = {
        "schema_version": 1,
        "type": "x810-arch-release",
        "release_tag": tag,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_commit": source_commit,
        "device": {"model": "SM-X810", "codename": "gts9pwifi"},
        "os": {"id": "archarm", "arch": "aarch64"},
        "kernel_release": "7.2.0-gts9wifi",
        "profile": [
            "GNOME Shell", "GDM", "GNOME Settings", "GNOME Terminal", "Brave",
            "BlueZ", "Tab Companion", "X810 module tree",
        ],
        "rootfs": {"archive": archive.name, "size_bytes": size, "sha256": digest},
        "assets": [{"name": archive.name, "size_bytes": size, "sha256": digest}],
        "privacy": "No build-time human account, SSH keys, Wi-Fi credentials, or Tailscale state.",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    checksum = output / "SHA256SUMS"
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Release manifest prepared for {tag}; rootfs SHA-256 {digest} ({size:,} bytes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
