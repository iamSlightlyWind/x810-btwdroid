#!/usr/bin/env python3
"""Unit tests for the Windstation target pacman sandbox policy."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).with_name("configure-target-pacman.py")
SPEC = importlib.util.spec_from_file_location("target_pacman_policy", TOOL)
assert SPEC is not None and SPEC.loader is not None
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)
MIRROR_TOOL = Path(__file__).with_name("configure-alarm-mirrors.py")
MIRROR_SPEC = importlib.util.spec_from_file_location("alarm_mirror_policy", MIRROR_TOOL)
assert MIRROR_SPEC is not None and MIRROR_SPEC.loader is not None
mirror_policy = importlib.util.module_from_spec(MIRROR_SPEC)
MIRROR_SPEC.loader.exec_module(mirror_policy)


class TargetPacmanPolicyTests(unittest.TestCase):
    def test_upgrade_initializes_trust_before_first_signed_transaction(self):
        upgrade = Path(__file__).with_name("upgrade-rootfs.sh").read_text(encoding="utf-8")
        initial_keyring = upgrade.index('"$script_dir/init-target-keyring.sh"')
        first_upgrade = upgrade.index("pacman_with_retries -Syu")
        keyring_refresh = upgrade.rindex('"$script_dir/init-target-keyring.sh"')
        self.assertLess(initial_keyring, first_upgrade)
        self.assertGreater(keyring_refresh, first_upgrade)
        self.assertIn("for attempt in 1 2 3", upgrade)
        self.assertIn("Pacman transaction failed after three attempts", upgrade)

    def test_alarm_mirror_fallbacks_are_added_before_geoip_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            mirrorlist = Path(temporary) / "mirrorlist"
            mirrorlist.write_text(
                "# ALARM mirrors\nServer = http://mirror.archlinuxarm.org/$arch/$repo\n",
                encoding="utf-8",
            )
            mirrorlist.chmod(0o644)
            self.assertTrue(mirror_policy.configure(mirrorlist))
            result = mirrorlist.read_text(encoding="utf-8")
            geoip = result.index("Server = http://mirror.archlinuxarm.org")
            self.assertLess(result.index("Server = https://ca.us."), geoip)
            self.assertLess(result.index("Server = https://fl.us."), geoip)
            self.assertEqual(result.count("https://ca.us."), 1)
            self.assertEqual(result.count("https://fl.us."), 1)
            self.assertEqual(mirrorlist.stat().st_mode & 0o777, 0o644)
            self.assertFalse(mirror_policy.configure(mirrorlist))
            self.assertEqual(mirrorlist.read_text(encoding="utf-8"), result)

    def test_alarm_mirror_tool_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("Server = http://mirror.archlinuxarm.org/$arch/$repo\n")
            link = root / "mirrorlist"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "regular non-symlink"):
                mirror_policy.configure(link)

    def test_adds_filesystem_workaround_only_to_options(self):
        source = "[options]\n#DisableSandboxFilesystem\n#DisableSandboxSyscalls\n[core]\nServer = example\n"
        result = policy.ensure_target_policy(source)
        self.assertIn("[options]\nDisableSandboxFilesystem\n", result)
        self.assertIn("#DisableSandboxSyscalls\n", result)
        self.assertIn("[core]\nServer = example\n", result)
        policy.check_target_policy(result)

    def test_policy_is_idempotent(self):
        source = "[options]\nDisableSandboxFilesystem\n[core]\n"
        self.assertEqual(policy.ensure_target_policy(source), source)

    def test_builder_workaround_is_confined_to_separate_pacman_config(self):
        source = (
            "[options]\nDownloadUser = alpm\nDisableSandboxFilesystem\n"
            "#DisableSandboxSyscalls\n[core]\nServer = example\n"
        )
        builder = policy.make_builder_only_config(source)
        self.assertEqual(policy.sandbox_state(source), (True, False))
        self.assertEqual(policy.sandbox_state(builder), (True, True))
        self.assertIn("DownloadUser = root", builder)
        self.assertIn("Server = example", builder)
        self.assertEqual(source.count("DisableSandboxSyscalls"), 1)
        self.assertIn("#DisableSandboxSyscalls", source)

    def test_external_package_cache_is_builder_only_and_replaces_default_cache_dirs(self):
        source = (
            "[options]\nCacheDir = /var/cache/pacman/pkg/\n"
            "#CacheDir = /other/cache\nDisableSandboxFilesystem\n"
            "[core]\nServer = example\n"
        )
        builder = policy.make_builder_only_config(source, "/work/pacman-cache")
        self.assertEqual(builder.count("CacheDir = "), 1)
        self.assertIn("CacheDir = /work/pacman-cache\n", builder)
        self.assertNotIn("/var/cache/pacman/pkg", builder)
        self.assertNotIn("/other/cache", builder)
        self.assertIn("Server = example", builder)
        with self.assertRaisesRegex(ValueError, "absolute path"):
            policy.make_builder_only_config(source, "relative/cache")

    def test_rejects_disabling_syscall_sandbox(self):
        source = "[options]\nDisableSandboxSyscalls\n"
        with self.assertRaisesRegex(ValueError, "syscall sandbox"):
            policy.ensure_target_policy(source)

    def test_rejects_duplicate_filesystem_directives(self):
        source = "[options]\nDisableSandboxFilesystem\nDisableSandboxFilesystem\n"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            policy.ensure_target_policy(source)

    def test_check_mode_requires_both_expected_states(self):
        with self.assertRaisesRegex(ValueError, "filesystem sandbox"):
            policy.check_target_policy("[options]\n#DisableSandboxFilesystem\n")
        with self.assertRaisesRegex(ValueError, "syscall sandbox"):
            policy.check_target_policy("[options]\nDisableSandboxFilesystem\nDisableSandboxSyscalls\n")

    def test_file_update_is_atomic_idempotent_and_preserves_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pacman.conf"
            path.write_text("[options]\n#DisableSandboxFilesystem\n#DisableSandboxSyscalls\n")
            path.chmod(0o640)
            self.assertTrue(policy.configure_file(path))
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            content = path.read_text()
            self.assertFalse(policy.configure_file(path))
            self.assertEqual(path.read_text(), content)
            policy.configure_file(path, check_only=True)

    def test_builder_config_output_is_0600_and_source_is_not_modified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "target.conf"
            output = root / "builder" / "pacman.conf"
            original = "[options]\nDownloadUser = alpm\n#DisableSandboxFilesystem\n#DisableSandboxSyscalls\n"
            source.write_text(original)
            policy.write_builder_config(source, output)
            self.assertEqual(source.read_text(), original)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(policy.sandbox_state(output.read_text()), (True, True))

    def test_builder_config_can_write_external_cache_without_mutating_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "target.conf"
            output = root / "builder" / "pacman.conf"
            original = "[options]\nCacheDir = /var/cache/pacman/pkg/\nDisableSandboxFilesystem\n"
            source.write_text(original)
            policy.write_builder_config(source, output, "/work/pacman-cache")
            self.assertEqual(source.read_text(), original)
            self.assertIn("CacheDir = /work/pacman-cache\n", output.read_text())

    def test_builder_image_uses_external_pacman_cache_when_configured(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            tools_dir = project / "tools"
            (tools_dir / "builder").mkdir(parents=True)
            shutil.copy2(Path(__file__).with_name("build-builder-image.sh"), tools_dir)
            shutil.copy2(Path(__file__).parent / "builder/Containerfile", tools_dir / "builder")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            podman = fake_bin / "podman"
            podman.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$@\" > \"$CAPTURE_ARGS\"\n",
                encoding="utf-8",
            )
            podman.chmod(0o755)
            cache = root / "builder-cache"
            capture = root / "args"
            env = os.environ.copy()
            env.update({
                "PATH": f"{fake_bin}:{env.get('PATH', '')}",
                "X810_BUILDER_PACMAN_CACHE_DIR": str(cache),
                "PODMAN_ROOT_OVERRIDE": str(root / "podman-root"),
                "PODMAN_RUNROOT_OVERRIDE": str(root / "podman-run"),
                "CAPTURE_ARGS": str(capture),
            })
            result = subprocess.run(
                [str(tools_dir / "build-builder-image.sh")], check=False, env=env,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            args = capture.read_text(encoding="utf-8").splitlines()
            self.assertIn(f"{cache}:/var/cache/pacman/pkg:rw,z", args)
            self.assertIn("X810_EXTERNAL_PACMAN_CACHE=1", args)

    def test_refuses_symlinked_or_missing_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real.conf"
            real.write_text("[options]\n")
            link = root / "link.conf"
            link.symlink_to(real)
            with self.assertRaisesRegex(ValueError, "regular, non-symlink"):
                policy.configure_file(link)


if __name__ == "__main__":
    unittest.main()
