#!/usr/bin/env python3
"""Host-side unit checks for the Arch rootfs-only X810 installer."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import hashlib
import json
import sys
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("x810-install")
LOADER = importlib.machinery.SourceFileLoader("x810_arch_install", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None and SPEC.loader is not None
installer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = installer
SPEC.loader.exec_module(installer)


class FakeClient:
    def __init__(self, values: dict[tuple[str, ...], tuple[int, str]] | None = None):
        self.serial = "TESTSERIAL001"
        self.values = values or {}
        self.calls: list[tuple[str, ...]] = []

    def shell(self, *args: str, timeout: int = 30):
        key = tuple(args)
        self.calls.append(key)
        status, stdout = self.values.get(key, (0, ""))
        return subprocess.CompletedProcess(["adb", *args], status, stdout, "")


class ProvisioningClient:
    def __init__(self):
        self.serial = "TESTSERIAL001"
        self.pushed: dict[str, str] = {}
        self.shell_calls: list[tuple[str, ...]] = []

    def push(self, source: Path, target: str):
        self.pushed[target] = Path(source).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(["adb", "push"], 0, "", "")

    def shell(self, *args: str, timeout: int = 30):
        self.shell_calls.append(tuple(args))
        return subprocess.CompletedProcess(["adb", *args], 0, "", "")


class InstallerTests(unittest.TestCase):
    def test_plan_only_is_allowed_without_interactive_tty(self):
        bundle = installer.InstallBundle(Path("/private/rootfs.tar.zst"), "0" * 64, 1024, "test")
        with patch.object(sys, "argv", [str(SCRIPT), "install", "--plan-only"]), \
             patch.object(sys, "stdin", io.StringIO("")), \
             patch.object(sys, "stdout", io.StringIO()), \
             patch.object(installer, "latest_release", return_value={"tag_name": "x810-arch-build-1"}), \
             patch.object(installer, "download_release_install_set", return_value=bundle), \
             patch.object(installer, "run_install", return_value=0) as run_install:
            self.assertEqual(installer.main(), 0)
        run_install.assert_called_once_with(SCRIPT.resolve().parents[1], bundle, None, True)

    def test_extracted_rootfs_checks_gdm_alias_and_graphical_target_dependency(self):
        root = "/mnt/linuxroot"
        client = FakeClient(
            {
                ("readlink", f"{root}/etc/systemd/system/default.target"):
                    (0, "/usr/lib/systemd/system/graphical.target\n"),
                ("readlink", f"{root}/etc/systemd/system/display-manager.service"):
                    (0, "/usr/lib/systemd/system/gdm.service\n"),
                ("readlink", f"{root}/etc/systemd/system/bluetooth.target.wants/bluetooth.service"):
                    (0, "/usr/lib/systemd/system/bluetooth.service\n"),
                ("grep", "-Fq", "Wants=display-manager.service",
                    f"{root}/usr/lib/systemd/system/graphical.target"): (0, ""),
                ("grep", "-Fxq", "ID=archarm", f"{root}/etc/os-release"): (0, ""),
            }
        )
        installer.verify_extracted_rootfs(client, root)
        self.assertIn(("test", "-x", f"{root}/usr/bin/brave"), client.calls)
        self.assertIn(("test", "-x", f"{root}/usr/bin/gnome-terminal"), client.calls)
        self.assertIn(("test", "-x", f"{root}/usr/bin/bluetoothctl"), client.calls)
        self.assertIn(("test", "-x", f"{root}/usr/local/libexec/x810-boot-switch-core"), client.calls)
        self.assertIn(("test", "-x", f"{root}/usr/local/libexec/tab-companion-boot-status"), client.calls)
        self.assertIn(("test", "-x", f"{root}/usr/local/libexec/tab-companion-boot-switch"), client.calls)
        self.assertIn(("test", "-f", f"{root}/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/extension.js"), client.calls)
        self.assertIn(("test", "-f", f"{root}/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json"), client.calls)
        self.assertIn(("grep", "-Fxq", "AutoEnable=true", f"{root}/etc/bluetooth/main.conf"), client.calls)

    def test_extracted_rootfs_rejects_missing_bluetooth_auto_enable(self):
        root = "/mnt/linuxroot"
        client = FakeClient({
            ("readlink", f"{root}/etc/systemd/system/default.target"):
                (0, "/usr/lib/systemd/system/graphical.target\n"),
            ("readlink", f"{root}/etc/systemd/system/display-manager.service"):
                (0, "/usr/lib/systemd/system/gdm.service\n"),
            ("readlink", f"{root}/etc/systemd/system/bluetooth.target.wants/bluetooth.service"):
                (0, "/usr/lib/systemd/system/bluetooth.service\n"),
            ("grep", "-Fxq", "AutoEnable=true", f"{root}/etc/bluetooth/main.conf"): (1, ""),
        })
        with self.assertRaisesRegex(RuntimeError, "BlueZ AutoEnable=true"):
            installer.verify_extracted_rootfs(client, root)

    def test_extracted_rootfs_rejects_graphical_target_without_display_manager_wants(self):
        root = "/mnt/linuxroot"
        client = FakeClient(
            {
                ("readlink", f"{root}/etc/systemd/system/default.target"):
                    (0, "/usr/lib/systemd/system/graphical.target\n"),
                ("readlink", f"{root}/etc/systemd/system/display-manager.service"):
                    (0, "/usr/lib/systemd/system/gdm.service\n"),
                ("readlink", f"{root}/etc/systemd/system/bluetooth.target.wants/bluetooth.service"):
                    (0, "/usr/lib/systemd/system/bluetooth.service\n"),
                ("grep", "-Fq", "Wants=display-manager.service",
                    f"{root}/usr/lib/systemd/system/graphical.target"): (1, ""),
            }
        )
        with self.assertRaisesRegex(RuntimeError, "graphical.target does not pull in"):
            installer.verify_extracted_rootfs(client, root)

    def test_installer_does_not_expect_nonexistent_gdm_wants_link(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("/etc/systemd/system/display-manager.service", source)
        self.assertIn('"Wants=display-manager.service"', source)
        self.assertNotIn("graphical.target.wants/gdm.service", source)

    def test_android_or_unavailable_adb_target_is_refused(self):
        def runner(argv, timeout=30):
            return subprocess.CompletedProcess(argv, 0, "List of devices attached\nserial-1\tdevice product:x\n", "")

        with self.assertRaisesRegex(RuntimeError, "expected TWRP ADB recovery"):
            installer.adb_target("adb", None, runner)

    def test_multiple_adb_targets_need_explicit_serial(self):
        def runner(argv, timeout=30):
            return subprocess.CompletedProcess(argv, 0,
                "List of devices attached\na\trecovery\nb\tdevice\n", "")

        with self.assertRaisesRegex(RuntimeError, "multiple ADB targets"):
            installer.adb_target("adb", None, runner)
        self.assertEqual(installer.adb_target("adb", "a", runner), ("a", "recovery"))

    def test_generic_twrp_model_alias_requires_x810_evidence(self):
        props = {
            "ro.twrp.version": "3.7.1_12-0",
            "ro.product.device": "gts9p",
            "ro.boot.em.model": installer.EXPECTED_TWRP_ALIAS,
            "ro.bootloader": "X810XXS5CYG1",
            "ro.boot.flash.locked": "0",
            "ro.boot.vbmeta.device_state": "unlocked",
            "ro.boot.verifiedbootstate": "orange",
        }
        def shell(*args, timeout=30):
            if args[0] == "getprop":
                return subprocess.CompletedProcess(args, 0, props.get(args[1], "") + "\n", "")
            if args == ("id", "-u"):
                return subprocess.CompletedProcess(args, 0, "0\n", "")
            if args == ("cat", "/proc/cmdline"):
                return subprocess.CompletedProcess(args, 0, "androidboot.em.model=SM-X810\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        client = FakeClient()
        client.shell = shell
        values, checks = installer.twrp_identity(client)
        self.assertEqual(values["model"], installer.EXPECTED_TWRP_ALIAS)
        self.assertFalse(any(check.state == "STOP" for check in checks), checks)
        self.assertIn("generic TWRP model alias", next(c.detail for c in checks if c.label == "Tablet identity"))

    def test_wrong_codename_or_locked_bootloader_stops(self):
        def build_props(device="gts9uwifi", locked="1"):
            props = {
                "ro.twrp.version": "3.7.1", "ro.product.device": device,
                "ro.boot.em.model": "SM-X910", "ro.bootloader": "X910XXS1",
                "ro.boot.flash.locked": locked, "ro.boot.vbmeta.device_state": "locked",
                "ro.boot.verifiedbootstate": "green",
            }
            def shell(*args, timeout=30):
                if args[0] == "getprop":
                    return subprocess.CompletedProcess(args, 0, props.get(args[1], "") + "\n", "")
                if args == ("id", "-u"):
                    return subprocess.CompletedProcess(args, 0, "0\n", "")
                return subprocess.CompletedProcess(args, 0, "", "")
            client = FakeClient()
            client.shell = shell
            return installer.twrp_identity(client)[1]

        checks = build_props()
        self.assertGreaterEqual(sum(c.state == "STOP" for c in checks), 2)
        self.assertTrue(any(c.label == "Bootloader" and c.state == "STOP" for c in checks))

    def test_only_linuxroot_format_command_is_authorized(self):
        args = installer.linuxroot_format_args()
        self.assertEqual(args[0], "mke2fs")
        self.assertEqual(args[-1], "/dev/block/by-name/linuxroot")
        joined = " ".join(args)
        for forbidden in ("userdata", "super", "/boot", "recovery", "vbmeta", "dtbo", "vendor_boot", "init_boot"):
            self.assertNotIn(forbidden, joined)

    def test_partition_validation_requires_correct_label_guid_and_unmounted_target(self):
        info = """Partition number: 35
