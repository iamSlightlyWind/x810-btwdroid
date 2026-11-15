#!/usr/bin/env bash
# Stage the same checksum-pinned CS35L45 protection pair as x810-fedroid.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
dest_dir="$project_dir/packages/x810-device-support/files/usr/lib/firmware/cirrus"
base=https://raw.githubusercontent.com/Azkali/gts9wifi-firmware/main/cirrus

die() { echo "ERROR: $*" >&2; exit 1; }
command -v curl >/dev/null || die 'curl is required to stage CS35L45 firmware'
command -v sha256sum >/dev/null || die 'sha256sum is required'
mkdir -p "$project_dir/work" "$dest_dir"
tmp="$(mktemp -d "$project_dir/work/cs35l45.XXXXXX")"
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

for spec in \
  'cs35l45-dsp1-spk-prot.wmfw:214ae6e1de113fde4f2568cdcd08bd0bf171d5b732a9eb44cfb4a8f6d9a67043' \
  'cs35l45-dsp1-spk-prot.bin:5fd06ccbd3c8a071121609f642956f16754851814aa2fb4133e4becc2799e79f'; do
  name="${spec%%:*}"
  expected="${spec##*:}"
  curl -fsSL --max-time 60 -o "$tmp/$name" "$base/$name" \
    || die "failed to fetch $name from the Fedora-validated firmware source"
  actual="$(sha256sum "$tmp/$name" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] \
    || die "CS35L45 firmware checksum mismatch for $name: got $actual"
  install -m 0644 "$tmp/$name" "$dest_dir/$name"
done
echo 'Staged checksum-verified CS35L45 speaker-protection firmware.'
