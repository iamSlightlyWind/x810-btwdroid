#!/usr/bin/env bash
# Stage only the validated public X810 WCN6855 IOE firmware and its one
# exact-ABI board-data payload into a disposable local rootfs tree.
#
#   tools/stage-x810-wifi-firmware.sh <rootfs-dir-under-the-repository>
#
# This is deliberately separate from x810-fedroid/rootfs/stage-public-firmware.sh:
# the latter also stages proprietary VPU/Cirrus content and its broad `bdftool
# swap` mode replaces all variants sharing a base name. This script does neither.

set -euo pipefail

die() {
    echo "ERROR: $*" >&2
    exit 1
}

root_arg="${1:-}"
[[ -n "$root_arg" ]] || die "usage: $(basename -- "$0") <rootfs-dir-under-the-repository>"
[[ -d "$root_arg" ]] || die "rootfs directory does not exist: $root_arg"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
workspace_dir="$(cd -- "$project_dir/.." && pwd -P)"
rootfs="$(cd -- "$root_arg" && pwd -P)"
case "$rootfs" in
    "$project_dir/work"/*|"$project_dir/tmp"/*) ;;
    *) die "rootfs must be a disposable tree below $project_dir/work or $project_dir/tmp (got $rootfs)" ;;
esac

x810_repo="$workspace_dir/x810-fedroid"
bdftool="$x810_repo/tools/bdftool.py"
bdftool_sha256="c2f851d7d9700fca7df41df19d291122877c6008e22722250f68fddbe72e4cc7"
[[ -f "$bdftool" ]] || die "missing pinned x810-fedroid tool: $bdftool"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v awk >/dev/null 2>&1 || die "awk is required"
[[ "$(sha256sum -- "$bdftool" | awk '{print $1}')" == "$bdftool_sha256" ]] \
    || die "x810-fedroid bdftool.py differs from the pinned version; review and update this script's pin"

fw_rel="usr/lib/firmware/ath11k/WCN6855/hw2.1"
fw_dir="$rootfs/$fw_rel"
board="$fw_dir/board-2.bin"
board_xz="$board.xz"
amss="$fw_dir/amss.bin"
m3="$fw_dir/m3.bin"
slot="bus=pci,vendor=17cb,device=1103,subsystem-vendor=17cb,subsystem-device=0108,qmi-chip-id=18,qmi-board-id=255"
variant="$slot,variant=NTM_TW220"

# Do not follow a rootfs symlink into a host path. Missing directories are
# permitted, but are created only after every source and output validates.
walk="$rootfs"
for part in usr lib firmware ath11k WCN6855 hw2.1; do
    walk="$walk/$part"
    if [[ -L "$walk" ]]; then
        die "refusing symlink in firmware destination path: $walk"
    fi
    if [[ -e "$walk" && ! -d "$walk" ]]; then
        die "firmware destination path component is not a directory: $walk"
    fi
done
for dest in "$board" "$board_xz" "$amss" "$m3"; do
    if [[ -L "$dest" ]]; then
        link="$(readlink -- "$dest")"
        case "$dest:$link" in
            "$board:../hw2.0/board-2.bin"|"$board_xz:../hw2.0/board-2.bin.xz"|\
            "$amss:../hw2.0/amss.bin"|"$m3:../hw2.0/m3.bin") ;;
            *) die "refusing unexpected firmware symlink: $dest -> $link" ;;
        esac
        resolved="$(realpath -e -- "$dest")" || die "broken firmware symlink: $dest"
        case "$resolved" in
            "$rootfs"/*) ;;
            *) die "firmware symlink escapes the rootfs: $dest -> $resolved" ;;
        esac
    fi
    if [[ -e "$dest" && ! -f "$dest" ]]; then
        die "firmware destination/source is not a regular file: $dest"
    fi
done

if [[ -L "$project_dir/tmp" || ( -e "$project_dir/tmp" && ! -d "$project_dir/tmp" ) ]]; then
    die "project temporary directory must be a normal directory, not a symlink: $project_dir/tmp"
fi
mkdir -p -- "$project_dir/tmp"
work="$(mktemp -d "$project_dir/tmp/stage-x810-wifi.XXXXXXXX")" \
    || die "could not create temporary work directory"
stage_temps=()
cleanup() {
    local p
    for p in "${stage_temps[@]}"; do
        [[ -n "$p" ]] && rm -f -- "$p"
    done
    find "$work" -mindepth 1 -maxdepth 1 -type f -delete 2>/dev/null || true
    rmdir "$work" 2>/dev/null || true
}
trap cleanup EXIT

sha256() {
    sha256sum -- "$1" | awk '{print $1}'
}

fetch_pinned() {
    local url="$1" out="$2" want="$3" label="$4" got
    echo "Fetching $label"
    if ! curl -fsSL --retry 3 --connect-timeout 20 --max-time 300 -o "$out" "$url"; then
        die "download failed for $label ($url)"
    fi
    got="$(sha256 "$out")"
    [[ "$got" == "$want" ]] || die "SHA-256 mismatch for $label: got $got, expected $want"
}

# These public source URLs and hashes are copied from the checked-in
# x810-fedroid/rootfs/stage-public-firmware.sh at the pinned revision documented
# in docs/X810-WIFI-FIRMWARE.md. Hashes, not a mutable Git branch name, decide
# whether any downloaded bytes are accepted.
ioe_base='https://raw.githubusercontent.com/CodeLinaro-mirror/ath-firmware_ath11k-firmware/main/WCN6855/hw2.0@nfa765/1.1/WLAN.HSP.1.1-04866.5-QCAHSPSWPL_V1_V2_SILICONZ_IOE-1'
amss_sha256='8cb5e63877c7cfdc5002a7d28bc5d7f7d20368183e6f93b12c977bfd0351c7b7'
m3_sha256='d20460e104b85a7be9cdb5199c4d8b94a9787912e3f920acd845694d4d71f730'
bdf_ref_url='https://raw.githubusercontent.com/CodeLinaro-mirror/ath-firmware_ath11k-firmware/main/WCN6855/hw2.0/board-2.bin'
bdf_ref_sha256='9287fa8d14d915892666b03e9403135875d08371fd1438d2c6d9fe96ae71cf68'
tuned_sha256='77b1b9ef636ce8492723aa7c2ff2c42c2e5e81a43967d7f32bfdef93a31bf8c4'
tuned_md5='6d42746b861fc52380a19dfdfaa702f1'
generic_md5='0e92fa42e6b9895e4afd7a281bbed079'
# Additional SHA pin for the generic exact-ABI payload in the currently locked
# Arch ARM bootstrap archive; see docs/X810-WIFI-FIRMWARE.md.
generic_sha256='9c5266d14cbe3eb40a4137e2fbe6199e10f14b1b8100a401b6de153326124a5e'

# Prepare IOE blobs in private temp storage. Existing correct outputs remain
# untouched; wrong/unrelated files are replaced only after all preflight passes.
amss_src=''
m3_src=''
if [[ -f "$amss" ]] && [[ "$(sha256 "$amss")" == "$amss_sha256" ]]; then
    echo "Existing WCN6855 IOE amss.bin is correct"
else
    amss_src="$work/amss.bin"
    fetch_pinned "$ioe_base/amss.bin" "$amss_src" "$amss_sha256" "WCN6855 IOE 04866.5 amss.bin"
fi
if [[ -f "$m3" ]] && [[ "$(sha256 "$m3")" == "$m3_sha256" ]]; then
    echo "Existing WCN6855 IOE m3.bin is correct"
else
    m3_src="$work/m3.bin"
    fetch_pinned "$ioe_base/m3.bin" "$m3_src" "$m3_sha256" "WCN6855 IOE 04866.5 m3.bin"
fi

# The locked bootstrap supplies an uncompressed board-2.bin. Accept a
# compressed package payload only as a read-only input, then create the plain
# override that ath11k checks first; never alter/remove the .xz source.
board_input="$work/input-board-2.bin"
if [[ -f "$board" ]]; then
    cp -- "$board" "$board_input"
elif [[ -f "$board_xz" ]]; then
    command -v xz >/dev/null 2>&1 || die "xz is required to read $board_xz"
    xz -dc -- "$board_xz" > "$board_input" || die "could not decompress $board_xz"
else
    die "no WCN6855 board-2.bin or board-2.bin.xz in the target rootfs"
fi

python3 "$bdftool" md5s "$board_input" > "$work/before.md5s" \
    || die "x810-fedroid bdftool.py could not parse the target board-2.bin"
slot_count="$(awk -v n="$slot" '$3 == n {c++} END {print c+0}' "$work/before.md5s")"
[[ "$slot_count" == 1 ]] \
    || die "expected exactly one X810 board slot in board-2.bin; found $slot_count"
slot_md5="$(awk -v n="$slot" '$3 == n {print $2}' "$work/before.md5s")"
python3 "$bdftool" dump "$board_input" "$slot" "$work/exact-before.bin" >/dev/null \
    || die "could not extract the exact-ABI board slot"
slot_sha256="$(sha256 "$work/exact-before.bin")"

board_src="$work/fixed-board-2.bin"
board_changed=0
case "$slot_md5:$slot_sha256" in
    "$tuned_md5:$tuned_sha256")
        echo "Exact X810 board slot already has the pinned tuned payload"
        cp -- "$board_input" "$board_src"
        ;;
    "$generic_md5:$generic_sha256")
        echo "Exact X810 board slot is the pinned generic payload; preparing the tuned replacement"
        variant_count="$(awk -v n="$variant" '$3 == n {c++} END {print c+0}' "$work/before.md5s")"
        if [[ "$variant_count" -gt 1 ]]; then
            die "duplicate NTM_TW220 variant entry; refusing ambiguous source"
        fi
        variant_ok=0
        if [[ "$variant_count" == 1 ]]; then
            python3 "$bdftool" dump "$board_input" "$variant" "$work/tuned.bin" >/dev/null \
                || die "could not extract the NTM_TW220 variant"
            [[ "$(sha256 "$work/tuned.bin")" == "$tuned_sha256" ]] && variant_ok=1
        fi
        if [[ "$variant_ok" != 1 ]]; then
            fetch_pinned "$bdf_ref_url" "$work/reference-board-2.bin" "$bdf_ref_sha256" \
                "pinned public WCN6855 reference board-2.bin"
            python3 "$bdftool" md5s "$work/reference-board-2.bin" > "$work/reference.md5s" \
                || die "x810-fedroid bdftool.py could not parse the pinned reference board-2.bin"
            ref_variant_count="$(awk -v n="$variant" '$3 == n {c++} END {print c+0}' "$work/reference.md5s")"
            [[ "$ref_variant_count" == 1 ]] \
                || die "pinned BDF source must contain exactly one NTM_TW220 variant; found $ref_variant_count"
            python3 "$bdftool" dump "$work/reference-board-2.bin" "$variant" "$work/tuned.bin" >/dev/null \
                || die "could not extract tuned NTM_TW220 payload from pinned reference BDF"
            [[ "$(sha256 "$work/tuned.bin")" == "$tuned_sha256" ]] \
                || die "tuned NTM_TW220 payload SHA-256 does not match the X810 source pin"
        fi

        # bdftool.py's CLI `swap` intentionally matches both a base name and
        # every `,variant=` entry with that base. Use its pinned BDF format
        # implementation/CLI for discovery and verification, but patch the raw
        # TLV bytes here so only the one exact ABI slot changes. This also keeps
        # unrelated entries and their original padding byte-for-byte intact.
        python3 - "$board_input" "$board_src" "$slot" "$work/tuned.bin" <<'PY'
import struct
import sys

source, output, wanted, payload_path = sys.argv[1:]
data = open(source, "rb").read()
payload = open(payload_path, "rb").read()
magic = b"QCA-ATH11K-BOARD\x00"

def align4(n):
    return (n + 3) & ~3

if not data.startswith(magic):
    raise SystemExit("bad QCA-ATH11K-BOARD magic")
header_len = align4(len(magic))
if header_len > len(data):
    raise SystemExit("truncated board-2.bin header")

offset = header_len
chunks = []
target_indices = []
while len(data) - offset > 8:
    start = offset
    ie_id, ie_len = struct.unpack_from("<II", data, offset)
    body_start = offset + 8
    body_end = body_start + ie_len
    top_end = body_start + align4(ie_len)
    if body_end > len(data) or top_end > len(data):
        raise SystemExit("truncated board-2.bin top-level entry")

    sub_offset = body_start
    name = None
    name_fields = 0
    data_subs = []
    subchunks = []
    while body_end - sub_offset > 8:
        sub_start = sub_offset
        sid, sub_len = struct.unpack_from("<II", data, sub_offset)
        value_start = sub_offset + 8
        value_end = value_start + sub_len
        sub_end = value_start + align4(sub_len)
        if value_end > body_end or sub_end > body_end:
            raise SystemExit("truncated board-2.bin sub-entry")
        value = data[value_start:value_end]
        raw_sub = data[sub_start:sub_end]
        if sid == 0:
            name_fields += 1
            try:
                if name_fields == 1:
                    name = value.decode("ascii")
            except UnicodeDecodeError:
                if name_fields == 1:
                    name = None
        elif sid == 1:
            data_subs.append((sub_start, value_start, value_end, sub_end, value))
        subchunks.append((sid, raw_sub, (sub_start, value_start, value_end, sub_end)))
        sub_offset = sub_end

    if name == wanted:
        target_indices.append(len(chunks))
        if name_fields != 1:
            raise SystemExit(f"exact target has {name_fields} name fields, expected one")
        if len(data_subs) != 1:
            raise SystemExit(f"exact target has {len(data_subs)} data fields, expected one")
        old_start, old_value_start, old_value_end, old_end, old_value = data_subs[0]
        rebuilt_subs = []
        for sid, raw_sub, spans in subchunks:
            if sid != 1:
                rebuilt_subs.append(raw_sub)
                continue
            _, value_start, value_end, sub_end = spans
            old_pad = data[value_end:sub_end]
            new_pad_len = align4(len(payload)) - len(payload)
            new_pad = old_pad if len(old_pad) == new_pad_len else b"\x00" * new_pad_len
            rebuilt_subs.append(struct.pack("<II", sid, len(payload)) + payload + new_pad)
        body_tail = data[sub_offset:body_end]
        new_body = b"".join(rebuilt_subs) + body_tail
        old_top_pad = data[body_end:top_end]
        new_top_pad_len = align4(len(new_body)) - len(new_body)
        new_top_pad = old_top_pad if len(old_top_pad) == new_top_pad_len else b"\x00" * new_top_pad_len
        chunks.append(struct.pack("<II", ie_id, len(new_body)) + new_body + new_top_pad)
    else:
        chunks.append(data[start:top_end])
    offset = top_end

if len(target_indices) != 1:
    raise SystemExit(f"expected one exact target entry, found {len(target_indices)}")
patched = data[:header_len] + b"".join(chunks) + data[offset:]
open(output, "wb").write(patched)
PY
        python3 "$bdftool" md5s "$board_src" > "$work/after.md5s" \
            || die "x810-fedroid bdftool.py could not parse generated board-2.bin"
        python3 - "$work/before.md5s" "$work/after.md5s" "$slot" "$generic_md5" "$tuned_md5" <<'PY'
import sys

before_path, after_path, slot, generic_md5, tuned_md5 = sys.argv[1:]

def rows(path):
    result = []
    for line in open(path, encoding="utf-8"):
        fields = line.split(maxsplit=2)
        if len(fields) != 3:
            raise SystemExit(f"malformed bdftool output: {line!r}")
        result.append((fields[0], fields[1], fields[2].rstrip("\n")))
    return result

old, new = rows(before_path), rows(after_path)
if len(old) != len(new):
    raise SystemExit("entry count changed while patching board-2.bin")
changed = 0
for a, b in zip(old, new):
    if a[2] != b[2]:
        raise SystemExit("board-2.bin entry order/name changed")
    if a[2] == slot:
        if a[1] != generic_md5 or b[1] != tuned_md5:
            raise SystemExit("exact target did not transition from expected generic to tuned payload")
        changed += 1
    elif a != b:
        raise SystemExit(f"unrelated board entry changed: {a[2]}")
if changed != 1:
    raise SystemExit(f"expected one changed exact target entry, found {changed}")
PY
        python3 "$bdftool" dump "$board_src" "$slot" "$work/exact-after.bin" >/dev/null \
            || die "could not verify generated exact-ABI slot"
        [[ "$(sha256 "$work/exact-after.bin")" == "$tuned_sha256" ]] \
            || die "generated exact-ABI payload does not match the pinned tuned SHA-256"
        board_changed=1
        ;;
    *)
        die "unrecognised exact-ABI board slot (md5=$slot_md5 sha256=$slot_sha256); refusing to guess"
        ;;
esac

if [[ -f "$board" ]] && [[ "$board_changed" == 0 ]]; then
    board_src=''
fi

# Stage files atomically within the target directory. All network, hash, BDF
# structure, and exact-slot checks above complete before the first rootfs write.
mkdir -p -- "$fw_dir"
stage_one() {
    local src dest tmp
    src="$1"
    dest="$2"
    tmp="$fw_dir/.stage-x810-wifi.$$.${dest##*/}"
    [[ ! -e "$tmp" && ! -L "$tmp" ]] || die "temporary destination already exists: $tmp"
    stage_temps+=("$tmp")
    stage_dests+=("$dest")
    install -m 0644 -- "$src" "$tmp"
}

