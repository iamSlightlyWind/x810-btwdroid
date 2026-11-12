#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="$ROOT/docs/ALARM-ROOTFS.lock"
declare -A values=()
while IFS='=' read -r key value; do
    [[ -z "${key//[[:space:]]/}" || "$key" == \#* ]] && continue
    [[ "$key" =~ ^[a-z0-9_]+$ ]] || { echo "Invalid lock key: $key" >&2; exit 2; }
    values["$key"]="$value"
done < "$LOCK"

for key in archive_path signature_path archive_sha256 signature_sha256 signer_fingerprint keyring_member; do
    [[ -n "${values[$key]:-}" ]] || { echo "Missing $key in $LOCK" >&2; exit 2; }
done
[[ "${values[archive_path]}" == cache/* && "${values[signature_path]}" == cache/* ]] || {
    echo "Only project-local cache paths are accepted" >&2; exit 2;
}
[[ "${values[archive_sha256]}" =~ ^[[:xdigit:]]{64}$ ]] || { echo "Invalid archive SHA-256" >&2; exit 2; }
[[ "${values[signature_sha256]}" =~ ^[[:xdigit:]]{64}$ ]] || { echo "Invalid signature SHA-256" >&2; exit 2; }
[[ "${values[signer_fingerprint]}" =~ ^[[:xdigit:]]{40}$ ]] || { echo "Invalid signer fingerprint" >&2; exit 2; }

ARCHIVE="$ROOT/${values[archive_path]}"
SIGNATURE="$ROOT/${values[signature_path]}"
for input in "$ARCHIVE" "$SIGNATURE"; do
    [[ -f "$input" ]] || { echo "Missing input: $input" >&2; exit 1; }
done

actual_archive_sha="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
actual_sig_sha="$(sha256sum "$SIGNATURE" | cut -d' ' -f1)"
[[ "$actual_archive_sha" == "${values[archive_sha256]}" ]] || {
    echo "Archive digest mismatch: $actual_archive_sha" >&2; exit 1;
}
[[ "$actual_sig_sha" == "${values[signature_sha256]}" ]] || {
    echo "Signature-file digest mismatch: $actual_sig_sha" >&2; exit 1;
}

TMP_ROOT="$ROOT/tmp"
mkdir -p "$TMP_ROOT"
VERIFY_DIR="$(mktemp -d "$TMP_ROOT/alarm-verify.XXXXXX")"
KEY_FILE="$VERIFY_DIR/archlinuxarm.gpg"
GNUPGHOME="$VERIFY_DIR/gnupg"
mkdir -m 700 "$GNUPGHOME"
tar -xOf "$ARCHIVE" "${values[keyring_member]}" > "$KEY_FILE"
[[ -s "$KEY_FILE" ]] || { echo "Empty embedded Arch Linux ARM keyring" >&2; exit 1; }

gpg --homedir "$GNUPGHOME" --batch --no-auto-key-retrieve --import "$KEY_FILE" >/dev/null 2>&1
key_fingerprints="$(gpg --homedir "$GNUPGHOME" --batch --no-auto-key-retrieve \
    --with-colons --fingerprint --list-keys | awk -F: '$1 == "fpr" { print toupper($10) }')"
grep -Fxq "${values[signer_fingerprint]}" <<< "$key_fingerprints" || {
    echo "Pinned signer fingerprint is not present in the embedded keyring" >&2; exit 1;
}

if ! verify_output="$(gpg --homedir "$GNUPGHOME" --batch --no-auto-key-retrieve \
    --status-fd 1 --verify "$SIGNATURE" "$ARCHIVE" 2>&1)"; then
    printf '%s\n' "$verify_output" >&2
    echo "Detached signature verification failed" >&2
    exit 1
fi
printf '%s\n' "$verify_output"
valid_fingerprint="$(awk '$1 == "[GNUPG:]" && $2 == "VALIDSIG" { print toupper($3); exit }' <<< "$verify_output")"
[[ "$valid_fingerprint" == "${values[signer_fingerprint]}" ]] || {
    echo "Signature was not made by the pinned signer: ${valid_fingerprint:-none}" >&2; exit 1;
}

printf '\nVerified Arch Linux ARM bootstrap archive.\nSHA-256: %s\nSigner: %s\n' \
    "$actual_archive_sha" "$valid_fingerprint"
printf 'Temporary verification keyring retained under: %s\n' "$VERIFY_DIR"
