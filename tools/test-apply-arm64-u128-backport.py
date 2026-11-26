#!/usr/bin/env python3
"""Tests the Linux tools header compatibility backport."""

from __future__ import annotations

import tempfile
import unittest
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().with_name("apply-arm64-u128-backport.py")
SPEC = importlib.util.spec_from_file_location("arm64_u128_backport", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ANCHOR, TYPEDEFS, apply = MODULE.ANCHOR, MODULE.TYPEDEFS, MODULE.apply


class BackportTests(unittest.TestCase):
    def test_applies_upstream_typedefs_once(self):
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / "types.h"
            header.write_text("prefix\n" + ANCHOR + "suffix\n", encoding="utf-8")
            apply(header)
            result = header.read_text(encoding="utf-8")
            self.assertEqual(result.count(TYPEDEFS), 1)
            apply(header)
            self.assertEqual(header.read_text(encoding="utf-8").count(TYPEDEFS), 1)

    def test_refuses_unknown_upstream_header(self):
        with tempfile.TemporaryDirectory() as directory:
            header = Path(directory) / "types.h"
            header.write_text("unexpected upstream content\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "insertion point"):
                apply(header)


if __name__ == "__main__":
    unittest.main()
