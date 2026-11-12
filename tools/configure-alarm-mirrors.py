#!/usr/bin/env python3
"""Add official Arch Linux ARM mirror fallbacks to a fresh rootfs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


FALLBACK_SERVERS = (
    "https://ca.us.mirror.archlinuxarm.org/$arch/$repo",
    "https://fl.us.mirror.archlinuxarm.org/$arch/$repo",
)
ACTIVE_SERVER = re.compile(r"^\s*Server\s*=\s*(\S+)\s*$", re.IGNORECASE)


def configure(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"mirrorlist must be a regular non-symlink file: {path}")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    active = {
        match.group(1)
        for line in lines
        if not line.lstrip().startswith("#")
        if (match := ACTIVE_SERVER.match(line.rstrip("\r\n")))
    }
    missing = [server for server in FALLBACK_SERVERS if server not in active]
    if not missing:
        return False

    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += "\n"
    insertion = next(
        (index for index, line in enumerate(lines)
         if not line.lstrip().startswith("#")
         and ACTIVE_SERVER.match(line.rstrip("\r\n"))),
        len(lines),
    )
    additions = [f"Server = {server}\n" for server in missing]
    lines[insertion:insertion] = additions
    path.write_text("".join(lines), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mirrorlist", type=Path)
    args = parser.parse_args()
    try:
        changed = configure(args.mirrorlist)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print("Configured official Arch Linux ARM mirror fallbacks." if changed
          else "Official Arch Linux ARM mirror fallbacks are already configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
