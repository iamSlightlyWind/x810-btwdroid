#!/usr/bin/env python3
"""Validate metadata in a private .tar.zst rootfs without exposing file data."""

from __future__ import annotations

import argparse
import json
import posixpath
import pathlib
import re
import stat
import subprocess
import tarfile


REQUIRED_PROFILE_PACKAGES = {
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
}
FORBIDDEN_OPTIONAL_DESKTOP_PACKAGES = {"gnome-console", "gnome-boxes", "gnome-books"}
REQUIRED_SYMLINK_TARGETS = {
    "etc/systemd/system/default.target": "usr/lib/systemd/system/graphical.target",
    "etc/systemd/system/display-manager.service": "usr/lib/systemd/system/gdm.service",
    "etc/systemd/system/bluetooth.target.wants/bluetooth.service": "usr/lib/systemd/system/bluetooth.service",
}


def parse_pacman_sandbox_options(text: str) -> tuple[bool, bool]:
    """Return (filesystem-sandbox-disabled, syscall-sandbox-disabled)."""
    in_options = False
    options_found = False
    filesystem = 0
    syscalls = 0
    for line in text.splitlines():
        section = re.fullmatch(r"\s*\[([^]]+)\]\s*(?:#.*)?", line)
        if section:
            in_options = section.group(1).strip().lower() == "options"
            options_found |= in_options
            continue
        stripped = line.lstrip()
        if not in_options or not stripped or stripped.startswith("#"):
            continue
        key = stripped.split("=", 1)[0].strip().split()[0]
        if key == "DisableSandboxFilesystem":
            filesystem += 1
        elif key == "DisableSandboxSyscalls":
            syscalls += 1
    if not options_found:
        raise ValueError("pacman.conf has no [options] section")
    if filesystem != 1:
        raise ValueError("pacman filesystem sandbox workaround must appear once in [options]")
    if syscalls:
        raise ValueError("pacman syscall sandbox must remain enabled")
    return True, False


def package_name_from_desc(data: bytes) -> str | None:
    """Read only the package name from a pacman local `desc` record."""
    lines = data.decode("utf-8", errors="strict").splitlines()
    values = [index + 1 for index, line in enumerate(lines) if line == "%NAME%"]
    if len(values) != 1 or values[0] >= len(lines):
        raise ValueError("malformed pacman package database desc record")
    name = lines[values[0]].strip()
    if not re.fullmatch(r"[A-Za-z0-9@._+-]+", name):
        raise ValueError("invalid package name in pacman database record")
    return name


def graphical_target_wants_display_manager(data: bytes) -> bool:
    """Check that graphical.target pulls in systemd's GDM alias."""
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("graphical.target is not valid UTF-8") from error
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "Wants" and "display-manager.service" in value.split():
            return True
    return False


def resolved_link_target(path: str, target: str) -> str:
    """Normalize a tar symlink target as a root-relative archive path."""
    if not target or "\x00" in target:
        raise ValueError(f"invalid symlink target at {path}")
    if target.startswith("/"):
        resolved = posixpath.normpath(target.lstrip("/"))
    else:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    result = pathlib.PurePosixPath(resolved)
    if result.is_absolute() or ".." in result.parts:
        raise ValueError(f"symlink escapes rootfs: {path}")
    return str(result)


def password_field_is_hash_or_locked(value: str) -> bool:
    """Allow empty/locked shadow fields or modular crypt hashes, never plaintext."""
    if not value:
        return True
    unprefixed = value.lstrip("!")
    if unprefixed in {"", "*", "LK", "NP"}:
        return True
    if not unprefixed.startswith("$") or any(ch.isspace() for ch in unprefixed):
        return False
    # Standard modular crypt hashes have an algorithm, salt/parameters and a
    # digest separated by '$'.  A value that merely starts with '$' is not
    # sufficient evidence that the field is hashed.
    return unprefixed.count("$") >= 3 and ":" not in unprefixed