Partition GUID code: 0FC63DAF-8483-4772-8E79-3D69D8477DE4 (Linux filesystem)
Partition unique GUID: 0FC63DAF-8483-4772-8E79-3D69D8477DE4
First sector: 4000000
Last sector: 5700000
Partition name: 'linuxroot'
"""
        mapping = {
            ("readlink", "-f", installer.LINUXROOT): (0, installer.LINUXROOT_NODE + "\n"),
            ("blockdev", "--getsize64", installer.LINUXROOT): (0, str(64 * 1024**3) + "\n"),
            ("toybox", "blkid", "-s", "LABEL", installer.LINUXROOT):
                (0, f'{installer.LINUXROOT}: LABEL="linuxroot"\n'),
            ("toybox", "blkid", "-s", "TYPE", installer.LINUXROOT):
                (0, f'{installer.LINUXROOT}: TYPE="ext4"\n'),
            ("sgdisk", "--info=35", "/dev/block/sda"): (0, info),
            ("cat", "/proc/mounts"): (0, "rootfs / rootfs rw 0 0\n"),
        }
        facts, checks = installer.validate_partition(FakeClient(mapping), 1024)
        self.assertEqual(facts["node"], installer.LINUXROOT_NODE)
        self.assertFalse(any(c.state == "STOP" for c in checks), checks)

        mapping[("cat", "/proc/mounts")] = (0, "/dev/block/sda35 /mnt/linuxroot ext4 rw 0 0\n")
        with self.assertRaisesRegex(RuntimeError, "already mounted"):
            installer.validate_partition(FakeClient(mapping), 1024)

    def test_target_is_revalidated_immediately_before_format_and_drift_never_formats(self):
        valid_info = (
            "Partition number: 35\n"
            "Partition GUID code: 0FC63DAF-8483-4772-8E79-3D69D8477DE4 (Linux filesystem)\n"
            "Partition unique GUID: 0FC63DAF-8483-4772-8E79-3D69D8477DE4\n"
            "First sector: 4000000\n"
            "Last sector: 5700000\n"
            "Partition name: 'linuxroot'\n"
        )

        def target_mapping(*, node=None, size=64 * 1024**3, label="linuxroot",
                           filesystem="ext4", info=valid_info, mounts="rootfs / rootfs rw 0 0\n"):
            return {
                ("readlink", "-f", installer.LINUXROOT):
                    (0, (node or installer.LINUXROOT_NODE) + "\n"),
                ("blockdev", "--getsize64", installer.LINUXROOT): (0, str(size) + "\n"),
                ("toybox", "blkid", "-s", "LABEL", installer.LINUXROOT):
                    (0, f'{installer.LINUXROOT}: LABEL="{label}"\n'),
                ("toybox", "blkid", "-s", "TYPE", installer.LINUXROOT):
                    (0, f'{installer.LINUXROOT}: TYPE="{filesystem}"\n'),
                ("sgdisk", "--info=35", "/dev/block/sda"): (0, info),
                ("cat", "/proc/mounts"): (0, mounts),
            }

        baseline, checks = installer.validate_partition(FakeClient(target_mapping()), 1024)
        self.assertFalse(any(check.state == "STOP" for check in checks), checks)
        bundle = installer.InstallBundle(Path("/private/rootfs.tar.zst"), "0" * 64, 1024, "test")

        drift_cases = (
            ("wrong resolved device", target_mapping(node="/dev/block/sda34")),
            ("changed exact size", target_mapping(size=65 * 1024**3)),
            ("changed filesystem label", target_mapping(label="userdata")),
            ("changed filesystem type", target_mapping(filesystem="f2fs")),
            ("changed GPT name", target_mapping(info=valid_info.replace("linuxroot", "userdata"))),
            ("changed GPT type", target_mapping(info=valid_info.replace(
                installer.LINUXROOT_TYPE_GUID, "1B81E7E6-F50D-419B-A739-2AEEF8DA3335"))),
            ("mounted target", target_mapping(mounts="/dev/block/sda35 /mnt/linuxroot ext4 rw 0 0\n")),
        )
        for label, mapping in drift_cases:
            with self.subTest(drift=label):
                client = FakeClient(mapping)
                with self.assertRaises(RuntimeError):
                    installer.format_and_install(client, bundle, Path("/not-used"), {}, baseline)
                self.assertNotIn(installer.linuxroot_format_args(), client.calls)

    def test_plan_only_runs_read_only_checks_without_backup_or_block_write(self):
        props = {
            "ro.twrp.version": "3.7.1_12-0", "ro.product.device": "gts9p",
            "ro.boot.em.model": "SM-X816B", "ro.bootloader": "X810XXS5CYG1",
            "ro.boot.flash.locked": "0", "ro.boot.vbmeta.device_state": "unlocked",
            "ro.boot.verifiedbootstate": "orange",
        }
        info = (
            "Partition GUID code: 0FC63DAF-8483-4772-8E79-3D69D8477DE4\n"
            "Partition unique GUID: 0FC63DAF-8483-4772-8E79-3D69D8477DE4\n"
            "First sector: 4000000\nLast sector: 5700000\n"
            "Partition name: 'linuxroot'\n"
        )
        calls = []
        def runner(argv, timeout=30):
            calls.append(argv)
            if argv[1:] == ["devices", "-l"]:
                return subprocess.CompletedProcess(argv, 0, "List of devices attached\nTESTSERIAL001\trecovery\n", "")
            args = tuple(argv[4:])
            if args[:1] == ("getprop",):
                return subprocess.CompletedProcess(argv, 0, props.get(args[1], "") + "\n", "")
            if args == ("id", "-u"):
                return subprocess.CompletedProcess(argv, 0, "0\n", "")
            if args == ("readlink", "-f", installer.LINUXROOT):
                return subprocess.CompletedProcess(argv, 0, installer.LINUXROOT_NODE + "\n", "")
            if args == ("blockdev", "--getsize64", installer.LINUXROOT):
                return subprocess.CompletedProcess(argv, 0, str(64 * 1024**3) + "\n", "")
            if args == ("toybox", "blkid", "-s", "LABEL", installer.LINUXROOT):
                return subprocess.CompletedProcess(argv, 0, f'{installer.LINUXROOT}: LABEL="linuxroot"\n', "")
            if args == ("toybox", "blkid", "-s", "TYPE", installer.LINUXROOT):
                return subprocess.CompletedProcess(argv, 0, f'{installer.LINUXROOT}: TYPE="ext4"\n', "")
            if args == ("sgdisk", "--info=35", "/dev/block/sda"):
                return subprocess.CompletedProcess(argv, 0, info, "")
            if args == ("cat", "/proc/mounts"):
                return subprocess.CompletedProcess(argv, 0, "rootfs / rootfs rw 0 0\n", "")
            if args[:2] == ("sh", "-c"):
                command_words = shlex.split(args[2])
                if len(command_words) == 1:
                    command_words = shlex.split(command_words[0])
                if command_words[:2] != ["command", "-v"]:
                    return subprocess.CompletedProcess(argv, 2, "", "invalid fake preflight command")
                tool = command_words[2]
                if tool not in {"sgdisk", "blockdev", "mke2fs", "e2fsck", "mount", "umount", "sync", "awk", "grep", "readlink", "toybox", "chmod", "chown", "mv", "cp", "mkdir", "rm", "chroot"}:
                    return subprocess.CompletedProcess(argv, 1, "", "")
                return subprocess.CompletedProcess(argv, 0, "/system/bin/" + tool + "\n", "")
            if args == ("toybox", "blkid", "-s", "LABEL", installer.LINUXROOT):
                return subprocess.CompletedProcess(argv, 0, f'{installer.LINUXROOT}: LABEL="linuxroot"\n', "")
            if args == ("cat", "/proc/cmdline"):
                return subprocess.CompletedProcess(argv, 0, "androidboot.em.model=SM-X810\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        bundle = installer.InstallBundle(Path("/private/rootfs.tar.zst"), "0" * 64, 1024, "test")
        with tempfile.TemporaryDirectory() as tmp:
            # The injected runner emulates the ADB CLI; the test should not
            # require a real adb executable to be installed on the host/CI.
            with patch.object(installer.shutil, "which", side_effect=lambda name: f"/fake/{name}"):
                status = installer.run_install(Path(tmp), bundle, plan_only=True, runner=runner)
        self.assertEqual(status, 0)
        commands = [" ".join(argv[4:]) for argv in calls if len(argv) > 4 and argv[3] == "shell"]
        self.assertFalse(any(item.startswith("mke2fs ") or item.startswith("sgdisk --backup") for item in commands), commands)
        self.assertFalse(any("exec-in" in " ".join(argv) or "push" in argv for argv in calls), calls)

    def test_install_details_prompt_for_fresh_identity_and_new_password(self):
        identity = iter(("Test User", "alice", "tablet"))
        secrets = iter(("new-secret", "new-secret"))
        identity_prompts = []
        password_prompts = []
        with patch.object(installer, "hash_password", return_value="$6$hashed") as hash_password:
            details = installer.prompt_install_details(
                password_reader=lambda prompt: (password_prompts.append(prompt), next(secrets))[1],
                input_func=lambda prompt: (identity_prompts.append(prompt), next(identity))[1],
            )
        self.assertEqual(identity_prompts, ["Full name: ", "Linux username: ", "Hostname: "])
        self.assertEqual(password_prompts, ["New Arch user password (hidden): ", "Repeat password: "])
        self.assertEqual(details, {
            "full_name": "Test User", "username": "alice", "hostname": "tablet",
            "password_hash": "$6$hashed",
        })
        hash_password.assert_called_once_with("new-secret")

    def test_install_provisions_a_fresh_user_not_the_template_account(self):
        client = ProvisioningClient()
        installer.provision_rootfs_account(
            client, "/mnt/linuxroot", "alice", "Alice Example", "tablet", "$6$hash",
        )
        script = client.pushed["/tmp/x810-arch-provision.sh"]
        password_file = client.pushed["/tmp/x810-arch-password-hash"]
        shell_syntax = subprocess.run(["sh", "-n"], input=script, text=True, capture_output=True, check=False)
        self.assertEqual(shell_syntax.returncode, 0, shell_syntax.stderr)
        self.assertEqual(password_file, "alice:$6$hash\n")
        self.assertIn('userdel "$SEED"', script)
        self.assertIn("useradd --create-home --uid 1000 --user-group", script)
        self.assertIn("--comment \"$FULL\" \"$NEW\"", script)
        self.assertIn("AllowUsers $NEW", script)
        self.assertIn("%wheel ALL=(ALL:ALL) ALL", script)
        self.assertNotIn("authorized_keys", script)
        self.assertNotIn("NOPASSWD", script)
        self.assertNotIn("<<EOF", script)
        self.assertIn('chroot "$ROOT" /usr/bin/userdel "$SEED"', script)
        self.assertIn('rm -rf "$ROOT/home/$SEED"', script)
        self.assertIn('chroot "$ROOT" /usr/bin/passwd --lock root', script)
        self.assertIn('chmod 0644 "$ROOT/etc/hosts"', script)
        self.assertNotIn("usermod --login", script)
        self.assertNotIn("existing slightlywind", script.lower())
        self.assertNotIn("new-secret", repr(client.pushed))
        self.assertIn(("rm", "-f", "/tmp/x810-arch-provision.sh",
                       "/tmp/x810-arch-password-hash"),
                      client.shell_calls)

    def test_install_provisioning_rejects_invalid_account_identity_before_adb(self):
        client = ProvisioningClient()
        with self.assertRaisesRegex(ValueError, "invalid username"):
            installer.provision_rootfs_account(client, "/mnt/linuxroot", "Alice",
                                               "Alice", "tablet", "$6$hash")
        self.assertEqual(client.pushed, {})

    def test_release_manifest_is_checked_against_github_asset_digest(self):
        tag = "x810-arch-build-123"
        archive_hash = "a" * 64
        manifest = {
            "schema_version": 1,
            "type": installer.RELEASE_TYPE,
            "release_tag": tag,
            "device": {"model": installer.EXPECTED_MODEL, "codename": "gts9pwifi"},
            "os": {"id": "archarm", "arch": "aarch64"},
            "kernel_release": installer.EXPECTED_KERNEL_RELEASE,
            "rootfs": {"archive": "rootfs.tar.zst", "size_bytes": 2048, "sha256": archive_hash},
        }
        payload = json.dumps(manifest).encode()
        digest = hashlib.sha256(payload).hexdigest()
        release = {"tag_name": tag, "assets": [
            {"name": "manifest.json", "size": len(payload), "digest": f"sha256:{digest}",
             "browser_download_url": "https://github.com/example/release/manifest.json"},
            {"name": "rootfs.tar.zst", "size": 2048, "digest": f"sha256:{archive_hash}",
             "browser_download_url": "https://github.com/example/release/rootfs.tar.zst"},
        ]}
        verified, assets = installer._release_manifest(release, opener=lambda *_args, **_kwargs: io.BytesIO(payload))
        self.assertEqual(verified, manifest)
        self.assertIn("rootfs.tar.zst", assets)

        release["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "GitHub's asset digest"):
            installer._release_manifest(release, opener=lambda *_args, **_kwargs: io.BytesIO(payload))

    def test_install_source_never_issues_partition_or_reboot_commands(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('client.shell("dd"', source)
        self.assertNotIn('client.shell("reboot"', source)
        self.assertNotIn('client.run("reboot"', source)
        self.assertNotIn('"userdata", "FORMAT"', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
