#!/usr/bin/env bash
# Validate and publish the matched Arch rootfs + Tab Companion update release.
set -euo pipefail

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"
: "${REL:?REL is required}"
: "${EXPECTED_INPUT_KEY:?EXPECTED_INPUT_KEY is required}"
: "${SOURCE_COMMIT:?SOURCE_COMMIT is required}"
: "${SOURCE_BRANCH:?SOURCE_BRANCH is required}"
: "${PORT_VERSION:?PORT_VERSION is required}"
: "${PUBLICATION_RUN_ID:?PUBLICATION_RUN_ID is required}"
: "${PUBLICATION_RUN_NUMBER:?PUBLICATION_RUN_NUMBER is required}"
: "${PORT_UPDATE_ZIP:?PORT_UPDATE_ZIP is required}"

[[ "$REL" == "x810-arch-build-$PUBLICATION_RUN_ID" ]]
[[ "$SOURCE_BRANCH" == main ]]
[[ "$PORT_VERSION" =~ ^(0|[1-9][0-9]{0,19})\.(0|[1-9][0-9]{0,19})\.(0|[1-9][0-9]{0,19})$ ]]

release_dir=_ci/release
[[ -f "$release_dir/rootfs.tar.zst" && -f "$release_dir/manifest.json" && -f "$release_dir/SHA256SUMS" ]] || {
  echo "REFUSING: verified rootfs release artifact is incomplete." >&2
  exit 1
}
[[ -f "$PORT_UPDATE_ZIP" ]] || {
  echo "REFUSING: updater ZIP artifact is missing: $PORT_UPDATE_ZIP" >&2
  exit 1
}

(cd "$release_dir" && sha256sum --check SHA256SUMS)
support_package_version="$(python3 - "$PORT_UPDATE_ZIP" "$PORT_VERSION" <<'PY'
import json
import sys
import zipfile

path, version = sys.argv[1:]
with zipfile.ZipFile(path) as archive:
    metadata = json.loads(archive.read("tab-companion-update.json"))
    assets = metadata.get("assets")
    if not isinstance(assets, list) or len(assets) != 1 or not isinstance(assets[0], dict):
        raise SystemExit("REFUSING: update.zip must describe exactly one support package")
    asset = assets[0]
    package_version = asset.get("package_version")
    if (asset.get("package_name") != "x810-device-support"
            or not isinstance(package_version, str)
            or not package_version.startswith(version + "-")):
        raise SystemExit("REFUSING: update.zip package version does not match PORT_VERSION")
    print(package_version)
PY
)"
[[ "$support_package_version" == "$PORT_VERSION"-* ]]
python3 tools/verify-rootfs-archive.py "$release_dir/rootfs.tar.zst" \
  --expected-port-version "$PORT_VERSION" --expected-run-id "$PUBLICATION_RUN_ID" \
  --expected-run-number "$PUBLICATION_RUN_NUMBER" --expected-commit "$SOURCE_COMMIT" \
  --expected-branch "$SOURCE_BRANCH" \
  --expected-support-package-version "$support_package_version"
[[ "$REL" == "x810-arch-build-$PUBLICATION_RUN_ID" ]]
python3 tools/assemble-arch-release.py \
  --release-dir "$release_dir" --update-zip "$PORT_UPDATE_ZIP" \
  --tag "$REL" --run-id "$PUBLICATION_RUN_ID" \
  --run-number "$PUBLICATION_RUN_NUMBER" --commit "$SOURCE_COMMIT" \
  --branch "$SOURCE_BRANCH" --input-key "$EXPECTED_INPUT_KEY" --port-version "$PORT_VERSION"
(cd "$release_dir" && sha256sum --check SHA256SUMS)

if gh release view "$REL" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  echo "Refreshing existing aggregate release $REL."
else
  gh release create "$REL" --repo "$GITHUB_REPOSITORY" --title "$REL" --latest=false \
    --notes "Verified Arch Linux ARM GNOME/GDM rootfs and Tab Companion update package for SM-X810. Built by $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID. The installer formats only linuxroot; Android, boot partitions, GPT, and recovery are not written."
fi

release_flags="$(gh release view "$REL" --repo "$GITHUB_REPOSITORY" --json isDraft,isPrerelease)"
python3 - "$release_flags" <<'PY'
import json
import sys

release = json.loads(sys.argv[1])
if release.get("isDraft") is not False or release.get("isPrerelease") is not False:
    raise SystemExit("REFUSING: aggregate release must be published and non-prerelease")
PY

gh release edit "$REL" --repo "$GITHUB_REPOSITORY" --latest=false
gh release upload "$REL" --repo "$GITHUB_REPOSITORY" --clobber \
  "$release_dir/rootfs.tar.zst" "$release_dir/manifest.json" \
  "$release_dir/SHA256SUMS" "$release_dir/update.zip"

expected_names=$'rootfs.tar.zst\nmanifest.json\nSHA256SUMS\nupdate.zip'
while IFS= read -r old_name; do
  [[ -n "$old_name" ]] || continue
  if ! grep -Fxq -- "$old_name" <<< "$expected_names"; then
    gh release delete-asset "$REL" "$old_name" --repo "$GITHUB_REPOSITORY" --yes
  fi
done < <(gh release view "$REL" --repo "$GITHUB_REPOSITORY" --json assets --jq '.assets[].name')

gh release edit "$REL" --repo "$GITHUB_REPOSITORY" --latest
latest_tag="$(gh api "repos/$GITHUB_REPOSITORY/releases/latest" --jq .tag_name)"
[[ "$latest_tag" == "$REL" ]] || {
  echo "REFUSING: GitHub latest release is $latest_tag, not complete release $REL." >&2
  exit 1
}
echo "Published complete Arch release $REL with rootfs and updater assets."
