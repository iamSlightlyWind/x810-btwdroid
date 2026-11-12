#!/usr/bin/env bash
set -euo pipefail

# Final release scrub for the staged target rootfs only. Run under PRoot fake
# root so mode-0700 bootstrap homes are traversable; never operates on device.
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
      -r "$rootfs" -w / -b /dev -b /proc -b /sys "$@"; }
    find_sensitive() {
      target /usr/bin/find / \
        \( -path /dev -o -path /proc -o -path /sys \) -prune -o \
        \( -iname ".ssh*" -o -iname "authorized_keys" \
          -o -iname "*ssh_host_*" -o -iname "wpa_supplicant.conf" \) "$@"
    }

    # The profile package transaction runs after SSH configuration and can
    # recreate generated host keys or bootstrap credential directories.
    find_sensitive -prune -exec /usr/bin/rm -rf -- {} +
    target /usr/bin/rm -rf -- /var/lib/tailscale
    if target /usr/bin/test -d /etc/NetworkManager/system-connections; then
      target /usr/bin/find /etc/NetworkManager/system-connections \
        -mindepth 1 -exec /usr/bin/rm -rf -- {} +
    fi

    remaining="$(find_sensitive -print -quit)"
    if [[ -n "$remaining" ]] || target /usr/bin/test -e /var/lib/tailscale; then
      echo "Private SSH, Wi-Fi, or Tailscale state remains in target rootfs." >&2
      exit 1
    fi
    if target /usr/bin/test -d /etc/NetworkManager/system-connections \
      && target /usr/bin/find /etc/NetworkManager/system-connections \
        -type f -print -quit | grep -q .; then
      echo "Saved NetworkManager profiles remain in target rootfs." >&2
      exit 1
    fi
    echo "Scrubbed private SSH, Wi-Fi, NetworkManager, and Tailscale state from target rootfs."
  '
