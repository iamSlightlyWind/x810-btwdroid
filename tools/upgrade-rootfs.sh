#!/usr/bin/env bash
set -euo pipefail

# Full Arch upgrade for the local cross-architecture rootfs. The keyring
# package's post_upgrade script launches target gpg-agent, which remains traced
# by PRoot/QEMU in this environment. Update everything else first, update the
# keyring package without its package scriptlet, then perform its documented
# key-import action natively against the target GnuPG directory.
# Optional pacman package targets can be passed as arguments; they are resolved
# in that same full -Syu transaction rather than as a later partial install.

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
[[ -d "$script_dir/../work/rootfs/etc/pacman.d" ]] || {
    echo "Missing prepared rootfs; run tools/prepare-rootfs.sh first." >&2
    exit 1
}

# The bootstrap has the keyring package files but no initialized trustdb.
# Populate its trust keys before the first signature-checked transaction.
"$script_dir/init-target-keyring.sh"

"$script_dir/pacman-target.sh" --builder-mode -Syu --needed --noconfirm \
  --ignore archlinux-keyring "$@"
"$script_dir/pacman-target.sh" --builder-mode -S --needed --noconfirm --noscriptlet archlinux-keyring
"$script_dir/init-target-keyring.sh"
