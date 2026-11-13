#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rootfs="${X810_ROOTFS_DIR:-$project_dir/work/rootfs}"
source_dir="$project_dir/cache/public-kernel/boot"
destination="$rootfs/var/lib/x810-boot-sets/fedora"

python3 "$project_dir/tools/fetch-x810-kernel.py" --verify-prepared
mkdir -p "$destination"
for part in boot init_boot vendor_boot dtbo; do
  source="$source_dir/$part.img"
  [[ -f "$source" && ! -L "$source" ]] || {
    echo "Missing verified X810 Linux boot image: $source" >&2
    exit 1
  }
  install -m 0644 -- "$source" "$destination/$part.img"
done
printf 'Arch Linux ARM\n' > "$destination/name.txt"
chmod 0644 "$destination/name.txt"
echo "Verified X810 Linux boot set staged at $destination."
