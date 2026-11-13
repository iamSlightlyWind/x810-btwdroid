#!/usr/bin/env bash
set -euo pipefail

builder_mode=0
if [[ "${1:-}" == "--builder-mode" ]]; then
    builder_mode=1
    shift
fi

if (($# == 0)); then
    echo "usage: $0 <pacman arguments>" >&2
    echo "example: $0 -Syu --noconfirm networkmanager tailscale sudo zram-generator" >&2
    exit 2
fi

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
rootfs="$project_dir/work/rootfs"
external_cache="${X810_PACMAN_CACHE_DIR:-}"

[[ -d "$rootfs/etc/pacman.d" ]] || { echo "Missing prepared target rootfs: $rootfs" >&2; exit 1; }
if [[ -n "$external_cache" ]]; then
    ((builder_mode)) || { echo "X810_PACMAN_CACHE_DIR requires --builder-mode" >&2; exit 2; }
    mkdir -p "$external_cache"
    [[ -d "$external_cache" && ! -L "$external_cache" ]] \
        || { echo "Pacman cache must be a real directory: $external_cache" >&2; exit 2; }
    external_cache="$(realpath -e -- "$external_cache")"
    rootfs_real="$(realpath -e -- "$rootfs")"
    [[ "$external_cache" != "$rootfs_real" && "$external_cache" != "$rootfs_real/"* ]] \
        || { echo "Pacman cache must be outside the staged rootfs: $external_cache" >&2; exit 2; }
fi
mkdir -p "$podman_root" "$podman_runroot"
# Keep temporary builder-only pacman configuration in the ignored project tmp
# tree even when Podman storage roots are overridden outside the repository.
mkdir -p "$project_dir/tmp"
mkdir -p "$project_dir/out/packages"

builder_conf_dir=""
builder_conf_file=""
cleanup() {
    [[ -z "$builder_conf_dir" ]] || rm -rf -- "$builder_conf_dir"
}
trap cleanup EXIT
if ((builder_mode)); then
    # PRoot/QEMU cannot install pacman's seccomp filter (EINVAL). Build only
    # from a disposable config copy with the two sandbox workarounds enabled;
    # never modify the target /etc/pacman.conf. The target profile keeps
    # DisableSandboxFilesystem only, preserving syscall sandboxing on-device.
    builder_conf_dir="$(mktemp -d "$project_dir/tmp/pacman-config.XXXXXXXX")"
    chmod 0700 "$builder_conf_dir"
    builder_conf_file="$builder_conf_dir/pacman.conf"
    if [[ -n "$external_cache" ]]; then
        "$script_dir/configure-target-pacman.py" \
          --builder-config "$builder_conf_file" --cache-dir /work/pacman-cache \
          "$rootfs/etc/pacman.conf"
    else
        "$script_dir/configure-target-pacman.py" \
          --builder-config "$builder_conf_file" "$rootfs/etc/pacman.conf"
    fi
fi

printf 'Target pacman command:'
printf ' %q' "$@"
printf '\n'

volume_args=(--volume "$rootfs:/work/rootfs:rw"
  --volume "$project_dir/out/packages:/work/packages:ro")
if ((builder_mode)); then
    volume_args+=(--volume "$builder_conf_file:/work/pacman-builder.conf:ro")
fi
if [[ -n "$external_cache" ]]; then
    volume_args+=(--volume "$external_cache:/work/pacman-cache:rw")
fi
podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --interactive --rm --security-opt label=disable \
  "${volume_args[@]}" --workdir /work \
  "$image" -lc '
    set -euo pipefail
    builder_mode="$1"
    shift
    proot=(/opt/proot/src/proot -0 -q /usr/bin/qemu-aarch64-static \
      -r /work/rootfs -w / -b /dev -b /proc -b /sys -b /tmp \
      -b /work/packages:/work/packages \
      -b /etc/resolv.conf:/run/systemd/resolve/resolv.conf)
    if [[ -d /work/pacman-cache ]]; then
      proot+=(-b /work/pacman-cache:/work/pacman-cache)
    fi
    if [[ "$builder_mode" == 1 ]]; then
      proot+=(-b /work/pacman-builder.conf:/tmp/pacman-builder.conf)
      pacman=(/usr/bin/pacman --config /tmp/pacman-builder.conf "$@")
    else
      pacman=(/usr/bin/pacman "$@")
    fi
    "${proot[@]}" "${pacman[@]}"
  ' -- "$builder_mode" "$@"
