#!/usr/bin/env python3
"""List installed packages recorded in an Arch Linux ARM rootfs tarball."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "cache/ArchLinuxARM-aarch64-latest.tar.gz"
DESC_RE = re.compile(r"^\./var/lib/pacman/local/[^/]+/desc$")


def read_package_fields(data: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    key: str | None = None
    for line in data.decode("utf-8", errors="replace").splitlines():
        if line.startswith("%") and line.endswith("%"):
            key = line.strip("%")
        elif key and line:
            fields.setdefault(key, line)
            key = None
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--json", action="store_true", help="emit JSON objects")
    parser.add_argument("--names-only", action="store_true", help="omit versions")
    args = parser.parse_args()

    if not args.archive.is_file():
        parser.error(f"archive not found: {args.archive}")

    packages: list[dict[str, str]] = []
    try:
        with tarfile.open(args.archive, mode="r:gz") as archive:
            for member in archive:
                if not member.isfile() or not DESC_RE.fullmatch(member.name):
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                fields = read_package_fields(stream.read())
                if fields.get("NAME") and fields.get("VERSION"):
                    packages.append({"name": fields["NAME"], "version": fields["VERSION"]})
    except (OSError, tarfile.TarError) as exc:
        print(f"Cannot read package database from {args.archive}: {exc}", file=sys.stderr)
        return 1

    packages.sort(key=lambda package: package["name"])
    if args.json:
        print(json.dumps(packages, indent=2))
    elif args.names_only:
        for package in packages:
            print(package["name"])
    else:
        for package in packages:
            print(f"{package['name']} {package['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
