#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"

mkdir -p "$podman_root" "$podman_runroot"
podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --rm --security-opt label=disable \
  --volume "$project_dir:/project:rw" --workdir /project \
  "$image" -lc '
    set -euo pipefail
    python3 - <<"PY"
from pathlib import Path

rootfs = Path("/project/work/rootfs")
targets = [rootfs / "var/cache/pacman/pkg", rootfs / "var/lib/pacman/sync"]
for target in targets:
    if not target.is_dir() or target.is_symlink():
        raise SystemExit(f"refusing unexpected cache path: {target}")
    removed = 0
    for child in target.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
            removed += 1
        elif child.is_dir():
            import shutil
            shutil.rmtree(child)
            removed += 1
        else:
            raise SystemExit(f"refusing special cache entry: {child}")
    print(f"Cleared {removed} entries from {target.relative_to(rootfs)}")

if not (rootfs / "var/lib/pacman/local/ALPM_DB_VERSION").is_file():
    raise SystemExit("pacman local package database was not preserved")
PY
  '
