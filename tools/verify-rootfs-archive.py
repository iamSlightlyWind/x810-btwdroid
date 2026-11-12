#!/usr/bin/env python3
"""Stream-validate a public Arch rootfs archive without extracting it."""

from __future__ import annotations

import argparse
import json
import pathlib
import posixpath
import re
import stat
import subprocess
import tarfile


KERNEL_RELEASE = "7.2.0-gts9wifi"
REQUIRED_PROFILE_PACKAGES = {
    "x810-device-support", "zram-generator", "networkmanager", "wpa_supplicant",
    "openssh", "sudo", "gdm", "gnome-shell", "gnome-session",
    "gnome-control-center", "gnome-terminal", "brave-bin", "bluez",
    "bluez-utils", "pipewire-jack", "noto-fonts", "tab-companion",
}
FORBIDDEN_OPTIONAL_DESKTOP_PACKAGES = {"gnome-console", "gnome-boxes", "gnome-books"}
REQUIRED_SYMLINK_TARGETS = {
    "etc/systemd/system/default.target": "usr/lib/systemd/system/graphical.target",
    "etc/systemd/system/display-manager.service": "usr/lib/systemd/system/gdm.service",
    "etc/systemd/system/bluetooth.target.wants/bluetooth.service": "usr/lib/systemd/system/bluetooth.service",
}
EXPECTED_FILES: dict[str, tuple[int, int, int | None]] = {
    "etc/shadow": (0, 0, 0o600),
    "etc/passwd": (0, 0, 0o644),
    "etc/pacman.conf": (0, 0, 0o644),
    "etc/sudoers.d/40-windstation": (0, 0, 0o440),
    "etc/ssh/sshd_config.d/90-windstation.conf": (0, 0, 0o644),
    f"usr/lib/modules/{KERNEL_RELEASE}/modules.dep": (0, 0, None),
    "usr/lib/systemd/system/gdm.service": (0, 0, None),
    "usr/lib/systemd/system/bluetooth.service": (0, 0, None),
    "usr/lib/systemd/system/graphical.target": (0, 0, None),
    "usr/bin/bluetoothctl": (0, 0, 0o755),
    "etc/bluetooth/main.conf": (0, 0, None),
    "usr/local/libexec/x810-boot-switch-core": (0, 0, 0o755),
    "usr/local/libexec/tab-companion-boot-status": (0, 0, 0o755),
    "usr/local/libexec/tab-companion-boot-switch": (0, 0, 0o755),
    "usr/share/tab-companion/port.json": (0, 0, None),
    "usr/share/tab-companion/port-build.json": (0, 0, 0o644),
    "usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/extension.js": (0, 0, None),
    "usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json": (0, 0, None),
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


def package_name_from_desc(data: bytes) -> str:
    lines = data.decode("utf-8", errors="strict").splitlines()
    values = [index + 1 for index, line in enumerate(lines) if line == "%NAME%"]
    if len(values) != 1 or values[0] >= len(lines):
        raise ValueError("malformed pacman package database desc record")
    name = lines[values[0]].strip()
    if not re.fullmatch(r"[A-Za-z0-9@._+-]+", name):
        raise ValueError("invalid package name in pacman database record")
    return name


def package_version_from_desc(data: bytes) -> str:
    lines = data.decode("utf-8", errors="strict").splitlines()
    values = [index + 1 for index, line in enumerate(lines) if line == "%VERSION%"]
    if len(values) != 1 or values[0] >= len(lines):
        raise ValueError("malformed pacman package database version record")
    version = lines[values[0]].strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:.+_~-]{0,127}", version):
        raise ValueError("invalid package version in pacman database record")
    return version


def graphical_target_wants_display_manager(data: bytes) -> bool:
    text = data.decode("utf-8", errors="strict")
    return any(
        key.strip() == "Wants" and "display-manager.service" in value.split()
        for line in text.splitlines()
        for key, separator, value in [line.partition("=")]
        if separator
    )


def resolved_link_target(path: str, target: str) -> str:
    if not target or "\x00" in target:
        raise ValueError(f"invalid symlink target at {path}")
    resolved = pathlib.PurePosixPath(target.lstrip("/")) if target.startswith("/") else pathlib.PurePosixPath(
        posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    )
    if resolved.is_absolute() or ".." in resolved.parts:
        raise ValueError(f"symlink escapes rootfs: {path}")
    return str(resolved)


