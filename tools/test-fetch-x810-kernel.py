#!/usr/bin/env python3
"""Tests for verified X810 kernel release/module provenance used by Arch builds."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


TOOL = Path(__file__).with_name("fetch-x810-kernel.py")
SPEC = importlib.util.spec_from_file_location("fetch_x810_kernel", TOOL)
assert SPEC is not None and SPEC.loader is not None
fetcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetcher)


class KernelReceiptTests(unittest.TestCase):
    def test_github_api_requests_use_workflow_token_without_exposing_it_in_release_urls(self):
        with patch.dict(fetcher.os.environ, {"GH_TOKEN": "workflow-secret"}, clear=True):
            headers = fetcher.github_api_headers()
        self.assertEqual(headers["Authorization"], "Bearer workflow-secret")
        self.assertIn("X-GitHub-Api-Version", headers)
        self.assertNotIn("Authorization", {
            "User-Agent": fetcher.USER_AGENT,
        })

    def test_latest_kernel_identity_is_metadata_only_and_carries_all_boot_hashes(self):
        release = {"tag_name": "x810-fedora-port-build-42"}
        manifest = {"source_commit": "a" * 40}
        rpm = {"sha256": "b" * 64, "size_bytes": 1234}
        boot = {
            name: {"sha256": hashlib.sha256(name.encode()).hexdigest(), "size_bytes": size}
            for name, size in fetcher.BOOT_IMAGE_SIZES.items()
        }
        with patch.object(fetcher, "fetch_json", return_value=release), \
                patch.object(fetcher, "release_kernel_asset", return_value=(rpm, manifest)), \
                patch.object(fetcher, "release_boot_assets", return_value=boot):
            identity = fetcher.latest_kernel_identity()
        self.assertEqual(identity["release_tag"], release["tag_name"])
        self.assertEqual(identity["source_commit"], manifest["source_commit"])
        self.assertEqual(identity["kernel_rpm"], {"sha256": rpm["sha256"], "size_bytes": rpm["size_bytes"]})
        self.assertEqual(identity["boot_images"], {
            name: {"sha256": record["sha256"], "size_bytes": record["size_bytes"]}
            for name, record in boot.items()
        })

    def test_receipt_records_release_rpm_and_exact_module_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            modules = root / "modules"
            modules.mkdir()
            (modules / "modules.dep").write_text("# modules\n", encoding="utf-8")
            (modules / "x810.ko").write_bytes(b"module-one")
            (modules / "x810.ko.zst").write_bytes(b"module-two")
            receipt_path = root / "kernel.json"
            images = {name: {"sha256": hashlib.sha256(b"boot").hexdigest(), "size_bytes": 4}
                      for name in fetcher.BOOT_IMAGE_SIZES}
            (root / "boot").mkdir()
            for name in images:
                (root / "boot" / f"{name}.img").write_bytes(b"boot")
            with patch.dict(fetcher.BOOT_IMAGE_SIZES, {name: 4 for name in images}):
                receipt = fetcher.write_kernel_receipt(
                    receipt_path,
                    {"tag_name": "x810-fedora-port-build-42"},
                    {"source_commit": "a" * 40},
                    {"sha256": "b" * 64, "size_bytes": 1234},
                    modules, images,
                )
            self.assertEqual(receipt["repository"], "iamSlightlyWind/x810-fedroid")
            self.assertEqual(receipt["kernel_release"], "7.2.0-gts9wifi")
            self.assertEqual(receipt["kernel_rpm"], {"sha256": "b" * 64, "size_bytes": 1234})
            self.assertEqual(receipt["modules"]["file_count"], 2)
            self.assertEqual(json.loads(receipt_path.read_text()), receipt)
            self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o600)
            with patch.dict(fetcher.BOOT_IMAGE_SIZES, {name: 4 for name in images}):
                self.assertEqual(fetcher.validate_kernel_receipt(receipt_path, modules), receipt)

            (modules / "x810.ko").write_bytes(b"changed")
            with patch.dict(fetcher.BOOT_IMAGE_SIZES, {name: 4 for name in images}), \
                    self.assertRaisesRegex(RuntimeError, "does not match its receipt"):
                fetcher.validate_kernel_receipt(receipt_path, modules)

    def test_receipt_rejects_missing_source_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            modules = Path(temporary) / "modules"
            modules.mkdir()
            (modules / "x810.ko").write_bytes(b"module")
            boot_assets = {name: {"sha256": hashlib.sha256(b"boot").hexdigest(), "size_bytes": 4}
                           for name in fetcher.BOOT_IMAGE_SIZES}
            with self.assertRaisesRegex(RuntimeError, "valid release provenance"):
                fetcher.write_kernel_receipt(
                    Path(temporary) / "kernel.json",
                    {"tag_name": "kernel"},
                    {"source_commit": "bad"},
                    {"sha256": "b" * 64, "size_bytes": 1234},
                    modules, boot_assets,
                )

    def test_module_identity_rejects_empty_trees(self):
        with tempfile.TemporaryDirectory() as temporary, \
                self.assertRaisesRegex(RuntimeError, "no module objects"):
            fetcher.module_tree_identity(Path(temporary))


if __name__ == "__main__":
    unittest.main()
