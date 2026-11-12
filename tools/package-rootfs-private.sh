#!/usr/bin/env bash
# Create a checksummed, metadata-preserving private archive of the local rootfs.
# The archive contains credentials and private state; it is never a release artifact.
#
# Usage: tools/package-rootfs-private.sh [rootfs-dir] [artifact-label]
# Default rootfs: work/rootfs
# Output: ignored out/private-rootfs/, mode 0600

set -euo pipefail
umask 077

(( EUID != 0 )) || {
    echo "ERROR: run this script as an unprivileged user; it is designed for rootless Podman." >&2
    exit 1
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
root_arg="${1:-$project_dir/work/rootfs}"
label="${2:-windstation-arch-rootfs}"
[[ $# -le 2 ]] || die "usage: $(basename -- "$0") [rootfs-dir] [artifact-label]"
[[ "$label" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] \
    || die "artifact label must use only letters, digits, dot, underscore, or hyphen"
[[ -d "$root_arg" && ! -L "$root_arg" ]] || die "rootfs must be a real directory: $root_arg"
rootfs="$(cd -- "$root_arg" && pwd -P)"
case "$rootfs" in
    "$project_dir/work"/*|"$project_dir/tmp"/*) ;;
    *) die "refusing to archive outside disposable $project_dir/work or $project_dir/tmp trees" ;;
esac
[[ -n "$(find "$rootfs" -mindepth 1 -print -quit)" ]] || die "refusing to package an empty rootfs"

command -v podman >/dev/null 2>&1 || die "podman is required"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
command -v awk >/dev/null 2>&1 || die "awk is required"
command -v date >/dev/null 2>&1 || die "date is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"

tmp_dir="$project_dir/tmp"
podman_root="${PODMAN_ROOT_OVERRIDE:-$tmp_dir/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$tmp_dir/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
output_root="$project_dir/out"
out_dir="$output_root/private-rootfs"
for path in "$tmp_dir" "$podman_root" "$podman_runroot" "$output_root" "$project_dir/docs"; do
    if [[ -L "$path" || ( -e "$path" && ! -d "$path" ) ]]; then
        die "project-local storage/output path must be a normal directory, not a symlink: $path"
    fi
done
if [[ -L "$out_dir" || ( -e "$out_dir" && ! -d "$out_dir" ) ]]; then
    die "private output path must be a normal directory, not a symlink: $out_dir"
fi
mkdir -p -- "$podman_root" "$podman_runroot" "$out_dir"
chmod 0700 -- "$out_dir"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive_name="$label-$stamp.tar.zst"
archive="$out_dir/$archive_name"
hash_file="$archive.sha256"
[[ ! -e "$archive" && ! -L "$archive" && ! -e "$hash_file" && ! -L "$hash_file" ]] \
    || die "refusing to overwrite an existing artifact: $archive"

tmp_archive="$(mktemp "$out_dir/.$label.tar.zst.XXXXXXXX")"
tmp_hash="$(mktemp "$out_dir/.$label.sha256.XXXXXXXX")"
chmod 0600 -- "$tmp_archive" "$tmp_hash"
archive_linked=0
hash_linked=0
committed=0
tmp_lock=""
cleanup() {
    rm -f -- "$tmp_archive" "$tmp_hash"
    [[ -z "$tmp_lock" ]] || rm -f -- "$tmp_lock"
    if (( archive_linked && !committed )); then rm -f -- "$archive"; fi
    if (( hash_linked && !committed )); then rm -f -- "$hash_file"; fi
}
trap cleanup EXIT

mkdir -p -- "$podman_root" "$podman_runroot"
podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --rm --pull=never --network=none --read-only --tmpfs /tmp:rw,nosuid,nodev \
  --security-opt label=disable \
  --volume "$rootfs:/rootfs:ro" \
  --volume "$tmp_archive:/out/rootfs.tar.zst:rw" \
  "$image" -lc '
    set -euo pipefail
    export LC_ALL=C
    command -v tar >/dev/null
    command -v zstd >/dev/null
    # This rootless container user namespace sees the rootfs numeric IDs as
    # target IDs. Do not apply --owner/--group or normalize modes/mtimes. The
    # TWRP Toybox tar cannot restore xattrs or ACLs. In particular,
    # the staged tree may inherit host SELinux labels from devnode; carrying
    # those labels into a tablet filesystem would be incorrect. Numeric IDs,
    # modes, timestamps and sparse extents remain in the archive. The source
    # is read-only; no workspace-wide mount or network is available.
    tar --create --zstd --file=/out/rootfs.tar.zst \
      --directory=/rootfs --format=posix --numeric-owner \
      --sparse --sort=name \
      --exclude="./run/*" .
    # Check the compressed archive without listing its (potentially sensitive) paths.
    tar --list --zstd --file=/out/rootfs.tar.zst >/dev/null
  '

chmod 0600 -- "$tmp_archive"
python3 "$script_dir/verify-rootfs-archive.py" "$tmp_archive" \
    || die "archive metadata validation failed"
digest="$(sha256sum -- "$tmp_archive" | awk '{print $1}')"
[[ "$digest" =~ ^[[:xdigit:]]{64}$ ]] || die "could not compute archive SHA-256"
printf '%s  %s\n' "$digest" "$archive_name" > "$tmp_hash"
chmod 0600 -- "$tmp_hash"

# Hard-link within the same private output directory so a concurrent run cannot
# overwrite an existing artifact. Keep both files private and ignored by Git.
ln -- "$tmp_archive" "$archive" || die "artifact appeared concurrently: $archive"
archive_linked=1
ln -- "$tmp_hash" "$hash_file" || die "hash sidecar appeared concurrently: $hash_file"
hash_linked=1
rm -f -- "$tmp_archive" "$tmp_hash"
[[ "$(stat -c %a -- "$archive")" == 600 ]] || die "archive permissions are not 0600"
[[ "$(stat -c %a -- "$hash_file")" == 600 ]] || die "hash sidecar permissions are not 0600"
lock_path="$project_dir/docs/ARCH-ROOTFS-ARTIFACT.lock"
[[ ! -L "$lock_path" ]] || die "artifact lock must not be a symlink: $lock_path"
[[ ! -e "$lock_path" || -f "$lock_path" ]] \
    || die "artifact lock must be a regular file or absent: $lock_path"
tmp_lock="$(mktemp "$project_dir/docs/.ARCH-ROOTFS-ARTIFACT.lock.XXXXXXXX")"
cat > "$tmp_lock" <<EOF
artifact=out/private-rootfs/$archive_name
format=tar.zst
sha256=$digest
size_bytes=$(stat -c %s -- "$archive")
created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sensitivity=PRIVATE: contains a salted /etc/shadow password hash, active Wi-Fi credentials, Tailscale node state, and SSH host private keys
contents=/run payload excluded; numeric uid/gid, modes, timestamps and sparse extents preserved; ACLs/xattrs omitted for TWRP compatibility
verification=tools/verify-rootfs-archive.py
EOF
chmod 0600 -- "$tmp_lock"
mv -- "$tmp_lock" "$lock_path"
tmp_lock=""
committed=1
echo "Created private rootfs archive: $archive"
echo "SHA-256: $digest"
echo "The archive contains private SSH/Wi-Fi/Tailscale state; do not publish or commit it."
