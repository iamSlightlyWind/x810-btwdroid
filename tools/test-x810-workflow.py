#!/usr/bin/env python3
"""Guard the Arch workflow's Fedora-shaped component/release pipeline."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/x810-arch.yml"


class ArchWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.jobs_text = cls.text.split("jobs:\n", 1)[1]
        cls.jobs = re.findall(r"^  ([a-z][a-z0-9_]*):$", cls.jobs_text, re.MULTILINE)

    def test_job_graph_matches_fedora_pipeline_with_kernel_resolution_adaptation(self):
        expected = (
            "publication_identity",
            "build_port_update",
            "plan",
            "prepare_kernel_modules",
            "resolve_rootfs",
            "build_rootfs",
            "publish_full_set",
            "prune_old_releases",
        )
        self.assertEqual(self.jobs, list(expected))
        fedora_jobs = (
            "publication_identity",
            "build_port_update",
            "plan",
            "build_kernel",
            "resolve_rootfs",
            "build_rootfs",
            "publish_full_set",
            "prune_old_releases",
        )
        self.assertEqual(
            ["prepare_kernel_modules" if job == "build_kernel" else job for job in fedora_jobs],
            list(expected),
        )
        self.assertNotIn("pull_request:", self.text)

    def test_port_update_job_tests_builds_and_hands_off_all_arch_package_outputs(self):
        update = self.text.split("  build_port_update:\n", 1)[1].split("  plan:\n", 1)[0]
        for command in (
            "tools/test-x810-install.py",
            "tools/test-arch-port-release.py",
            "tools/build-packages.sh",
            "tools/make-arch-port-update-bundle.py",
            "filename//:/_",
            "name: x810-arch-packages",
            "name: x810-port-update",
        ):
            self.assertIn(command, update)
        self.assertIn("BUILD_RUN_ID", update)
        self.assertIn("write-arch-port-build-info.py", update)

    def test_rootfs_build_consumes_the_exact_prebuilt_package_and_kernel_artifacts(self):
        resolve = self.text.split("  resolve_rootfs:\n", 1)[1].split("  build_rootfs:\n", 1)[0]
        build = self.text.split("  build_rootfs:\n", 1)[1].split("  publish_full_set:\n", 1)[0]
        self.assertIn("needs: [plan, build_port_update, prepare_kernel_modules]", self.text)
        self.assertIn("name: x810-arch-packages", resolve)
        self.assertIn("name: x810-arch-kernel-modules", resolve)
        self.assertIn("name: x810-arch-packages", build)
        self.assertIn("name: x810-arch-kernel-modules", build)
        self.assertIn('X810_PREBUILT_PACKAGES: "1"', build)
        self.assertIn('X810_PREBUILT_KERNEL_MODULES: "1"', build)
        self.assertIn("Arch repositories are rolling", self.text)

    def test_complete_release_includes_tab_companion_update_and_prunes_only_after_validation(self):
        publish = self.text.split("  publish_full_set:\n", 1)[1].split("  prune_old_releases:\n", 1)[0]
        prune = self.text.split("  prune_old_releases:\n", 1)[1]
        publisher = (ROOT / "tools/publish-arch-full-set.sh").read_text()
        for command in ("name: x810-arch-rootfs", "name: x810-port-update", "publish-arch-full-set.sh"):
            self.assertIn(command, publish)
        for asset in ("rootfs.tar.zst", "manifest.json", "SHA256SUMS", "update.zip"):
            self.assertIn(asset, publisher)
            self.assertIn(asset, prune)
        self.assertIn("gh release edit", publisher)
        self.assertIn("--latest", publisher)
        self.assertIn("PUBLISH_RESULT", prune)
        self.assertIn("gh release delete", prune)
        self.assertIn("preserving the previous complete release", prune)


if __name__ == "__main__":
    unittest.main()
