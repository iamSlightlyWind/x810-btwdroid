#!/usr/bin/env bash
# Create the public, credential-free rootfs asset for a GitHub release.
set -euo pipefail
umask 022

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
root_arg="${1:-$project_dir/work/rootfs}"
[[ $# -le 1 ]] || { echo "usage: tools/package-rootfs.sh [rootfs-dir]" >&2; exit 2; }
[[ -d "$root_arg" && ! -L "$root_arg" ]] || { echo "missing/unsafe rootfs: $root_arg" >&2; exit 1; }
rootfs="$(cd -- "$root_arg" && pwd -P)"
case "$rootfs" in
  "$project_dir/work"/*|"$project_dir/tmp"/*) ;;
  *) echo "refusing to package a tree outside disposable work/ or tmp/: $rootfs" >&2; exit 1 ;;
esac

command -v podman >/dev/null 2>&1 || { echo "podman is required" >&2; exit 1; }
command -v zstd >/dev/null 2>&1 || { echo "zstd is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }
project_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
project_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
output_dir="$project_dir/out"
archive="$output_dir/rootfs.tar.zst"
mkdir -p "$project_root" "$project_runroot" "$output_dir"
[[ ! -L "$output_dir" && ! -L "$archive" ]] || { echo "refusing symlinked public output" >&2; exit 1; }
[[ ! -e "$archive" ]] || { echo "refusing to overwrite existing public rootfs: $archive" >&2; exit 1; }
temporary="$output_dir/.rootfs.tar.zst.partial-$$"
[[ ! -e "$temporary" && ! -L "$temporary" ]] || { echo "refusing existing temporary output: $temporary" >&2; exit 1; }
umask 077
: > "$temporary"
trap 'rm -f -- "$temporary"' EXIT

podman --root "$project_root" --runroot "$project_runroot" --storage-driver=vfs \
  run --rm --pull=never --network=none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev --security-opt label=disable \
  --volume "$rootfs:/rootfs:ro" \
  --volume "$temporary:/out/rootfs.tar.zst:rw" \
  "$image" -lc '
    set -euo pipefail
    export LC_ALL=C
    tar --create --zstd --file=/out/rootfs.tar.zst \
      --directory=/rootfs --format=posix --numeric-owner --sparse --sort=name \
      --exclude="./run/*" .
    tar --list --zstd --file=/out/rootfs.tar.zst >/dev/null
  '

python3 "$script_dir/verify-rootfs-archive.py" "$temporary"
chmod 0644 "$temporary"
mv -- "$temporary" "$archive"
trap - EXIT
digest="$(sha256sum "$archive" | awk '{print $1}')"
printf '%s  %s\n' "$digest" "$(basename -- "$archive")" > "$output_dir/SHA256SUMS"
printf 'Created public rootfs asset: %s (%s bytes)\n' "$archive" "$(stat -c %s "$archive")"
printf 'SHA-256: %s\n' "$digest"
