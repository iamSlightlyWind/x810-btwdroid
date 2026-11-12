#!/usr/bin/env python3
"""Configure/check the Windstation pacman Landlock workaround.

The target kernel does not enable CONFIG_SECURITY_LANDLOCK, so pacman's
filesystem sandbox must be disabled.  Keep its syscall sandbox enabled.
This helper only edits the target rootfs's [options] section; it never runs
pacman and is safe to use while assembling a local rootfs.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import tempfile
from pathlib import Path


FILESYSTEM_DIRECTIVE = "DisableSandboxFilesystem"
SYSCALL_DIRECTIVE = "DisableSandboxSyscalls"


def sandbox_state(text: str) -> tuple[bool, bool]:
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
        if not in_options:
            continue
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        key = stripped.split("=", 1)[0].strip().split()[0]
        if key == FILESYSTEM_DIRECTIVE:
            filesystem += 1
        elif key == SYSCALL_DIRECTIVE:
            syscalls += 1
    if not options_found:
        raise ValueError("pacman.conf has no [options] section")
    if filesystem > 1:
        raise ValueError("pacman.conf has duplicate DisableSandboxFilesystem directives")
    if syscalls > 1:
        raise ValueError("pacman.conf has duplicate DisableSandboxSyscalls directives")
    return filesystem == 1, syscalls == 1


def ensure_target_policy(text: str) -> str:
    """Enable only the filesystem workaround; fail if syscall sandbox is off."""
    filesystem_disabled, syscalls_disabled = sandbox_state(text)
    if syscalls_disabled:
        raise ValueError(
            "pacman.conf disables the syscall sandbox; remove that directive before continuing"
        )
    if filesystem_disabled:
        return text

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if re.fullmatch(r"\s*\[options\]\s*(?:#.*)?\s*", line.rstrip("\r\n"), re.IGNORECASE):
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            lines.insert(index + 1, FILESYSTEM_DIRECTIVE + newline)
            return "".join(lines)
    raise ValueError("pacman.conf has no [options] section")


def make_builder_only_config(text: str) -> str:
    """Return an isolated PRoot config; its relaxed sandboxes never enter image."""
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    in_options = False
    options_found = False
    inserted = False
    for line in lines:
        section = re.fullmatch(r"\s*\[([^]]+)\]\s*(?:#.*)?", line.rstrip("\r\n"))
        if section:
            in_options = section.group(1).strip().lower() == "options"
            options_found |= in_options
            result.append(line)
            if in_options:
                newline = "\r\n" if line.endswith("\r\n") else "\n"
                result.extend(
                    (
                        "DownloadUser = root" + newline,
                        FILESYSTEM_DIRECTIVE + newline,
                        SYSCALL_DIRECTIVE + newline,
                    )
                )
                inserted = True
            continue
        if in_options:
            stripped = line.lstrip()
            candidate = stripped.removeprefix("#").strip()
            key = candidate.split("=", 1)[0].strip().split()[0] if candidate else ""
            if key in {"DownloadUser", FILESYSTEM_DIRECTIVE, SYSCALL_DIRECTIVE}:
                continue
        result.append(line)
    if not options_found or not inserted:
        raise ValueError("pacman.conf has no [options] section")
    return "".join(result)


def check_target_policy(text: str) -> None:
    filesystem_disabled, syscalls_disabled = sandbox_state(text)
    if not filesystem_disabled:
        raise ValueError("pacman filesystem sandbox workaround is not enabled")
    if syscalls_disabled:
        raise ValueError("pacman syscall sandbox must remain enabled")


def configure_file(path: Path, *, check_only: bool = False) -> bool:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular, non-symlink pacman.conf: {path}")
    original = path.read_text(encoding="utf-8")
    if check_only:
        check_target_policy(original)
        return False

    updated = ensure_target_policy(original)
    check_target_policy(updated)
    if updated == original:
        return False

    mode = stat.S_IMODE(path.stat().st_mode)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return True


def write_builder_config(source: Path, output: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"expected a regular, non-symlink pacman.conf: {source}")
    if output.exists() or output.is_symlink():
        raise ValueError(f"builder config output already exists: {output}")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    rendered = make_builder_only_config(source.read_text(encoding="utf-8"))
    try:
        with output.open("x", encoding="utf-8", newline="") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(output, 0o600)
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pacman_conf", type=Path)
    parser.add_argument("--check", action="store_true", help="verify without editing")
    parser.add_argument(
        "--builder-config",
        type=Path,
        help="write an isolated PRoot-only config with both sandbox workarounds enabled",
    )
    args = parser.parse_args()
    try:
        if args.builder_config is not None:
            if args.check:
                parser.error("--builder-config and --check are mutually exclusive")
            write_builder_config(args.pacman_conf, args.builder_config)
            print("Created isolated builder-only pacman config; target pacman.conf was not edited.")
            return 0
        changed = configure_file(args.pacman_conf, check_only=args.check)
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(1, f"pacman sandbox policy: ERROR: {error}\n")
    if args.check:
        print("Pacman sandbox policy OK: filesystem sandbox disabled; syscall sandbox enabled.")
    elif changed:
        print("Pacman policy set: filesystem sandbox disabled; syscall sandbox remains enabled.")
    else:
        print("Pacman policy already correct: filesystem sandbox disabled; syscall sandbox enabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
