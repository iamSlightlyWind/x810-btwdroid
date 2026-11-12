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
            "build_packages",
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
            [job for job in expected if job != "build_packages"],
        )
        self.assertIn("build_packages:\n    needs: publication_identity", self.text)
        self.assertIn("build_port_update:\n    needs: build_packages", self.text)
        self.assertNotIn("pull_request:", self.text)

    def test_package_job_builds_and_hands_off_native_arch_packages(self):
        packages = self.text.split("  build_packages:\n", 1)[1].split("  build_port_update:\n", 1)[0]
        for command in (
            "tools/test-x810-install.py",
            "tools/test-arch-port-release.py",
            "tools/build-packages.sh",
            "filename//:/_",
            "name: x810-arch-packages",
            "port-build.json",
        ):
            self.assertIn(command, packages)
        self.assertIn("BUILD_RUN_ID", packages)
        self.assertIn("write-arch-port-build-info.py", packages)

    def test_update_bundle_is_separate_and_does_not_gate_rootfs_jobs(self):
        update = self.text.split("  build_port_update:\n", 1)[1].split("  plan:\n", 1)[0]
        resolve = self.text.split("  resolve_rootfs:\n", 1)[1].split("  build_rootfs:\n", 1)[0]
        build = self.text.split("  build_rootfs:\n", 1)[1].split("  publish_full_set:\n", 1)[0]
        self.assertIn("tools/make-arch-port-update-bundle.py", update)
        self.assertIn("name: x810-port-update", update)
        self.assertNotIn("tools/build-packages.sh", update)
        self.assertIn("needs: [plan, build_packages, prepare_kernel_modules]", self.text)
        self.assertIn("needs.build_packages.result == 'success'", resolve)
        self.assertIn("name: x810-arch-packages", resolve)
        self.assertIn("needs: [plan, build_packages, prepare_kernel_modules, resolve_rootfs]", self.text)
        self.assertIn("needs.build_packages.result == 'success'", build)
        self.assertNotIn("build_port_update", resolve)
        self.assertNotIn("build_port_update", build)

    def test_rootfs_build_consumes_the_exact_prebuilt_package_and_kernel_artifacts(self):
        resolve = self.text.split("  resolve_rootfs:\n", 1)[1].split("  build_rootfs:\n", 1)[0]
        build = self.text.split("  build_rootfs:\n", 1)[1].split("  publish_full_set:\n", 1)[0]
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
