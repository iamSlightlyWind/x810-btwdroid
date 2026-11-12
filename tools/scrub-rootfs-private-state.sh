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
    candidate_roots=(/etc /home /root /usr /var /opt /srv /boot /tmp /mnt /media /run /lib /lib64 /bin /sbin)
    scan_roots=()
    for candidate in "${candidate_roots[@]}"; do
      if target /usr/bin/test -d "$candidate"; then
        scan_roots+=("$candidate")
      fi
    done
    find_sensitive() {
      target /usr/bin/find "${scan_roots[@]}" \
        \( -iname ".ssh*" -o -iname "authorized_keys" \
          -o -iname "*ssh_host_*" -o -iname "wpa_supplicant.conf" \) "$@"
    }

    # The profile package transaction runs after SSH configuration and can
    # recreate generated host keys or bootstrap credential directories.
    sensitive_list="/tmp/windstation-private-paths-$$"
    find_sensitive -prune -print0 > "$sensitive_list"
    while IFS= read -r -d "" sensitive_path; do
      target /usr/bin/rm -rf -- "$sensitive_path"
    done < "$sensitive_list"
    rm -f -- "$sensitive_list"
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