def password_field_is_hash_or_locked(value: str) -> bool:
    if not value:
        return True
    unprefixed = value.lstrip("!")
    if unprefixed in {"", "*", "LK", "NP"}:
        return True
    return unprefixed.startswith("$") and unprefixed.count("$") >= 3 and ":" not in unprefixed and not any(
        ch.isspace() for ch in unprefixed
    )


def validate_shadow_data(data: bytes) -> None:
    text = data.decode("utf-8", errors="strict")
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
    for account in ("root", "alarm"):
        value = entries.get(account, "")
        if not value.startswith(("!", "*")):
            raise ValueError(f"{account} password must remain locked in the public installer image")


def _read_member(archive: tarfile.TarFile, member: tarfile.TarInfo, label: str) -> bytes:
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"could not read archived {label}")
    return stream.read()


def verify_archive(path: pathlib.Path,
                   expected_port_identity: dict[str, object] | None = None,
                   expected_support_package_version: str | None = None) -> None:
    test = subprocess.run(["zstd", "-q", "-t", str(path)], check=False,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if test.returncode:
        raise ValueError(f"zstd integrity check failed: {test.stderr.strip()}")
    seen: dict[str, tuple[int, int, int, bool, str]] = {}
    package_records: set[str] = set()
    package_versions: dict[str, str] = {}
    run_entries: list[str] = []
    symlinks: dict[str, str] = {}
    captured: dict[str, bytes] = {}
    nm_profile_count = 0
    module_releases: set[str] = set()
    decompressor = subprocess.Popen(["zstd", "-q", "-dc", str(path)], stdout=subprocess.PIPE)
    assert decompressor.stdout is not None
    try:
        with tarfile.open(fileobj=decompressor.stdout, mode="r|") as archive:
            for member in archive:
                raw = member.name
                normalized = raw.removeprefix("./").rstrip("/")
                rel = pathlib.PurePosixPath(normalized)
                if rel.is_absolute() or ".." in rel.parts:
                    raise ValueError(f"unsafe archive path: {raw!r}")
                if any("xattr." in key.lower() or "acl." in key.lower() for key in member.pax_headers):
                    raise ValueError("archive contains xattr/ACL records unsupported by TWRP Toybox tar")
                if normalized in seen:
                    raise ValueError(f"duplicate archive path: {normalized}")
                link_target = ""
                if member.issym():
                    link_target = resolved_link_target(normalized, member.linkname)
                    if normalized in REQUIRED_SYMLINK_TARGETS:
                        symlinks[normalized] = link_target
                seen[normalized] = (member.uid, member.gid, stat.S_IMODE(member.mode),
                                    member.isfile() or member.isdir(), link_target)

                # No secrets or host-specific bootstrap state may enter a
                # public release. Only filenames are examined; file values
                # are never printed.
                lower = normalized.lower()
                if (lower.endswith("/authorized_keys") or "/.ssh" in lower
                        or "/ssh_host_" in lower):
                    raise ValueError("public rootfs contains SSH credential material")
                if lower.startswith("var/lib/tailscale/"):
                    raise ValueError("public rootfs contains Tailscale state")
                if lower.endswith("/wpa_supplicant.conf"):
                    raise ValueError("public rootfs contains saved Wi-Fi credentials")
                if (lower.startswith("etc/NetworkManager/system-connections/")
                        and member.isfile()):
                    raise ValueError("public rootfs contains saved NetworkManager credentials")
                if normalized.startswith("etc/NetworkManager/system-connections/") and member.isfile():
                    nm_profile_count += 1
                if normalized == "run":
                    if not member.isdir():
                        raise ValueError("archive /run entry is not a directory")
                elif normalized.startswith("run/"):
                    run_entries.append(normalized)
                if normalized.startswith("usr/lib/modules/"):
                    tail = normalized[len("usr/lib/modules/"):]
                    if "/" in tail:
                        module_releases.add(tail.split("/", 1)[0])
                if (member.isfile() and normalized.startswith("var/lib/pacman/local/")
                        and normalized.endswith("/desc")):
                    desc = _read_member(archive, member, "pacman database record")
                    name = package_name_from_desc(desc)
                    if name in REQUIRED_PROFILE_PACKAGES | FORBIDDEN_OPTIONAL_DESKTOP_PACKAGES | {"linux-aarch64"}:
                        if name in package_records:
                            raise ValueError(f"duplicate pacman package record: {name}")
                        package_records.add(name)
                        package_versions[name] = package_version_from_desc(desc)
                if member.isfile() and normalized in {
                    "etc/pacman.conf", "etc/shadow", "etc/passwd", "etc/os-release",
                    "etc/bluetooth/main.conf", "etc/sudoers.d/40-windstation",
                    "etc/ssh/sshd_config.d/90-windstation.conf",
                    "usr/lib/systemd/system/graphical.target",
                    "usr/local/libexec/x810-boot-switch-core",
                    "usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json",
                    "usr/share/tab-companion/port.json",
                    "usr/share/tab-companion/port-build.json",
                }:
                    captured[normalized] = _read_member(archive, member, normalized)
    finally:
        decompressor.stdout.close()
    if decompressor.wait() != 0:
        raise ValueError("zstd decompression failed")

    missing = REQUIRED_PROFILE_PACKAGES - package_records
    if missing:
        raise ValueError("pacman database missing required packages: " + ", ".join(sorted(missing)))
    if (expected_support_package_version is not None
            and package_versions.get("x810-device-support") != expected_support_package_version):
        raise ValueError("rootfs x810-device-support package version does not match update.zip")
    forbidden_packages = package_records & (FORBIDDEN_OPTIONAL_DESKTOP_PACKAGES | {"linux-aarch64"})
    if forbidden_packages:
        raise ValueError("rootfs contains forbidden packages: " + ", ".join(sorted(forbidden_packages)))
    if nm_profile_count:
        raise ValueError("public rootfs must not contain saved NetworkManager credentials")
    if run_entries:
        raise ValueError("archive unexpectedly contains volatile /run contents")
    if module_releases != {KERNEL_RELEASE}:
        raise ValueError(f"rootfs must contain only matching X810 module release {KERNEL_RELEASE}; got {sorted(module_releases)}")
    for path, target in REQUIRED_SYMLINK_TARGETS.items():
        if symlinks.get(path) != target:
            raise ValueError(f"missing required systemd link: {path}")

    for name, (uid, gid, mode) in EXPECTED_FILES.items():
        actual = seen.get(name)
        if actual is None or not actual[3]:
            raise ValueError(f"archive is missing required regular file: {name}")
        if actual[0] != uid or actual[1] != gid:
            raise ValueError(f"unexpected owner for {name}: {actual[0]}:{actual[1]}")
        if mode is not None and actual[2] != mode:
            raise ValueError(f"unexpected mode for {name}: {actual[2]:04o}")

    try:
        validate_shadow_data(captured["etc/shadow"])
        passwd_lines = captured["etc/passwd"].decode("utf-8").splitlines()
        records = [line.split(":") for line in passwd_lines if line]
        alarm = [record for record in records if record[0] == "alarm"]
        if len(alarm) != 1 or alarm[0][2:4] != ["1000", "1000"] or alarm[0][5:] != ["/home/alarm", "/bin/bash"]:
            raise ValueError("public rootfs must contain the generic locked UID/GID 1000 alarm installer seed")
        if any(len(record) < 7 and record[0] == "alarm" for record in records):
            raise ValueError("malformed alarm passwd entry")
        if any(record[2:4] == ["1000", "1000"] and record[0] != "alarm" for record in records):
            raise ValueError("public rootfs contains an unexpected UID/GID 1000 account")
        if any(record[5].startswith("/home/") and record[0] != "alarm" for record in records if len(record) >= 7):
            raise ValueError("public rootfs contains an unexpected human home account")
        home_entries = {name.split("/", 1)[1].rstrip("/") for name in seen
                        if name.startswith("home/") and name != "home" and "/" not in name[5:].rstrip("/")}
        if home_entries - {"alarm"}:
            raise ValueError("public rootfs contains an unexpected home directory")
        release_lines = captured["etc/os-release"].decode("utf-8").splitlines()
        if "ID=archarm" not in release_lines:
            raise ValueError("rootfs is not Arch Linux ARM")
        parse_pacman_sandbox_options(captured["etc/pacman.conf"].decode("utf-8"))
        if not graphical_target_wants_display_manager(captured["usr/lib/systemd/system/graphical.target"]):
            raise ValueError("graphical.target does not want display-manager.service")
        if not re.search(rb"(?m)^\s*AutoEnable\s*=\s*true\s*$", captured["etc/bluetooth/main.conf"], re.I):
            raise ValueError("BlueZ AutoEnable=true is missing")
        if b"PasswordAuthentication yes" not in captured["etc/ssh/sshd_config.d/90-windstation.conf"]:
            raise ValueError("password-based SSH is not enabled for the install-provisioned account")
        if b"PermitRootLogin no" not in captured["etc/ssh/sshd_config.d/90-windstation.conf"]:
            raise ValueError("root SSH login must be disabled")
        if b"%wheel ALL=(ALL:ALL) ALL" not in captured["etc/sudoers.d/40-windstation"]:
            raise ValueError("wheel sudo policy is missing")
        port = json.loads(captured["usr/share/tab-companion/port.json"])
        if not isinstance(port, dict) or port.get("port_id") != "x810-arch":
            raise ValueError("Tab Companion Arch port metadata is missing or invalid")
        expected_port_fields = {
            "device_id": "SM-X810",
            "os_id": "archarm",
            "os_version": "rolling",
            "arch": "aarch64",
            "workflow_file": "x810-arch.yml",
            "artifact_name": "update",
            "release_tag_prefix": "x810-arch-build",
        }
        if (any(port.get(key) != value for key, value in expected_port_fields.items())
                or port.get("public_release") is not True):
            raise ValueError("Tab Companion Arch update target/release metadata is invalid")
        capabilities = port.get("capabilities")
        if (not isinstance(capabilities, dict) or capabilities.get("dualboot") is not True
                or capabilities.get("port_update") is not True
                or port.get("port_update") != {"backend": "pacman", "available": True}
                or port.get("kernel_update") != {"backend": "pacman", "available": False}):
            raise ValueError("Arch port metadata must enable dualboot and the package feed, but disable kernel updates")
        port_version = port.get("version")
        if (not isinstance(port_version, str)
                or not re.fullmatch(r"(?:0|[1-9][0-9]{0,19})\.(?:0|[1-9][0-9]{0,19})\.(?:0|[1-9][0-9]{0,19})", port_version)
                or port.get("build_info_path") != "/usr/share/tab-companion/port-build.json"):
            raise ValueError("Arch port update version/build-info metadata is missing or invalid")
        build_info = json.loads(captured["usr/share/tab-companion/port-build.json"])
        if (not isinstance(build_info, dict)
                or build_info.get("schema_version") != 1
                or build_info.get("project") != "x810-arch"
                or build_info.get("version") != port_version
                or isinstance(build_info.get("run_id"), bool)
                or not isinstance(build_info.get("run_id"), int) or build_info["run_id"] < 1
                or isinstance(build_info.get("run_number"), bool)
                or not isinstance(build_info.get("run_number"), int) or build_info["run_number"] < 1
                or not re.fullmatch(r"[0-9a-f]{40,64}", str(build_info.get("commit", "")))
                or not isinstance(build_info.get("branch"), str)
                or not re.fullmatch(r"[A-Za-z0-9_./-]{1,200}", build_info["branch"])):
            raise ValueError("Arch port build-info provenance is missing or invalid")
        if expected_port_identity is not None:
            for key, expected in expected_port_identity.items():
                actual = port_version if key == "version" else build_info.get(key)
                if actual != expected:
                    raise ValueError(f"Arch port build provenance does not match expected {key}")
        extension = json.loads(captured[
            "usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json"
        ])
        if not isinstance(extension, dict) or "51" not in extension.get("shell-version", []):
            raise ValueError("dualboot extension does not declare GNOME Shell 51 support")
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"rootfs configuration validation failed: {error}") from error

    for helper in ("usr/local/libexec/x810-boot-switch-core", "usr/local/libexec/tab-companion-boot-status",
                   "usr/local/libexec/tab-companion-boot-switch"):
        if helper not in seen:
            raise ValueError(f"archive is missing required dualboot helper: {helper}")
    if b"archarm" not in captured["usr/local/libexec/x810-boot-switch-core"]:
        raise ValueError("Arch-aware dualboot backend is missing or stale")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=pathlib.Path)
    parser.add_argument("--expected-port-version")
    parser.add_argument("--expected-run-id", type=int)
    parser.add_argument("--expected-run-number", type=int)
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-branch")
    parser.add_argument("--expected-support-package-version")
    args = parser.parse_args()
    if not args.archive.is_file() or args.archive.is_symlink():
        parser.error("archive must be a regular file")
    expected_values = {
        "version": args.expected_port_version,
        "run_id": args.expected_run_id,
        "run_number": args.expected_run_number,
        "commit": args.expected_commit,
        "branch": args.expected_branch,
    }
    if any(value is not None for value in expected_values.values()) and any(
            value is None for value in expected_values.values()):
        parser.error("all expected publication identity options must be supplied together")
    try:
        verify_archive(
            args.archive,
            expected_values if args.expected_port_version is not None else None,
            args.expected_support_package_version,
        )
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
        raise SystemExit(f"rootfs archive verification failed: {error}") from error
    print("Public rootfs verified: minimal GNOME/GDM, matching X810 modules, Bluetooth, Tab Companion dualboot, locked generic seed account, and no private credentials.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
