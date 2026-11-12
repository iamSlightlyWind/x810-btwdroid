#!/usr/bin/env python3
"""Tests for the exact Fedora release/module provenance passed to Arch builds."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).with_name("fetch-x810-kernel.py")
SPEC = importlib.util.spec_from_file_location("fetch_x810_kernel", TOOL)
assert SPEC is not None and SPEC.loader is not None
fetcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetcher)


class KernelReceiptTests(unittest.TestCase):
    def test_receipt_records_release_rpm_and_exact_module_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            modules = root / "modules"
            modules.mkdir()
            (modules / "modules.dep").write_text("# modules\n", encoding="utf-8")
            (modules / "x810.ko").write_bytes(b"module-one")
            (modules / "x810.ko.zst").write_bytes(b"module-two")
            receipt_path = root / "kernel.json"
            receipt = fetcher.write_kernel_receipt(
                receipt_path,
                {"tag_name": "x810-fedora-port-build-42"},
                {"source_commit": "a" * 40},
                {"sha256": "b" * 64, "size_bytes": 1234},
                modules,
            )
            self.assertEqual(receipt["repository"], "iamSlightlyWind/x810-fedroid")
            self.assertEqual(receipt["kernel_release"], "7.2.0-gts9wifi")
            self.assertEqual(receipt["kernel_rpm"], {"sha256": "b" * 64, "size_bytes": 1234})
            self.assertEqual(receipt["modules"]["file_count"], 2)
            self.assertEqual(json.loads(receipt_path.read_text()), receipt)
            self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(fetcher.validate_kernel_receipt(receipt_path, modules), receipt)

            (modules / "x810.ko").write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "does not match its receipt"):
                fetcher.validate_kernel_receipt(receipt_path, modules)

    def test_receipt_rejects_missing_source_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            modules = Path(temporary) / "modules"
            modules.mkdir()
            (modules / "x810.ko").write_bytes(b"module")
            with self.assertRaisesRegex(RuntimeError, "valid release provenance"):
                fetcher.write_kernel_receipt(
                    Path(temporary) / "kernel.json",
                    {"tag_name": "kernel"},
                    {"source_commit": "bad"},
                    {"sha256": "b" * 64, "size_bytes": 1234},
                    modules,
                )

    def test_module_identity_rejects_empty_trees(self):
        with tempfile.TemporaryDirectory() as temporary, \
                self.assertRaisesRegex(RuntimeError, "no module objects"):
            fetcher.module_tree_identity(Path(temporary))


if __name__ == "__main__":
    unittest.main()
