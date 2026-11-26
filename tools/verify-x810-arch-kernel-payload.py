#!/usr/bin/env python3
"""Check that the built X810 zboot image contains the current PPS code."""

from __future__ import annotations

import argparse
import gzip
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def verify(image: bytes, pogo_source: str) -> None:
    revision = re.search(r"driver_revision=(\d+)", pogo_source)
    if revision is None:
        raise ValueError("cannot determine STM32 pogo driver revision")
    required = (
        f"driver_revision={revision.group(1)}".encode(),
        b"PPS bus did not settle: target=%dmV measured=%dmV",
        b"Handling deferred source Alert after PPS AMS",
    )
    missing = [marker.decode() for marker in required if marker not in image]
    if missing:
        raise ValueError("built kernel is missing required current X810 marker: " + "; ".join(missing))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kernel", type=Path)
    parser.add_argument("pogo_source", type=Path)
    parser.add_argument("extractor", type=Path)
    args = parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="x810-arch-kernel-check-") as directory:
            payload = Path(directory) / "kernel.gz"
            subprocess.run([sys.executable, str(args.extractor), str(args.kernel), str(payload)], check=True)
            image = gzip.decompress(payload.read_bytes())
        verify(image, args.pogo_source.read_text(encoding="utf-8"))
        print("Verified X810 zboot contains the current PPS settle path and pogo driver.")
        return 0
    except (OSError, UnicodeError, gzip.BadGzipFile, subprocess.SubprocessError, ValueError) as error:
        print(f"X810 Arch kernel payload verification failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
