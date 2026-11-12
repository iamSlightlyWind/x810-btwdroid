#!/usr/bin/env python3
"""Integration tests for the public GNOME-profile rootfs archive verifier."""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
VERIFIER = TOOLS / "verify-rootfs-archive.py"
PACKAGES = (
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
)


class ArchiveFixture:
    def __init__(self, *, missing_package: str | None = None,
                 syscall_sandbox_disabled: bool = False,
                 plaintext_shadow: bool = False,
                 omit_display_manager_alias: bool = False,
                 omit_graphical_display_manager_wants: bool = False,
                 os_release_symlink: bool = False,
                 optional_app: str | None = None,
                 arch_dualboot_backend: bool = True,
                 private_credentials: bool | str = False) -> None:
        self.missing_package = missing_package
        self.syscall_sandbox_disabled = syscall_sandbox_disabled
        self.plaintext_shadow = plaintext_shadow
        self.omit_display_manager_alias = omit_display_manager_alias
        self.omit_graphical_display_manager_wants = omit_graphical_display_manager_wants
        self.os_release_symlink = os_release_symlink
        self.optional_app = optional_app
        self.arch_dualboot_backend = arch_dualboot_backend
        self.private_credentials = private_credentials

    @staticmethod
    def add_file(archive: tarfile.TarFile, name: str, data: bytes,
                 *, mode: int = 0o644, uid: int = 0, gid: int = 0) -> None:
        info = tarfile.TarInfo(name)
        info.type = tarfile.REGTYPE
        info.mode = mode
        info.uid = uid
        info.gid = gid
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))

    @staticmethod
    def add_dir(archive: tarfile.TarFile, name: str, *, mode: int = 0o755,
                uid: int = 0, gid: int = 0) -> None:
        info = tarfile.TarInfo(name.rstrip("/") + "/")
        info.type = tarfile.DIRTYPE
        info.mode = mode
        info.uid = uid
        info.gid = gid
        info.size = 0
        archive.addfile(info)

    @staticmethod
    def add_link(archive: tarfile.TarFile, name: str, target: str) -> None:
        info = tarfile.TarInfo(name)
        info.type = tarfile.SYMTYPE
        info.mode = 0o777
        info.uid = 0
        info.gid = 0
        info.linkname = target
        archive.addfile(info)

    def write_tar(self, path: Path) -> None:
        with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as archive:
            for name, mode, uid, gid in (
                ("run", 0o755, 0, 0),
                ("home/alarm", 0o700, 1000, 1000),
            ):
                self.add_dir(archive, name, mode=mode, uid=uid, gid=gid)
            self.add_file(
                archive,
                "etc/shadow",
                (
                    b"root:!:1:0:99999:7:::\n"
                    + (
                        b"alarm:plaintext:1:0:99999:7:::\n"
                        if self.plaintext_shadow
                        else b"alarm:!:1:0:99999:7:::\n"
                    )
                ),
                mode=0o600,
            )
            self.add_file(archive, "etc/passwd",
                          b"root:x:0:0:root:/root:/bin/bash\nalarm:x:1000:1000:Linux User,,,:/home/alarm:/bin/bash\n")
            self.add_file(archive, "etc/group",
                          b"root:x:0:\nalarm:x:1000:\nwheel:x:998:alarm\nvideo:x:986:alarm\naudio:x:985:alarm\ninput:x:987:alarm\nstorage:x:988:alarm\n")
            pacman_conf = (
                b"[options]\nDisableSandboxFilesystem\n"
                + (b"DisableSandboxSyscalls\n" if self.syscall_sandbox_disabled else b"#DisableSandboxSyscalls\n")
                + b"[core]\n"
            )
            self.add_file(archive, "etc/pacman.conf", pacman_conf)
            if self.os_release_symlink:
                self.add_link(archive, "etc/os-release", "../usr/lib/os-release")
                self.add_file(archive, "usr/lib/os-release", b"ID=archarm\nPRETTY_NAME=Arch Linux ARM\n")
            else:
                self.add_file(archive, "etc/os-release", b"ID=archarm\nPRETTY_NAME=Arch Linux ARM\n")
            self.add_file(archive, "etc/sudoers.d/40-windstation", b"%wheel ALL=(ALL:ALL) ALL\n", mode=0o440)
            self.add_file(archive, "etc/ssh/sshd_config.d/90-windstation.conf",
                          b"PasswordAuthentication yes\nPermitRootLogin no\n")
            if self.private_credentials:
                private_path = (self.private_credentials if isinstance(self.private_credentials, str)
                                else "home/alarm/.ssh/authorized_keys")
                self.add_file(archive, private_path, b"private test state\n",
                              mode=0o600, uid=1000, gid=1000)
            self.add_file(archive, "usr/lib/modules/7.2.0-gts9wifi/modules.dep", b"# synthetic modules index\n")
            self.add_file(archive, "usr/lib/firmware/ath11k/WCN6855/hw2.1/board-2.bin", b"synthetic board data\n")
            self.add_file(archive, "usr/lib/systemd/system/gdm.service", b"[Service]\nExecStart=/usr/bin/gdm\n")
            self.add_file(archive, "usr/lib/systemd/system/bluetooth.service", b"[Service]\nExecStart=/usr/lib/bluetooth/bluetoothd\n")
            self.add_file(archive, "usr/bin/bluetoothctl", b"#!/bin/sh\n", mode=0o755)
            self.add_file(archive, "etc/bluetooth/main.conf", b"[Policy]\nAutoEnable=true\n")
            self.add_file(
                archive,
                "usr/local/libexec/x810-boot-switch-core",
                (b"archarm snapshot_current_linux" if self.arch_dualboot_backend else b"fedora only"),
                mode=0o755,
            )
            for name in ("tab-companion-boot-status", "tab-companion-boot-switch"):
                self.add_file(archive, f"usr/local/libexec/{name}", b"#!/bin/sh\n", mode=0o755)
            self.add_file(archive, "usr/libexec/tab-companion-admin", b"#!/bin/sh\n", mode=0o755)
            self.add_file(archive, "usr/share/tab-companion/port.json",
                          b'{"port_id":"x810-arch","device_id":"SM-X810","os_id":"archarm",'
                          b'"os_version":"rolling","arch":"aarch64","workflow_file":"x810-arch.yml",'
                          b'"version":"0.1.0","build_info_path":"/usr/share/tab-companion/port-build.json",'
                          b'"artifact_name":"update","release_tag_prefix":"x810-arch-build",'
                          b'"public_release":true,"capabilities":{"dualboot":true,"port_update":true},'
                          b'"port_update":{"backend":"pacman","available":true},'
                          b'"kernel_update":{"backend":"pacman","available":false}}\n')
            self.add_file(archive, "usr/share/tab-companion/port-build.json",
                          (b'{"schema_version":1,"project":"x810-arch","version":"0.1.0",'
                           b'"run_id":123,"run_number":17,"commit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
                           b'"branch":"main"}\n'))
            self.add_file(archive, "usr/share/polkit-1/actions/io.github.agcarbajo.TabCompanion.Admin.policy", b"<policyconfig/>\n")
            self.add_file(archive, "usr/share/polkit-1/actions/io.github.agcarbajo.TabCompanion.X810.policy", b"<policyconfig/>\n")
            extension_dir = "usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io"
            self.add_file(archive, f"{extension_dir}/extension.js", b"// dualboot\n")
            self.add_file(archive, f"{extension_dir}/metadata.json", b'{"shell-version":["51"]}\n')
            graphical_target = b"[Unit]\nDescription=Graphical Interface\n"
            if not self.omit_graphical_display_manager_wants:
                graphical_target += b"Wants=display-manager.service\n"
            self.add_file(archive, "usr/lib/systemd/system/graphical.target", graphical_target)
            self.add_link(archive, "etc/systemd/system/default.target", "/usr/lib/systemd/system/graphical.target")
            self.add_link(archive, "etc/systemd/system/bluetooth.target.wants/bluetooth.service", "/usr/lib/systemd/system/bluetooth.service")
            if not self.omit_display_manager_alias:
                self.add_link(archive, "etc/systemd/system/display-manager.service", "/usr/lib/systemd/system/gdm.service")
            for package in PACKAGES:
                if package == self.missing_package:
                    continue
                dbdir = f"var/lib/pacman/local/{package}-1.0-1"
                self.add_dir(archive, dbdir, mode=0o755)
                package_version = "0.1.0-3" if package == "x810-device-support" else "1.0-1"
                self.add_file(archive, f"{dbdir}/desc", f"%NAME%\n{package}\n\n%VERSION%\n{package_version}\n".encode())
            if self.optional_app:
                dbdir = f"var/lib/pacman/local/{self.optional_app}-1.0-1"
                self.add_dir(archive, dbdir, mode=0o755)
                self.add_file(archive, f"{dbdir}/desc", f"%NAME%\n{self.optional_app}\n\n%VERSION%\n1.0-1\n".encode())

    def write_zstd_archive(self, path: Path) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tar_path = Path(temporary) / "fixture.tar"
            self.write_tar(tar_path)
            with path.open("wb") as output:
                result = subprocess.run(["zstd", "-q", "-c", str(tar_path)], stdout=output, stderr=subprocess.PIPE)
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors="replace"))


