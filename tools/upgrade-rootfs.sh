#!/usr/bin/env bash
set -euo pipefail

# Full Arch upgrade for the local cross-architecture rootfs. The keyring
# package's post_upgrade script launches target gpg-agent, which remains traced
# by PRoot/QEMU in this environment. Update everything else first, update the
# keyring package without its package scriptlet, then perform its documented
# key-import action natively against the target GnuPG directory.
# Optional pacman package targets can be passed as arguments; they are resolved
# in that same full -Syu transaction rather than as a later partial install.

pacman_with_retries() {
    local attempt delay
    for attempt in 1 2 3; do
        if "$script_dir/pacman-target.sh" --builder-mode "$@"; then
            return 0
        fi
        if ((attempt < 3)); then
            delay=$((attempt * 15))
            echo "Pacman network/transaction attempt $attempt failed; retrying in ${delay}s." >&2
            sleep "$delay"
        fi
    done
    echo "Pacman transaction failed after three attempts." >&2
    return 1
}

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
[[ -d "$script_dir/../work/rootfs/etc/pacman.d" ]] || {
    echo "Missing prepared rootfs; run tools/prepare-rootfs.sh first." >&2
    exit 1
}

# The bootstrap has the keyring package files but no initialized trustdb.
# Populate its trust keys before the first signature-checked transaction.
"$script_dir/init-target-keyring.sh"

pacman_with_retries -Syu --needed --noconfirm \
  --ignore archlinux-keyring "$@"
pacman_with_retries -S --needed --noconfirm --noscriptlet archlinux-keyring
"$script_dir/init-target-keyring.sh"
