#!/usr/bin/env bash
# Fetch the public SM8550 AudioReach topology, apply the X810 MI2S SD1 route,
# and stage it under the exact firmware name requested by the X810 sound card.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
dest="$project_dir/packages/x810-device-support/files/usr/lib/firmware/qcom/sm8550/Samsung-Galaxy-Tab-S9-tplg.bin"
repo=https://gitlab.com/kernel-firmware/linux-firmware.git
commit=18cf97993f06c0a28d88cee30b7b646807642acd
upstream_sha512=d41185a9c905571f7c234ff8caf6e6d24870161a5e6ef0316bb997bfd26cee871a483287308a0af177d39a81b256def4cfa99b0f2594b364ba7ef1104dd9caca
staged_sha512=0c36213640a9c8d8ddbe76ad9b948ff2eb0b063803c6d5906cef2407628ec92e23adc279eb3fe150dc0fd75d8b01a22bca21fc16466d9b8a69775fdb31bdf410

die() { echo "ERROR: $*" >&2; exit 1; }
command -v git >/dev/null || die 'git is required to stage AudioReach topology'
command -v sha512sum >/dev/null || die 'sha512sum is required'
command -v python3 >/dev/null || die 'python3 is required'

verify_staged() {
  [[ -f "$dest" && ! -L "$dest" ]] || return 1
  [[ "$(sha512sum "$dest" | awk '{print $1}')" == "$staged_sha512" ]]
}
if verify_staged; then
  echo 'Verified cached X810 AudioReach topology.'
  exit 0
fi

mkdir -p "$project_dir/work"
tmp="$(mktemp -d "$project_dir/work/audioreach.XXXXXX")"
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM
git -C "$tmp" init -q
git -C "$tmp" remote add origin "$repo"
git -C "$tmp" -c protocol.version=2 fetch -q --depth=1 --filter=blob:none origin "$commit"
git -C "$tmp" sparse-checkout init --cone
git -C "$tmp" sparse-checkout set qcom/sm8550
git -C "$tmp" checkout -q --detach FETCH_HEAD

src="$tmp/qcom/sm8550/SM8550-HDK-tplg.bin"
[[ -s "$src" ]] || die "missing upstream topology: $src"
[[ "$(sha512sum "$src" | awk '{print $1}')" == "$upstream_sha512" ]] \
  || die 'upstream topology checksum mismatch'

python3 - "$src" "$tmp/x810-tplg.bin" <<'PY'
import struct
import sys

src, dst = sys.argv[1:]
data = bytearray(open(src, "rb").read())
module_id = struct.pack("<I", 0x0700100A)  # MODULE_ID_I2S_SINK
token_sd_line = 256                       # AR_TKN_U32_MODULE_SD_LINE_IDX
matches = [i for i in range(len(data)) if data.startswith(module_id, i)]
if len(matches) != 1:
    raise SystemExit(f"expected one I2S sink module, found {len(matches)}")
patched = 0
start = matches[0]
for offset in range(start, min(start + 200, len(data) - 8), 4):
    token, value = struct.unpack_from("<II", data, offset)
    if token == token_sd_line and value == 1:
        struct.pack_into("<I", data, offset + 4, 2)  # I2S_SD1
        patched += 1
if patched != 1:
    raise SystemExit(f"expected one SD0-to-SD1 token change, changed {patched}")
with open(dst, "wb") as stream:
    stream.write(data)
PY

[[ "$(sha512sum "$tmp/x810-tplg.bin" | awk '{print $1}')" == "$staged_sha512" ]] \
  || die 'patched topology checksum mismatch'
install -D -m 0644 "$tmp/x810-tplg.bin" "$dest"
verify_staged || die 'staged topology failed verification'
echo "Staged verified X810 AudioReach topology: $dest"
