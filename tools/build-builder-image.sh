#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
external_cache="${X810_BUILDER_PACMAN_CACHE_DIR:-}"

mkdir -p "$podman_root" "$podman_runroot"
cache_args=()
if [[ -n "$external_cache" ]]; then
  mkdir -p "$external_cache"
  [[ -d "$external_cache" && ! -L "$external_cache" ]] \
    || { echo "Builder pacman cache must be a real directory: $external_cache" >&2; exit 2; }
  external_cache="$(realpath -e -- "$external_cache")"
  cache_args+=(--volume "$external_cache:/var/cache/pacman/pkg:rw,z"
    --build-arg X810_EXTERNAL_PACMAN_CACHE=1)
fi
podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  build --pull=always "${cache_args[@]}" --tag localhost/windstation-arch-builder:2026-11-11 \
  --file "$script_dir/builder/Containerfile" "$script_dir/builder"

echo "Builder image ready: localhost/windstation-arch-builder:2026-11-11"