@unittest.skipUnless(shutil.which("zstd"), "zstd is required")
class VerifyRootfsArchiveIntegrationTests(unittest.TestCase):
    def run_verifier(self, fixture: ArchiveFixture, *extra: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "rootfs.tar.zst"
            fixture.write_zstd_archive(archive_path)
            return subprocess.run(
                ["python3", str(VERIFIER), str(archive_path), *extra],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    def test_accepts_complete_gnome_profile_image(self):
        result = self.run_verifier(ArchiveFixture())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Tab Companion dualboot", result.stdout)

    def test_accepts_standard_usr_lib_os_release_symlink(self):
        result = self.run_verifier(ArchiveFixture(os_release_symlink=True))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_release_publisher_can_require_the_embedded_port_build_identity(self):
        result = self.run_verifier(
            ArchiveFixture(), "--expected-port-version", "0.1.0", "--expected-run-id", "123",
            "--expected-run-number", "17", "--expected-commit", "a" * 40, "--expected-branch", "main",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_release_publisher_rejects_a_mismatched_embedded_run_identity(self):
        result = self.run_verifier(
            ArchiveFixture(), "--expected-port-version", "0.1.0", "--expected-run-id", "999",
            "--expected-run-number", "17", "--expected-commit", "a" * 40, "--expected-branch", "main",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match expected run_id", result.stderr)

    def test_release_publisher_requires_rootfs_support_package_to_match_update(self):
        result = self.run_verifier(ArchiveFixture(), "--expected-support-package-version", "0.1.0-3")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        mismatch = self.run_verifier(ArchiveFixture(), "--expected-support-package-version", "0.1.0-4")
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("does not match update.zip", mismatch.stderr)

    def test_rejects_fedora_only_dualboot_backend(self):
        result = self.run_verifier(ArchiveFixture(arch_dualboot_backend=False))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Arch-aware dualboot backend", result.stderr)

    def test_rejects_missing_package_database_record(self):
        result = self.run_verifier(ArchiveFixture(missing_package="gnome-shell"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required packages", result.stderr)

    def test_rejects_missing_gdm_display_manager_alias(self):
        result = self.run_verifier(ArchiveFixture(omit_display_manager_alias=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required systemd link", result.stderr)

    def test_rejects_graphical_target_without_display_manager_wants(self):
        result = self.run_verifier(ArchiveFixture(omit_graphical_display_manager_wants=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("graphical.target does not want display-manager.service", result.stderr)

    def test_rejects_disabling_syscall_sandbox(self):
        result = self.run_verifier(ArchiveFixture(syscall_sandbox_disabled=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("syscall sandbox must remain enabled", result.stderr)

    def test_rejects_optional_full_group_apps_in_minimal_profile(self):
        result = self.run_verifier(ArchiveFixture(optional_app="gnome-boxes"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rootfs contains forbidden packages", result.stderr)

    def test_rejects_plaintext_shadow_password(self):
        result = self.run_verifier(ArchiveFixture(plaintext_shadow=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a crypt hash", result.stderr)
        self.assertNotIn("plaintext", result.stdout + result.stderr)

    def test_rejects_embedded_ssh_credentials(self):
        private_paths = (
            "home/alarm/.ssh/authorized_keys",
            "etc/ssh/ssh_host_rsa_key",
            "var/lib/tailscale/tailscaled.state",
            "etc/wpa_supplicant/wpa_supplicant.conf",
            "etc/NetworkManager/system-connections/old.nmconnection",
        )
        for path in private_paths:
            with self.subTest(path=path):
                result = self.run_verifier(ArchiveFixture(private_credentials=path))
                self.assertNotEqual(result.returncode, 0)
                expected_failure = (
                    "saved NetworkManager credentials" if path.startswith("etc/NetworkManager/")
                    else "saved Wi-Fi credentials" if path.endswith("wpa_supplicant.conf")
                    else "Tailscale state" if path.startswith("var/lib/tailscale/")
                    else "SSH credential material"
                )
                self.assertIn(expected_failure, result.stderr)


if __name__ == "__main__":
    unittest.main()
