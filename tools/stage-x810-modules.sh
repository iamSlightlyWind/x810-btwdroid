#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
workspace_dir="$(cd -- "$project_dir/.." && pwd)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"

mkdir -p "$podman_root" "$podman_runroot"
podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --rm --security-opt label=disable \
  --volume "$workspace_dir:/workspace:rw" --workdir /workspace \
  "$image" -lc '
    set -euo pipefail
    project=/workspace/x810-btwdroid
    rootfs="$project/work/rootfs"
    source="$project/cache/public-kernel/usr/lib/modules/7.2.0-gts9wifi"
    release=7.2.0-gts9wifi
    [[ -d "$rootfs/etc" && -d "$source" ]]

    module_hash() {
      ( cd "$1" && find . -type f -name "*.ko*" -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64 )
    }
    [[ -s "$source/modules.dep" ]] || {
      echo "public X810 kernel RPM has no modules.dep for $release" >&2
      exit 1
    }

    destination="$rootfs/usr/lib/modules/$release"
    mkdir -p "$rootfs/usr/lib/modules"
    if [[ -e "$destination" ]]; then
      current="$(module_hash "$destination")"
      original="$(module_hash "$source")"
      [[ "$current" == "$original" ]] || {
        echo "existing module tree differs; refusing overwrite: $destination" >&2
        exit 1
      }
      echo "Matching module files already staged; refreshing depmod indexes"
    else
      cp -a -- "$source" "$destination"
      echo "Copied the pinned X810 release module tree to $destination"
    fi

    depmod -b "$rootfs" "$release"
    current="$(module_hash "$destination")"
    original="$(module_hash "$source")"
    [[ "$current" == "$original" ]] || {
      echo "depmod changed a module payload; refusing to continue" >&2
      exit 1
    }
    printf "Staged %s module objects; payload SHA256 list digest: %s\n" \
      "$(find "$destination" -type f -name "*.ko*" | wc -l)" "$current"
  '
