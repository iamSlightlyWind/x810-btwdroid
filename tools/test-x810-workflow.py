#!/usr/bin/env python3
"""Guard the Arch workflow's Fedora-shaped component/release pipeline."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/x810-arch.yml"
FEDORA_WORKFLOW = ROOT.parent / "x810-fedroid/.github/workflows/x810-fedora.yml"


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
        self.assertIn("build_port_update:\n    needs: [publication_identity, plan]", self.text)
        self.assertIn("needs.plan.outputs.reuse_release != 'true'", self.text)
        self.assertNotIn("pull_request:", self.text)

    def test_publication_identity_is_the_same_fedora_gate_except_repo_paths(self):
        fedora = FEDORA_WORKFLOW.read_text(encoding="utf-8") if FEDORA_WORKFLOW.is_file() else None

        def job_block(text: str, name: str) -> str:
            start = text.index(f"  {name}:\n")
            following = re.search(r"\n  [a-z][a-z0-9_]*:\n", text[start + 1:])
            end = start + 1 + following.start() if following else len(text)
            block = text[start:end]
            trailing_comment = block.find("\n  #")
            return block[:trailing_comment] if trailing_comment >= 0 else block

        arch_identity = job_block(self.text, "publication_identity")
        arch_identity = arch_identity.replace("x810-arch.yml", "WORKFLOW.yml")
        # These are deliberately the only workflow-specific release-input paths.
        arch_identity = arch_identity.replace(
            "PORT_VERSION README.md LICENSE rootfs docs packages tools .gitignore .github/workflows/WORKFLOW.yml",
            "PORT_VERSION kernel boot rootfs specs tools .github/workflows/WORKFLOW.yml",
        )
        if fedora is not None:
            fedora_identity = job_block(fedora, "publication_identity").replace(
                "x810-fedora.yml", "WORKFLOW.yml"
            )
            self.assertEqual(arch_identity, fedora_identity)
        else:
            # Keep the contract test runnable in GitHub Actions, which checks
            # out this repository only and does not have the sibling Fedora repo.
            self.assertIn('github.ref == \'refs/heads/main\'', arch_identity)
            self.assertIn('event=push&status=completed&per_page=100', arch_identity)
            self.assertIn('select(.conclusion == "success" and .head_branch == "main")', arch_identity)
            self.assertIn('git diff --quiet "$commit" "$GITHUB_SHA" --', arch_identity)
            self.assertIn('No successful main-branch push build is available for this manual run.', arch_identity)
            self.assertIn('Release inputs changed since the last successful push.', arch_identity)

    def test_all_checkouts_disable_persisted_git_credentials_in_both_workflows(self):
        workflows = [self.text]
        if FEDORA_WORKFLOW.is_file():
            workflows.append(FEDORA_WORKFLOW.read_text(encoding="utf-8"))
        for workflow in workflows:
            step_headers = list(re.finditer(r"^\s*- name: .+$", workflow, re.MULTILINE))
            checked_out = 0
            for index, header in enumerate(step_headers):
                end = step_headers[index + 1].start() if index + 1 < len(step_headers) else len(workflow)
                step = workflow[header.start():end]
                if "uses: actions/checkout@" in step:
                    checked_out += 1
                    self.assertIn("persist-credentials: false", step)
            self.assertGreater(checked_out, 0)

    def test_release_pruning_permissions_and_success_gate_match_fedora(self):
        workflows = [self.text]
        fedora = FEDORA_WORKFLOW.read_text(encoding="utf-8") if FEDORA_WORKFLOW.is_file() else None
        if fedora is not None:
            workflows.append(fedora)
        for workflow in workflows:
            prune = workflow.split("  prune_old_releases:\n", 1)[1]
            self.assertIn("    permissions:\n      contents: write", prune)
            self.assertIn("PUBLISH_RESULT", prune)
            self.assertIn("REFUSING to prune", prune)
            self.assertIn("preserving the previous complete release set", prune)
        arch_publish = self.text.split("  publish_full_set:\n", 1)[1].split("  prune_old_releases:\n", 1)[0]
        publishes = [arch_publish]
        if fedora is not None:
            publishes.append(fedora.split("  publish_full_set:\n", 1)[1].split("  prune_old_releases:\n", 1)[0])
        for publish in publishes:
            self.assertIn("    permissions:\n      actions: read\n      contents: write", publish)
            self.assertIn("needs.build_port_update.result == 'success'", publish)

    def test_unchanged_manual_run_reuses_latest_complete_release_without_building(self):
        plan = self.text.split("  plan:\n", 1)[1].split("  prepare_kernel_modules:\n", 1)[0]
        self.assertIn("reuse_release: ${{ steps.plan.outputs.reuse_release }}", plan)
        self.assertIn('FORCE_REBUILD: ${{ inputs.rebuild || false }}', plan)
        self.assertIn('if [[ "$FORCE_REBUILD" != true ]]', plan)
        self.assertIn('latest_tag" == "$release_tag"', plan)
        self.assertIn('manifest.get("source_commit") != commit', plan)
        self.assertIn('manifest.get("build_inputs_key", "")', plan)
        self.assertIn('boot = kernel.get("boot_images")', plan)
        self.assertIn('releases/tags/$latest_tag', plan)
        self.assertIn('api_by_name[name]["digest"]', plan)
        self.assertIn('--pattern manifest.json --pattern SHA256SUMS', plan)
        self.assertNotIn('--pattern rootfs.tar.zst', plan)
        self.assertNotIn('--pattern update.zip', plan)
        self.assertIn(r'echo "- Complete release: inputs and checksums match the latest published release; **reuse \`$release_tag\`', plan)
        self.assertIn("reuse_release=true", plan)
        self.assertIn("skip every build", plan)
        for job in ("build_port_update", "prepare_kernel_modules", "resolve_rootfs", "build_rootfs", "publish_full_set"):
            block = self.text.split(f"  {job}:\n", 1)[1]
            if job == "build_port_update":
                block = block.split("  plan:\n", 1)[0]
            elif job == "prepare_kernel_modules":
                block = block.split("  resolve_rootfs:\n", 1)[0]
            elif job == "resolve_rootfs":
                block = block.split("  build_rootfs:\n", 1)[0]
            elif job == "build_rootfs":
                block = block.split("  publish_full_set:\n", 1)[0]
            else:
                block = block.split("  prune_old_releases:\n", 1)[0]
            self.assertIn("reuse_release != 'true'", block, job)

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

    def test_aggregate_publication_and_prune_follow_fedora_success_gating(self):
        fedora = FEDORA_WORKFLOW.read_text(encoding="utf-8") if FEDORA_WORKFLOW.is_file() else None
        publish = self.text.split("  publish_full_set:\n", 1)[1].split("  prune_old_releases:\n", 1)[0]
        prune = self.text.split("  prune_old_releases:\n", 1)[1]
        publishes = [publish]
        prunes = [prune]
        if fedora is not None:
            publishes.append(fedora.split("  publish_full_set:\n", 1)[1].split("  prune_old_releases:\n", 1)[0])
            prunes.append(fedora.split("  prune_old_releases:\n", 1)[1])
        for workflow in publishes:
            self.assertIn("needs.plan.result == 'success'", workflow)
            self.assertIn("needs.build_port_update.result == 'success'", workflow)
        for workflow in prunes:
            self.assertIn("PUBLISH_RESULT", workflow)
            self.assertIn("repos/$GITHUB_REPOSITORY/releases/latest", workflow)
            self.assertIn("preserving the previous complete release set", workflow)
            self.assertIn("REFUSING to prune", workflow)
            self.assertIn("gh release delete", workflow)

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
