#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
rootfs="$project_dir/work/rootfs"

[[ -d "$rootfs/usr/share/pacman/keyrings" ]] || { echo "Missing target rootfs keyrings: $rootfs" >&2; exit 1; }
mkdir -p "$podman_root" "$podman_runroot"

# pacman-key --init/populate is run natively in the isolated x86 Arch
# container, with GnuPG pointed at the target tree. Running it through QEMU +
# PRoot can leave a traced gpg-agent daemon attached and block the transaction.
podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --rm --security-opt label=disable \
  --volume "$rootfs:/work/rootfs:rw" --workdir /work \
  "$image" -lc '
    keyring=/work/rootfs/etc/pacman.d/gnupg
    rm -f "$keyring"/S.gpg-agent "$keyring"/S.gpg-agent.browser \
      "$keyring"/S.gpg-agent.extra "$keyring"/S.gpg-agent.ssh
    if [[ ! -s "$keyring/pubring.gpg" || ! -s "$keyring/trustdb.gpg" ]]; then
      pacman-key --gpgdir "$keyring" --init
    fi
    pacman-key --gpgdir "$keyring" \
      --populate-from /work/rootfs/usr/share/pacman/keyrings \
      --populate archlinux archlinuxarm
    gpgconf --homedir "$keyring" --kill gpg-agent || true
    rm -f "$keyring"/S.gpg-agent "$keyring"/S.gpg-agent.browser \
      "$keyring"/S.gpg-agent.extra "$keyring"/S.gpg-agent.ssh
  '
