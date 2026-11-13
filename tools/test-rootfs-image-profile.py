#!/usr/bin/env python3
"""Policy tests for the GNOME/GDM Arch install image contract."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
VERIFY_PATH = TOOLS / "verify-rootfs-archive.py"
SPEC = importlib.util.spec_from_file_location("rootfs_archive_verifier", VERIFY_PATH)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class RootfsImageProfileTests(unittest.TestCase):
    def test_python_installer_and_internal_build_orchestration(self):
        project = TOOLS.parent
        installer = project / "tools/x810-install"
        self.assertTrue(installer.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3"))
        self.assertTrue(os.access(installer, os.X_OK))
        self.assertFalse((project / "x810-build").exists())
        build_script = project / "rootfs/build-rootfs.sh"
        self.assertTrue(os.access(build_script, os.X_OK))
        for helper in (
            "tools/configure-ssh-rootfs.sh",
            "tools/audit-rootfs.sh",
            "tools/scrub-rootfs-private-state.sh",
            "tools/package-rootfs.sh",
        ):
            self.assertTrue(os.access(project / helper, os.X_OK), f"{helper} must be executable")
        script = build_script.read_text(encoding="utf-8")
        steps = (
            "tools/fetch-alarm-rootfs.py",
            "tools/build-builder-image.sh",
            "tools/verify-alarm-rootfs.sh",
            "tools/prepare-rootfs.sh",
            "tools/fetch-x810-kernel.py",
            "tools/upgrade-rootfs.sh",
            "tools/stage-x810-modules.sh",
            "tools/stage-x810-wifi.sh",
            "tools/configure-ssh-rootfs.sh",
            "tools/build-packages.sh",
            "tools/install-gnome-profile.sh",
            "tools/package-rootfs.sh",
            "tools/make-rootfs-release.py",
        )
        offsets = [script.index(step) for step in steps]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn("networkmanager wpa_supplicant openssh sudo zram-generator", script)
        self.assertIn('X810_PREBUILT_KERNEL_MODULES', script)
        self.assertIn('X810_PREBUILT_PACKAGES', script)
        self.assertIn("work/rootfs already contains a staged tree", script)
        self.assertIn("No build-time user, SSH key, Wi-Fi credential", script)
        self.assertNotIn("adb", script)
        self.assertNotIn("import-connectivity-state.sh", script)
        prepare = (TOOLS / "prepare-rootfs.sh").read_text(encoding="utf-8")
        self.assertIn("configure-alarm-mirrors.py", prepare)
        self.assertIn("Missing or unsafe target ALARM mirrorlist", prepare)

    def test_profile_and_rootfs_audit_report_named_metadata_failures(self):
        project = TOOLS.parent
        profile = (project / "tools/install-gnome-profile.sh").read_text(encoding="utf-8")
        audit = (project / "tools/audit-rootfs.sh").read_text(encoding="utf-8")
        self.assertIn("X810 device-support package is missing usr/share/tab-companion/port.json", profile)
        self.assertIn("Arch port.json was not installed from x810-device-support", profile)
        self.assertIn('audit_check "Arch Tab Companion port metadata is present"', audit)
        self.assertIn('audit_check "dualboot extension metadata is present"', audit)
        self.assertIn('audit_fail "$label"', audit)

    def test_installer_fetches_a_public_release_and_supports_offline_cache(self):
        installer = (TOOLS / "x810-install").read_text(encoding="utf-8")
        self.assertIn('REPOSITORY = "iamSlightlyWind/x810-btwdroid"', installer)
        self.assertIn('RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"', installer)
        self.assertIn("--no-update", installer)
        self.assertIn("rootfs.tar.zst", installer)
        self.assertIn("verify-rootfs-archive.py", installer)
        self.assertIn("format only", installer.lower())

    def test_build_removes_generic_kernel_before_staging_x810_modules(self):
        script = (TOOLS.parent / "rootfs/build-rootfs.sh").read_text(encoding="utf-8")
        upgrade = script.index('"$tools/upgrade-rootfs.sh" networkmanager')
        removal = script.index('"$tools/pacman-target.sh" --builder-mode -R --noconfirm linux-aarch64')
        stage = script.index('"$tools/stage-x810-modules.sh"')
        self.assertLess(upgrade, removal)
        self.assertLess(removal, stage)
        self.assertIn('die "generic linux-aarch64 remains installed', script)
        self.assertNotIn('-Rns --noconfirm linux-aarch64', script)

    def test_archive_requires_gnome_gdm_and_tab_companion_package_records(self):
        self.assertEqual(
            verifier.REQUIRED_PROFILE_PACKAGES,
            {
                "x810-device-support",
                "zram-generator",
                "networkmanager",
                "wpa_supplicant",
                "openssh",
                "sudo",
                "gdm",
                "gnome-shell",
                "gnome-session",
                "gnome-control-center",
                "gnome-terminal",
                "brave-bin",
                "bluez",
                "bluez-utils",
                "pipewire-jack",
                "noto-fonts",
                "tab-companion",
            },
        )
        self.assertEqual(
            verifier.FORBIDDEN_OPTIONAL_DESKTOP_PACKAGES,
            {"gnome-console", "gnome-boxes", "gnome-books"},
        )

    def test_archive_requires_graphical_default_and_enabled_gdm(self):
        self.assertEqual(
            verifier.REQUIRED_SYMLINK_TARGETS,
            {
                "etc/systemd/system/default.target": "usr/lib/systemd/system/graphical.target",
                "etc/systemd/system/display-manager.service": "usr/lib/systemd/system/gdm.service",
                "etc/systemd/system/bluetooth.target.wants/bluetooth.service": "usr/lib/systemd/system/bluetooth.service",
            },
        )
        self.assertEqual(
            verifier.resolved_link_target(
                "etc/systemd/system/display-manager.service",
                "/usr/lib/systemd/system/gdm.service",
            ),
            "usr/lib/systemd/system/gdm.service",
        )

    def test_public_build_removes_bootstrap_credentials_before_archive(self):
        configure = (TOOLS / "configure-ssh-rootfs.sh").read_text(encoding="utf-8")
        audit = (TOOLS / "audit-rootfs.sh").read_text(encoding="utf-8")
        for marker in (r"-name .ssh\*", "ssh_host_*_key", "system-connections",
                       "wpa_supplicant.conf", "/var/lib/tailscale"):
            self.assertIn(marker, configure)
        self.assertIn("No private Wi-Fi, SSH, account, or Tailscale state", configure)
        self.assertIn('target /usr/bin/find /home /root -mindepth 1 -name .ssh\\*', configure)
        self.assertIn('no_private_ssh_wifi_paths()', audit)
        self.assertIn("-name alarm", audit)
        profile = (TOOLS / "install-gnome-profile.sh").read_text(encoding="utf-8")
        self.assertIn('"$script_dir/scrub-rootfs-private-state.sh"', profile)
        self.assertIn('pacman-target.sh" --builder-mode -Sc --noconfirm', profile)
        self.assertIn('"$script_dir/clean-rootfs-cache.sh"', profile)
        self.assertNotIn('--builder-mode -Scc', profile)
        self.assertLess(profile.index('"$script_dir/clean-rootfs-cache.sh"'), profile.index('"$script_dir/audit-rootfs.sh"'))
        cleaner = (TOOLS / "clean-rootfs-cache.sh").read_text(encoding="utf-8")
        self.assertIn('Path("/project/work/rootfs")', cleaner)
        self.assertIn("Private SSH or Wi-Fi credential path remains in target rootfs", audit)
        self.assertIn('audit_check "downloaded pacman package archives are absent" no_cached_packages', audit)
        scrub = (TOOLS / "scrub-rootfs-private-state.sh").read_text(encoding="utf-8")
        for marker in ('-iname ".ssh*"', '-iname "authorized_keys"',
                       '-iname "*ssh_host_*"', '-iname "wpa_supplicant.conf"',
                       'rm -rf -- /var/lib/tailscale',
                       '/etc/NetworkManager/system-connections'):
            self.assertIn(marker, scrub)
        self.assertIn('target /usr/bin/find "${scan_roots[@]}"', scrub)
        self.assertIn('find_sensitive -prune -print0 > "$sensitive_list"', scrub)
        self.assertIn('target /usr/bin/rm -rf -- "$sensitive_path"', scrub)
        self.assertIn("Private SSH, Wi-Fi, or Tailscale state remains", scrub)

    def test_pacman_policy_disables_only_filesystem_sandbox(self):
        text = "[options]\nDisableSandboxFilesystem\n#DisableSandboxSyscalls\n[core]\n"
        self.assertEqual(verifier.parse_pacman_sandbox_options(text), (True, False))
        with self.assertRaisesRegex(ValueError, "syscall sandbox"):
            verifier.parse_pacman_sandbox_options(
                "[options]\nDisableSandboxFilesystem\nDisableSandboxSyscalls\n"
            )
        with self.assertRaisesRegex(ValueError, "filesystem sandbox"):
            verifier.parse_pacman_sandbox_options("[options]\n#DisableSandboxFilesystem\n")

    def test_password_fields_must_be_crypt_hash_or_locked(self):
        self.assertTrue(verifier.password_field_is_hash_or_locked("!"))
        self.assertTrue(verifier.password_field_is_hash_or_locked("$6$salt$digest"))
        self.assertFalse(verifier.password_field_is_hash_or_locked("plaintext-password"))
        verifier.validate_shadow_data(b"root:!:1:0:99999:7:::\nalarm:!:1:0:99999:7:::\n")
        with self.assertRaisesRegex(ValueError, "not a crypt hash"):
            verifier.validate_shadow_data(
                b"root:!:1:0:99999:7:::\nalarm:plaintext-password:1:0:99999:7:::\n"
            )
        with self.assertRaisesRegex(ValueError, "root password must remain locked"):
            verifier.validate_shadow_data(
                b"root:$6$salt$digest:1:0:99999:7:::\nalarm:!:1:0:99999:7:::\n"
            )

    def test_build_profile_uses_full_upgrade_and_enables_gdm_without_starting_it(self):
        script = (TOOLS / "install-gnome-profile.sh").read_text(encoding="utf-8")
        upgrade = (TOOLS / "upgrade-rootfs.sh").read_text(encoding="utf-8")
        docs = (TOOLS.parent / "docs/GNOME-PROFILE.md").read_text(encoding="utf-8")
        pkgbuild = (TOOLS.parent / "packages/tab-companion/PKGBUILD").read_text(encoding="utf-8")
        self.assertIn('upgrade-rootfs.sh" "${desktop_packages[@]}"', script)
        self.assertIn("-Syu", upgrade)
        for package in (
            "x810-device-support",
            "gnome-shell",
            "gnome-session",
            "gdm",
            "gnome-control-center",
            "pipewire-jack",
            "noto-fonts",
            "gnome-terminal",
            "brave-bin",
            "bluez",
            "bluez-utils",
            "zram-generator",
            "python-gobject",
            "python-dbus",
            "gtk4",
            "libadwaita",
        ):
            self.assertIn(package, script)
        package_block = script.split("desktop_packages=(", 1)[1].split(")", 1)[0]
        for optional_app in ("gnome-console", "gnome-boxes", "gnome-books"):
            self.assertNotIn(optional_app, package_block)
        self.assertNotIn("excluded_optional_apps", script)
        self.assertIn("gnome-control-center", script)
        self.assertIn("pipewire-jack", script)
        self.assertIn("noto-fonts", script)
        self.assertIn('systemctl --root="$rootfs" enable bluetooth.service', script)
        self.assertIn("AutoEnable=true", script)
        self.assertIn('echo "Packages: X810 zram/thermal defaults', script)
        self.assertNotIn('echo "Packages: gnome group', script)
        self.assertNotIn(" gnome gdm ", script)
        self.assertIn("group is avoided", docs)
        self.assertIn("gnome-console", docs)
        self.assertIn("gnome-boxes", docs)
        self.assertIn('rm -f "$pkgdir/usr/share/glib-2.0/schemas/gschemas.compiled"', pkgbuild)
        self.assertIn("Tab Companion package must not ship the generated shared gschemas.compiled cache", script)
        self.assertIn("Tab Companion package is missing its GSettings schema XML", script)
        self.assertIn('pacman-target.sh" --builder-mode -U --noconfirm', script)
        self.assertIn('"/work/packages/$(basename -- "$device_package")"', script)
        self.assertIn('pacman-target.sh" --builder-mode -Qip "/work/packages/$(basename -- "$device_package")"', script)
        self.assertIn('"/work/packages/$app_name"', script)
        self.assertIn('systemctl --root="$rootfs" enable gdm.service', script)
        self.assertNotIn("systemctl --root=\"$rootfs\" start gdm", script)
        builder = (TOOLS.parent / "rootfs/build-rootfs.sh").read_text(encoding="utf-8")
        self.assertIn('tools/package-rootfs.sh', builder)
        self.assertNotIn('package-rootfs-private.sh', script + builder)
        self.assertIn('configure-target-pacman.py" --check', script)

    def test_builder_mode_never_disables_the_syscall_sandbox(self):
        pacman_target = (TOOLS / "pacman-target.sh").read_text(encoding="utf-8")
        self.assertIn('run --interactive --rm', pacman_target)
        self.assertNotIn("DisableSandboxSyscalls", pacman_target)
        self.assertIn("DisableSandboxFilesystem", pacman_target)
        self.assertIn("--builder-config", pacman_target)
        self.assertIn("X810_PACMAN_CACHE_DIR", pacman_target)
        self.assertIn("/work/pacman-cache", pacman_target)
        self.assertIn("trap cleanup EXIT", pacman_target)

    def test_audit_container_script_does_not_break_outer_single_quote(self):
        audit = (TOOLS / "audit-rootfs.sh").read_text(encoding="utf-8")
        marker = '"$image" -lc \'\n'
        self.assertIn(marker, audit)
        inner_script = audit.split(marker, 1)[1].rsplit("\n  '\n", 1)[0]
        self.assertNotIn("'", inner_script)

    def test_ssh_configuration_container_script_does_not_break_outer_single_quote(self):
        configure = (TOOLS / "configure-ssh-rootfs.sh").read_text(encoding="utf-8")
        marker = '"$image" -lc \'\n'
        self.assertIn(marker, configure)
        inner_script = configure.split(marker, 1)[1].rsplit("\n  '\n", 1)[0]
        self.assertNotIn("'", inner_script)
        self.assertIn('target() { "${proot[@]}" "$@"; }', inner_script)
        self.assertIn("target /usr/bin/ssh-keygen -A", inner_script)

    def test_private_state_scrub_container_script_does_not_break_outer_single_quote(self):
        scrub = (TOOLS / "scrub-rootfs-private-state.sh").read_text(encoding="utf-8")
        marker = '"$image" -lc \'\n'
        self.assertIn(marker, scrub)
        inner_script = scrub.split(marker, 1)[1].rsplit("\n  '\n", 1)[0]
        self.assertNotIn("'", inner_script)

    def test_builder_failure_leaves_target_pacman_conf_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            # Exercise the real wrapper in an isolated project fixture rather
            # than requiring this test to have a private, staged work/rootfs.
            project = temp / "project"
            test_tools = project / "tools"
            test_tools.mkdir(parents=True)
            for name in ("pacman-target.sh", "configure-target-pacman.py"):
                shutil.copy2(TOOLS / name, test_tools / name)
            rootfs = project / "work/rootfs"
            (rootfs / "etc/pacman.d").mkdir(parents=True)
            target_conf = rootfs / "etc/pacman.conf"
            original = b"[options]\nArchitecture = auto\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n"
            target_conf.write_bytes(original)

            fake_bin = temp / "bin"
            fake_bin.mkdir()
            captured = temp / "builder-pacman.conf"
            captured_args = temp / "podman-args"
            podman_stub = fake_bin / "podman"
            podman_stub.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "builder_conf=\n"
                "for arg in \"$@\"; do\n"
                "  case \"$arg\" in\n"
                "    *:/work/pacman-builder.conf:ro) builder_conf=\"${arg%%:/work/pacman-builder.conf:ro}\" ;;\n"
                "  esac\n"
                "done\n"
                "printf '%s\\n' \"$@\" > \"$CAPTURE_PODMAN_ARGS\"\n"
                "test -n \"$builder_conf\"\n"
                "cp -- \"$builder_conf\" \"$CAPTURE_BUILDER_CONF\"\n"
                "exit 23\n",
                encoding="utf-8",
            )
            podman_stub.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment.get('PATH', '')}"
            environment["CAPTURE_BUILDER_CONF"] = str(captured)
            environment["CAPTURE_PODMAN_ARGS"] = str(captured_args)
            environment["X810_PACMAN_CACHE_DIR"] = str(temp / "pacman-cache")
            result = subprocess.run(
                [str(test_tools / "pacman-target.sh"), "--builder-mode", "-Q", "pacman"],
                check=False,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            self.assertTrue(captured.is_file())
            builder_text = captured.read_text(encoding="utf-8")
            self.assertEqual(builder_text.count("\nDisableSandboxFilesystem\n"), 1)
            self.assertEqual(builder_text.count("\nDisableSandboxSyscalls\n"), 1)
            self.assertIn("CacheDir = /work/pacman-cache", builder_text)
            self.assertIn(
                f"{temp / 'pacman-cache'}:/work/pacman-cache:rw",
                captured_args.read_text(encoding="utf-8").splitlines(),
            )
            self.assertIn("DownloadUser = root", builder_text)
            self.assertEqual(target_conf.read_bytes(), original)
            self.assertEqual(list((project / "tmp").glob("pacman-config.*")), [])


if __name__ == "__main__":
    unittest.main()