stage_dests=()

if [[ -n "$amss_src" ]]; then
    stage_one "$amss_src" "$amss"
    echo "Staged public IOE amss.bin"
fi
if [[ -n "$m3_src" ]]; then
    stage_one "$m3_src" "$m3"
    echo "Staged public IOE m3.bin"
fi
if [[ -n "$board_src" ]]; then
    stage_one "$board_src" "$board"
fi
for i in "${!stage_temps[@]}"; do
    # -T replaces the expected hw2.1 -> hw2.0 symlink itself; do not follow it
    # and mutate the generic hw2.0 source in place.
    mv -fT -- "${stage_temps[$i]}" "${stage_dests[$i]}"
done
stage_temps=()
stage_dests=()

[[ "$(sha256 "$amss")" == "$amss_sha256" ]] || die "final amss.bin validation failed"
[[ "$(sha256 "$m3")" == "$m3_sha256" ]] || die "final m3.bin validation failed"
python3 "$bdftool" md5s "$board" > "$work/final.md5s" \
    || die "final board-2.bin validation failed"
slot_count="$(awk -v n="$slot" '$3 == n {c++} END {print c+0}' "$work/final.md5s")"
slot_md5="$(awk -v n="$slot" '$3 == n {print $2}' "$work/final.md5s")"
[[ "$slot_count" == 1 && "$slot_md5" == "$tuned_md5" ]] \
    || die "final board-2.bin exact slot is not the single pinned tuned payload"
python3 "$bdftool" dump "$board" "$slot" "$work/final-exact.bin" >/dev/null \
    || die "final board-2.bin exact slot could not be extracted"
[[ "$(sha256 "$work/final-exact.bin")" == "$tuned_sha256" ]] \
    || die "final board-2.bin exact slot SHA-256 validation failed"

if [[ -n "$board_src" ]]; then
    echo "Staged board-2.bin with only the exact X810 ABI slot tuned"
fi

echo "Wi-Fi firmware staging complete under $fw_dir"
echo "  amss.bin:     $amss_sha256"
echo "  m3.bin:       $m3_sha256"
echo "  exact BDF:    $tuned_sha256 ($slot)"
echo "  no VPU, Cirrus, or other firmware was staged"
