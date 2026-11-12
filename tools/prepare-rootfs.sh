#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
archive="$project_dir/cache/ArchLinuxARM-aarch64-latest.tar.gz"
rootfs="$project_dir/work/rootfs"

[[ -f "$archive" ]] || { echo "Missing verified rootfs archive: $archive" >&2; exit 1; }
if [[ -e "$rootfs" ]] && find "$rootfs" -mindepth 1 -print -quit | grep -q .; then
    echo "Refusing to overwrite non-empty rootfs: $rootfs" >&2
    echo "Move or remove it explicitly before preparing a fresh extraction." >&2
    exit 1
fi

"$script_dir/verify-alarm-rootfs.sh"
mkdir -p "$rootfs" "$podman_root" "$podman_runroot"

podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --rm --security-opt label=disable \
  --volume "$rootfs:/target:rw" \
  --volume "$archive:/input/ArchLinuxARM-aarch64-latest.tar.gz:ro" \
  "$image" -lc 'tar --extract --gzip --file=/input/ArchLinuxARM-aarch64-latest.tar.gz \
      --directory=/target --numeric-owner --same-owner --same-permissions \
      --xattrs --xattrs-include="*" --acls'

mirrorlist="$rootfs/etc/pacman.d/mirrorlist"
[[ -f "$mirrorlist" && ! -L "$mirrorlist" ]] \
    || { echo "Missing or unsafe target ALARM mirrorlist: $mirrorlist" >&2; exit 1; }
python3 "$script_dir/configure-alarm-mirrors.py" "$mirrorlist"

echo "Extracted signed generic AArch64 bootstrap into: $rootfs"
echo "This is a disposable staging tree; Windstation was not accessed or modified."
