#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
workspace_dir="$(cd -- "$project_dir/.." && pwd)"
project_name="$(basename -- "$project_dir")"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
build_user="$(id -u):$(id -g)"

mkdir -p "$project_dir/out/packages" "$project_dir/work/makepkg/build" \
  "$project_dir/work/makepkg/sources" \
  "$podman_root" "$podman_runroot"

# CI stages the successful-push identity before packaging. For local builds,
# create useful provenance too, without claiming that the image is publishable.
port_build_info="$project_dir/packages/x810-device-support/files/usr/share/tab-companion/port-build.json"
if [[ ! -s "$port_build_info" ]]; then
    port_version="$(tr -d '\r\n ' < "$project_dir/PORT_VERSION")"
    build_run_id="${GITHUB_RUN_ID:-1}"
    build_run_number="${GITHUB_RUN_NUMBER:-1}"
    build_commit="${GITHUB_SHA:-$(git -C "$project_dir" rev-parse HEAD)}"
    build_branch="${GITHUB_REF_NAME:-local}"
    python3 "$script_dir/write-arch-port-build-info.py" "$port_build_info" \
      "$port_version" "$build_run_id" "$build_run_number" "$build_commit" "$build_branch"
fi

# Keep one unambiguous current archive for each locally built package.
shopt -s nullglob
for name in x810-device-support tab-companion brave-bin; do
    stale=("$project_dir/out/packages/$name"-*.pkg.tar.zst)
    ((${#stale[@]} == 0)) || rm -f -- "${stale[@]}"
done
shopt -u nullglob
cat > "$project_dir/work/makepkg/makepkg.conf" <<EOF
source /etc/makepkg.conf
CARCH=aarch64
BUILDDIR=/workspace/$project_name/work/makepkg/build
SRCDEST=/workspace/$project_name/work/makepkg/sources
PKGDEST=/workspace/$project_name/out/packages
EOF

for name in x810-device-support tab-companion brave-bin; do
    package_dir="$project_dir/packages/$name"
    [[ -f "$package_dir/PKGBUILD" ]] || { echo "Missing PKGBUILD: $package_dir" >&2; exit 1; }
    printf '\n=== Building %s as an unprivileged user ===\n' "$name"
    podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
      run --rm --security-opt label=disable --userns=keep-id --user "$build_user" \
      --volume "$workspace_dir:/workspace:rw" --workdir "/workspace/$project_name/packages/$name" \
      "$image" -lc \
      "makepkg --cleanbuild --noconfirm --nodeps --force --config=/workspace/$project_name/work/makepkg/makepkg.conf"
done

echo "Packages built under: $project_dir/out/packages"
