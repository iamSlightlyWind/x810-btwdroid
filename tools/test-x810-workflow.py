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
        self.assertIn("build_port_update:\n    needs: publication_identity", self.text)
        self.assertNotIn("pull_request:", self.text)

    def test_port_update_job_builds_packages_and_hands_off_only_updater_bundle(self):
        update = self.text.split("  build_port_update:\n", 1)[1].split("  plan:\n", 1)[0]
        for command in (
            "tools/test-x810-install.py",
            "tools/test-arch-port-release.py",
            "tools/build-packages.sh",
            "tools/make-arch-port-update-bundle.py",
            "filename//:/_",
            "name: x810-port-update",
            "port-build.json",
        ):
            self.assertIn(command, update)
        self.assertIn("BUILD_RUN_ID", update)
        self.assertIn("write-arch-port-build-info.py", update)
        self.assertNotIn("name: x810-arch-packages", update)
        for marker in (
            "actions/cache/restore@",
            "actions/cache/save@",
            "x810-arch-builder-pacman-port-",
            "x810-makepkg-port-",
            "Finalize Arch builder and makepkg caches",
        ):
            self.assertIn(marker, update)
        self.assertLess(update.index("Restore Arch builder package cache"), update.index("Build the Arch support packages"))
        self.assertLess(update.index("Restore makepkg source cache"), update.index("Build the Arch support packages"))
        self.assertLess(update.index("Finalize Arch builder and makepkg caches"), update.index("Build the Tab Companion updater bundle"))

    def test_rootfs_is_independent_of_the_port_update_job(self):
        resolve = self.text.split("  resolve_rootfs:\n", 1)[1].split("  build_rootfs:\n", 1)[0]
        build = self.text.split("  build_rootfs:\n", 1)[1].split("  publish_full_set:\n", 1)[0]
        self.assertIn("needs: [plan, prepare_kernel_modules]", resolve)
        self.assertIn("needs: [plan, prepare_kernel_modules, resolve_rootfs]", self.text)
        self.assertNotIn("build_port_update", resolve)
        self.assertNotIn("build_port_update", build)
        self.assertNotIn("x810-arch-packages", resolve)
        self.assertNotIn("x810-arch-packages", build)
        self.assertNotIn('X810_PREBUILT_PACKAGES: "1"', build)
        self.assertIn("Stage publication identity for the rootfs package build", build)
        self.assertIn("write-arch-port-build-info.py", build)
        self.assertIn("needs.plan.outputs.publication_run_id", build)
        for marker in (
            "actions/cache/restore@",
            "actions/cache/save@",
            "x810-alarm-bootstrap-",
            "x810-arch-builder-pacman-rootfs-",
            "x810-arch-rootfs-pacman-",
            "x810-makepkg-rootfs-",
            "X810_BUILDER_PACMAN_CACHE_DIR",
            "X810_PACMAN_CACHE_DIR",
            "Finalize Arch rootfs caches after build attempt",
        ):
            self.assertIn(marker, build)
        self.assertLess(build.index("Restore pinned Arch Linux ARM bootstrap"), build.index("Build and audit the complete Arch GNOME rootfs"))
        self.assertLess(build.index("Restore rolling rootfs package cache"), build.index("Build and audit the complete Arch GNOME rootfs"))
        self.assertLess(build.index("Finalize Arch rootfs caches after build attempt"), build.index("Hand the rootfs release set"))
        rootfs_builder = (ROOT / "rootfs/build-rootfs.sh").read_text(encoding="utf-8")
        self.assertIn('"$tools/build-packages.sh"', rootfs_builder)

    def test_rootfs_build_uses_its_own_packages_and_the_verified_kernel_artifact(self):
        resolve = self.text.split("  resolve_rootfs:\n", 1)[1].split("  build_rootfs:\n", 1)[0]
        build = self.text.split("  build_rootfs:\n", 1)[1].split("  publish_full_set:\n", 1)[0]
        self.assertIn("name: x810-arch-kernel-modules", resolve)
        self.assertIn("name: x810-arch-kernel-modules", build)
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
