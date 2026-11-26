#!/usr/bin/env python3
"""Backport upstream Linux commit 10a47fb67340 for current arm64 UAPI headers."""

from __future__ import annotations

import sys
from pathlib import Path


ANCHOR = "\t__GFP_HIGH\n} gfp_t;\n\n"
TYPEDEFS = (
    "#ifdef __SIZEOF_INT128__\n"
    "typedef __signed__ __int128 __s128 __attribute__((aligned(16)));\n"
    "typedef unsigned __int128 __u128 __attribute__((aligned(16)));\n"
    "#endif"
)


def apply(header: Path) -> None:
    text = header.read_text(encoding="utf-8")
    if TYPEDEFS in text:
        return
    if text.count(ANCHOR) != 1:
        raise ValueError(f"cannot locate unique tools/include/linux/types.h insertion point: {header}")
    header.write_text(text.replace(ANCHOR, ANCHOR + TYPEDEFS + "\n\n", 1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: apply-arm64-u128-backport.py <tools/include/linux/types.h>", file=sys.stderr)
        return 2
    try:
        apply(Path(args[0]))
    except (OSError, UnicodeError, ValueError) as error:
        print(f"arm64 tools __u128 backport failed: {error}", file=sys.stderr)
        return 2
    print("Applied/verified upstream arm64 tools __u128 backport.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
