#!/usr/bin/env bash
# Internal release builder, analogous to x810-fedroid/rootfs/build-rootfs.sh.
# The public user-facing entry point is the Python tools/x810-install script.
set -euo pipefail
umask 022

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
tools="$project_dir/tools"
rootfs="$project_dir/work/rootfs"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for program in podman python3 gpg zstd tar sha256sum cpio rpm2cpio; do
  command -v "$program" >/dev/null 2>&1 || die "required host tool is missing: $program"
done
[[ ! -L "$project_dir/work" ]] || die "refusing symlinked work directory"
[[ ! -e "$rootfs" || -d "$rootfs" ]] || die "work/rootfs is not a directory"
[[ ! -L "$rootfs" ]] || die "refusing symlinked work/rootfs"
if [[ -d "$rootfs" ]] && find "$rootfs" -mindepth 1 -print -quit | grep -q .; then
  die "work/rootfs already contains a staged tree; move it aside explicitly before a clean build"
fi

# Podman rejects overlong rootless runroot paths on some versions. These
# project-local short paths remain ignored under tmp/ and keep all state here.
export PODMAN_ROOT_OVERRIDE="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/p}"
export PODMAN_RUNROOT_OVERRIDE="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/r}"

echo "Building a clean Arch Linux ARM GNOME rootfs; no tablet access is performed."
python3 "$tools/fetch-alarm-rootfs.py"
"$tools/build-builder-image.sh"
"$tools/verify-alarm-rootfs.sh"
"$tools/prepare-rootfs.sh"
if [[ "${X810_PREBUILT_KERNEL_MODULES:-0}" == 1 ]]; then
  python3 "$tools/fetch-x810-kernel.py" --verify-prepared
else
  python3 "$tools/fetch-x810-kernel.py"
fi
"$tools/upgrade-rootfs.sh" networkmanager wpa_supplicant openssh sudo zram-generator
"$tools/stage-x810-modules.sh"
"$tools/stage-x810-wifi.sh"
"$tools/configure-ssh-rootfs.sh"
if [[ "${X810_PREBUILT_PACKAGES:-0}" == 1 ]]; then
  [[ -f "$project_dir/out/packages/SHA256SUMS" && ! -L "$project_dir/out/packages/SHA256SUMS" ]] \
    || die "prebuilt package checksum manifest is missing"
  (cd "$project_dir/out/packages" && sha256sum --check SHA256SUMS)
  shopt -s nullglob
  package_archives=("$project_dir"/out/packages/*.pkg.tar.zst)
  shopt -u nullglob
  [[ ${#package_archives[@]} -eq 3 ]] || die "expected exactly three prebuilt Arch package archives"
  for package in x810-device-support tab-companion brave-bin; do
    compgen -G "$project_dir/out/packages/$package-*.pkg.tar.zst" >/dev/null \
      || die "prebuilt package artifact is missing $package"
  done
  echo "Using three prebuilt Arch package artifacts from the package build stage."
else
  "$tools/build-packages.sh"
fi
"$tools/install-gnome-profile.sh"
"$tools/package-rootfs.sh" "$rootfs"
python3 "$tools/make-rootfs-release.py"

echo "Release-ready Arch rootfs and manifest are under out/."
echo "No build-time user, SSH key, Wi-Fi credential, or Tailscale state is included."
echo "Windstation was not contacted, written, or rebooted."
