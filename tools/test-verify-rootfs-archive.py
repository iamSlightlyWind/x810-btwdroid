#!/usr/bin/env python3
"""Integration tests for the private GNOME-profile rootfs archive verifier."""

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
                 optional_app: str | None = None,
                 arch_dualboot_backend: bool = True) -> None:
        self.missing_package = missing_package
        self.syscall_sandbox_disabled = syscall_sandbox_disabled
        self.plaintext_shadow = plaintext_shadow
        self.omit_display_manager_alias = omit_display_manager_alias
        self.omit_graphical_display_manager_wants = omit_graphical_display_manager_wants
        self.optional_app = optional_app
        self.arch_dualboot_backend = arch_dualboot_backend

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
                ("home/slightlywind", 0o700, 1000, 1000),
                ("home/slightlywind/.ssh", 0o700, 1000, 1000),
            ):
                self.add_dir(archive, name, mode=mode, uid=uid, gid=gid)
            self.add_file(
                archive,
                "etc/shadow",
                (
                    b"root:!:1:0:99999:7:::\n"
                    + (
                        b"slightlywind:plaintext:1:0:99999:7:::\n"
                        if self.plaintext_shadow
                        else b"slightlywind:$6$salt$digest:1:0:99999:7:::\n"
                    )
                ),
                mode=0o600,
            )
            pacman_conf = (
                b"[options]\nDisableSandboxFilesystem\n"
                + (b"DisableSandboxSyscalls\n" if self.syscall_sandbox_disabled else b"#DisableSandboxSyscalls\n")
                + b"[core]\n"
            )
            self.add_file(archive, "etc/pacman.conf", pacman_conf)
            self.add_file(archive, "etc/sudoers.d/40-windstation", b"slightlywind ALL=(ALL) NOPASSWD: ALL\n", mode=0o440)
            self.add_file(archive, "etc/ssh/ssh_host_ed25519_key", b"test-only-private-key-placeholder\n", mode=0o600)
            self.add_file(archive, "var/lib/tailscale/tailscaled.state", b"test-only-state-placeholder\n", mode=0o600)
            self.add_file(archive, "home/slightlywind/.ssh/authorized_keys", b"ssh-ed25519 test\n", mode=0o600, uid=1000, gid=1000)
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
            self.add_file(archive, "usr/share/polkit-1/actions/io.github.agcarbajo.TabCompanion.Admin.policy", b"<policyconfig/>\n")
            self.add_file(archive, "usr/share/polkit-1/actions/io.github.agcarbajo.TabCompanion.X810.policy", b"<policyconfig/>\n")
            extension_dir = "usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io"
            self.add_file(archive, f"{extension_dir}/extension.js", b"// dualboot\n")
            self.add_file(archive, f"{extension_dir}/metadata.json", b'{"shell-version":["51"]}\n')
            graphical_target = b"[Unit]\nDescription=Graphical Interface\n"
            if not self.omit_graphical_display_manager_wants:
                graphical_target += b"Wants=display-manager.service\n"
            self.add_file(archive, "usr/lib/systemd/system/graphical.target", graphical_target)
            self.add_file(archive, "etc/NetworkManager/system-connections/usb.nmconnection", b"[connection]\nid=test\n", mode=0o600)
            self.add_link(archive, "etc/systemd/system/default.target", "/usr/lib/systemd/system/graphical.target")
            self.add_link(archive, "etc/systemd/system/bluetooth.target.wants/bluetooth.service", "/usr/lib/systemd/system/bluetooth.service")
            if not self.omit_display_manager_alias:
                self.add_link(archive, "etc/systemd/system/display-manager.service", "/usr/lib/systemd/system/gdm.service")
            for package in PACKAGES:
                if package == self.missing_package:
                    continue
                dbdir = f"var/lib/pacman/local/{package}-1.0-1"
                self.add_dir(archive, dbdir, mode=0o755)
                self.add_file(archive, f"{dbdir}/desc", f"%NAME%\n{package}\n\n%VERSION%\n1.0-1\n".encode())
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
    def run_verifier(self, fixture: ArchiveFixture) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "rootfs.tar.zst"
            fixture.write_zstd_archive(archive_path)
            return subprocess.run(
                ["python3", str(VERIFIER), str(archive_path)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    def test_accepts_complete_gnome_profile_image(self):
        result = self.run_verifier(ArchiveFixture())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Arch dualboot support", result.stdout)

    def test_rejects_fedora_only_dualboot_backend(self):
        result = self.run_verifier(ArchiveFixture(arch_dualboot_backend=False))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Arch-aware X810 dualboot backend", result.stderr)

    def test_rejects_missing_package_database_record(self):
        result = self.run_verifier(ArchiveFixture(missing_package="gnome-shell"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required profile packages", result.stderr)

    def test_rejects_missing_gdm_display_manager_alias(self):
        result = self.run_verifier(ArchiveFixture(omit_display_manager_alias=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("enabled-systemd link", result.stderr)

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
        self.assertIn("minimal GNOME profile unexpectedly includes optional desktop apps", result.stderr)

    def test_rejects_plaintext_shadow_password(self):
        result = self.run_verifier(ArchiveFixture(plaintext_shadow=True))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a crypt hash", result.stderr)
        self.assertNotIn("plaintext", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