def validate_shadow_data(data: bytes) -> None:
    """Fail unless /etc/shadow is structurally valid and contains no plaintext."""
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("/etc/shadow is not valid UTF-8") from error
    entries: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            continue
        fields = line.split(":")
        if len(fields) < 2 or not fields[0] or fields[0] in entries:
            raise ValueError("/etc/shadow has malformed or duplicate account records")
        if not password_field_is_hash_or_locked(fields[1]):
            raise ValueError("/etc/shadow contains a password field that is not a crypt hash or lock marker")
        entries[fields[0]] = fields[1]
    if "slightlywind" not in entries:
        raise ValueError("/etc/shadow is missing the installer account")
    if not entries.get("root", "").startswith(("!", "*")):
        raise ValueError("root password must remain locked in the installer artifact")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=pathlib.Path)
    args = parser.parse_args()
    if not args.archive.is_file():
        parser.error("archive does not exist")

    expected = {
        "etc/shadow": (0, 0, 0o600),
        "etc/pacman.conf": (0, 0, 0o644),
        "etc/sudoers.d/40-windstation": (0, 0, 0o440),
        "etc/ssh/ssh_host_ed25519_key": (0, 0, 0o600),
        "var/lib/tailscale/tailscaled.state": (0, 0, 0o600),
        "run": (0, 0, 0o755),
        "home/slightlywind": (1000, 1000, 0o700),
        "home/slightlywind/.ssh": (1000, 1000, 0o700),
        "home/slightlywind/.ssh/authorized_keys": (1000, 1000, 0o600),
        "usr/lib/modules/7.2.0-gts9wifi/modules.dep": (0, 0, None),
        "usr/lib/firmware/ath11k/WCN6855/hw2.1/board-2.bin": (0, 0, None),
        "usr/lib/systemd/system/gdm.service": (0, 0, None),
        "usr/lib/systemd/system/bluetooth.service": (0, 0, None),
        "usr/bin/bluetoothctl": (0, 0, 0o755),
        "etc/bluetooth/main.conf": (0, 0, None),
        "usr/local/libexec/x810-boot-switch-core": (0, 0, 0o755),
        "usr/local/libexec/tab-companion-boot-status": (0, 0, 0o755),
        "usr/local/libexec/tab-companion-boot-switch": (0, 0, 0o755),
        "usr/libexec/tab-companion-admin": (0, 0, 0o755),
        "usr/share/polkit-1/actions/io.github.agcarbajo.TabCompanion.Admin.policy": (0, 0, None),
        "usr/share/polkit-1/actions/io.github.agcarbajo.TabCompanion.X810.policy": (0, 0, None),
        "usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/extension.js": (0, 0, None),
        "usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json": (0, 0, None),
    }
    seen: dict[str, tuple[int, int, int, bool]] = {}
    nm_profiles: list[str] = []
    run_entries: list[str] = []
    package_records: set[str] = set()
    symlink_targets: dict[str, str] = {}
    pacman_conf: bytes | None = None
    shadow_data: bytes | None = None
    graphical_target_data: bytes | None = None
    bluez_main_conf: bytes | None = None
    dualboot_core_data: bytes | None = None
    dualboot_metadata: bytes | None = None

    # Test the compressed stream first; tarfile's streaming mode below skips
    # payloads without extracting, inspecting, or printing private file data.
    test = subprocess.run(
        ["zstd", "-q", "-t", str(args.archive)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if test.returncode:
        raise SystemExit(f"zstd integrity check failed: {test.stderr.strip()}")

    decompressor = subprocess.Popen(
        ["zstd", "-q", "-dc", str(args.archive)], stdout=subprocess.PIPE
    )
    assert decompressor.stdout is not None
    with tarfile.open(fileobj=decompressor.stdout, mode="r|") as archive:
        for member in archive:
            raw_name = member.name
            normalized = raw_name.removeprefix("./").rstrip("/")
            path = pathlib.PurePosixPath(normalized)
            if path.is_absolute() or ".." in path.parts:
                raise SystemExit(f"unsafe archive path: {raw_name!r}")
            if any("xattr." in key.lower() or "acl." in key.lower() for key in member.pax_headers):
                raise SystemExit("archive contains xattr/ACL records unsupported by TWRP Toybox tar")
            if normalized in REQUIRED_SYMLINK_TARGETS:
                if not member.issym():
                    raise SystemExit(f"expected a systemd symlink, found another file type: {normalized}")
                try:
                    symlink_targets[normalized] = resolved_link_target(normalized, member.linkname)
                except ValueError as error:
                    raise SystemExit(str(error)) from error
            if normalized == "etc/pacman.conf" and member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise SystemExit("could not read archived pacman.conf")
                pacman_conf = stream.read()
            if normalized == "etc/shadow" and member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise SystemExit("could not read archived shadow file")
                shadow_data = stream.read()
            if normalized == "etc/bluetooth/main.conf" and member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise SystemExit("could not read archived BlueZ main.conf")
                bluez_main_conf = stream.read()
            if normalized == "usr/local/libexec/x810-boot-switch-core" and member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise SystemExit("could not read the Arch dualboot backend")
                dualboot_core_data = stream.read()
            if normalized == "usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json" and member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise SystemExit("could not read the dualboot GNOME extension metadata")
                dualboot_metadata = stream.read()
            if normalized == "usr/lib/systemd/system/graphical.target" and member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise SystemExit("could not read graphical.target")
                graphical_target_data = stream.read()
            if (
                member.isfile()
                and normalized.startswith("var/lib/pacman/local/")
                and normalized.endswith("/desc")
            ):
                stream = archive.extractfile(member)
                if stream is None:
                    raise SystemExit("could not read a pacman package database record")
                try:
                    package_name = package_name_from_desc(stream.read())
                except (UnicodeDecodeError, ValueError) as error:
                    raise SystemExit(str(error)) from error
                if package_name in REQUIRED_PROFILE_PACKAGES | FORBIDDEN_OPTIONAL_DESKTOP_PACKAGES:
                    if package_name in package_records:
                        raise SystemExit(f"duplicate pacman package database record: {package_name}")
                    package_records.add(package_name)
            if normalized == "run":
                if not member.isdir():
                    raise SystemExit("archive /run entry is not a directory")
            elif normalized.startswith("run/"):
                run_entries.append(normalized)
            if normalized.startswith("etc/NetworkManager/system-connections/") and normalized.endswith(".nmconnection"):
                if member.isfile():
                    nm_profiles.append(normalized)
                    seen[normalized] = (
                        member.uid,
                        member.gid,
                        stat.S_IMODE(member.mode),
                        member.isfile(),
                    )
            if normalized in expected:
                seen[normalized] = (
                    member.uid,
                    member.gid,
                    stat.S_IMODE(member.mode),
                    member.isfile() or member.isdir(),
                )

    returncode = decompressor.wait()
    if returncode:
        raise SystemExit(f"zstd decompression failed with status {returncode}")
    if len(nm_profiles) != 1:
        raise SystemExit(f"expected exactly one archived NetworkManager profile; found {len(nm_profiles)}")
    expected[nm_profiles[0]] = (0, 0, 0o600)
    if run_entries:
        raise SystemExit("archive unexpectedly contains volatile /run contents")

    missing_packages = REQUIRED_PROFILE_PACKAGES - package_records
    if missing_packages:
        raise SystemExit(f"rootfs package database is missing required profile packages: {', '.join(sorted(missing_packages))}")
    present_optional_apps = package_records & FORBIDDEN_OPTIONAL_DESKTOP_PACKAGES
    if present_optional_apps:
        raise SystemExit(
            "minimal GNOME profile unexpectedly includes optional desktop apps: "
            + ", ".join(sorted(present_optional_apps))
        )
    for path, expected_target in REQUIRED_SYMLINK_TARGETS.items():
        if symlink_targets.get(path) != expected_target:
            raise SystemExit(f"rootfs is missing the required enabled-systemd link: {path}")
    if graphical_target_data is None:
        raise SystemExit("archive is missing a regular graphical.target unit")
    try:
        has_display_manager_wants = graphical_target_wants_display_manager(graphical_target_data)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if not has_display_manager_wants:
        raise SystemExit("graphical.target does not want display-manager.service")
    if bluez_main_conf is None or not re.search(
        rb"(?m)^\s*AutoEnable\s*=\s*true\s*$", bluez_main_conf, re.IGNORECASE
    ):
        raise SystemExit("BlueZ AutoEnable=true is missing from the rootfs")
    if dualboot_core_data is None or b"archarm" not in dualboot_core_data or b"snapshot_current_linux" not in dualboot_core_data:
        raise SystemExit("Arch-aware X810 dualboot backend is missing or stale")
    try:
        extension_data = json.loads(dualboot_metadata or b"null")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid dualboot GNOME extension metadata: {error}") from error
    if not isinstance(extension_data, dict) or "51" not in extension_data.get("shell-version", []):
        raise SystemExit("dualboot GNOME extension does not declare Arch's GNOME Shell 51")
    if pacman_conf is None:
        raise SystemExit("archive is missing a regular /etc/pacman.conf")
    try:
        parse_pacman_sandbox_options(pacman_conf.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, ValueError) as error:
        raise SystemExit(f"invalid archived pacman sandbox policy: {error}") from error
    if shadow_data is None:
        raise SystemExit("archive is missing a regular /etc/shadow")
    try:
        validate_shadow_data(shadow_data)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    for name, (uid, gid, mode) in expected.items():
        label = "NetworkManager profile" if name in nm_profiles else name
        actual = seen.get(name)
        if actual is None:
            raise SystemExit(f"archive is missing required path: {label}")
        if actual[0] != uid or actual[1] != gid:
            raise SystemExit(f"unexpected numeric owner on {label}: {actual[0]}:{actual[1]}")
        if mode is not None and actual[2] != mode:
            raise SystemExit(f"unexpected mode on {label}: {actual[2]:04o}")
        if not actual[3]:
            raise SystemExit(f"required path is not a regular file or directory: {label}")

    print("Rootfs archive verified: GNOME/GDM/Tab Companion with Arch dualboot support, enabled GDM/Bluetooth, pacman sandbox policy, hashed/locked shadow fields, critical owners/modes, one private Wi-Fi profile, no /run payload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
