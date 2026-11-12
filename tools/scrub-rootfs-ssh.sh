#!/usr/bin/env bash
set -euo pipefail

# Run find/rm as PRoot fake-root inside the target tree. The rootless host
# builder cannot traverse mode-0700 homes owned by the target's alarm user.
script_dir="$(cd -- "$(dirname -- "$0")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
rootfs="$project_dir/work/rootfs"

[[ -d "$rootfs/etc" ]] || { echo "Missing target rootfs: $rootfs" >&2; exit 1; }
mkdir -p "$podman_root" "$podman_runroot"

podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --rm --security-opt label=disable \
  --volume "$rootfs:/work/rootfs:rw" --workdir /work \
  "$image" -lc '
    set -euo pipefail
    rootfs=/work/rootfs
    target() { /opt/proot/src/proot -0 -q /usr/bin/qemu-aarch64-static \
      -r "$rootfs" -w / -b /dev -b /proc -b /sys -b /tmp "$@"; }
    target /usr/bin/find /home /root -mindepth 1 -name ".ssh*" -prune \
      -exec /usr/bin/rm -rf -- {} +
    remaining="$(target /usr/bin/find /home /root -mindepth 1 -name ".ssh*" -print -quit)"
    if [[ -n "$remaining" ]]; then
      echo "Unexpected SSH material remains in target home: $remaining" >&2
      exit 1
    fi
    echo "Removed SSH material from target home trees."
  '
