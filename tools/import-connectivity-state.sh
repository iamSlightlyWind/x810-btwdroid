#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
workspace_dir="$(cd -- "$project_dir/.." && pwd)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
rootfs="$project_dir/work/rootfs"
archive="$project_dir/cache/windstation-connectivity.tar.gz"

[[ -s "$archive" ]] || { echo "Missing local connectivity snapshot: $archive" >&2; exit 1; }
[[ -d "$rootfs/etc/NetworkManager" ]] || { echo "NetworkManager is not installed in the rootfs" >&2; exit 1; }

# Do not trust tar paths, links, or additional source files in this private input.
python3 - "$archive" <<'PY'
import sys, tarfile

expected = {
    "var/lib/tailscale/tailscaled.state",
}
with tarfile.open(sys.argv[1], "r:gz") as archive:
    members = archive.getmembers()
    if len(members) != 2:
        raise SystemExit(f"expected two connectivity files, found {len(members)}")
    names = set()
    for member in members:
        name = member.name
        if member.issym() or member.islnk() or not member.isfile():
            raise SystemExit(f"refusing non-regular connectivity member: {name!r}")
        if name.startswith("/") or ".." in name.split("/"):
            raise SystemExit(f"refusing unsafe connectivity path: {name!r}")
        names.add(name)
    profiles = [n for n in names if n.startswith("etc/NetworkManager/system-connections/") and n.endswith(".nmconnection")]
    if len(profiles) != 1 or not expected.issubset(names):
        raise SystemExit("archive must contain exactly one NM profile plus tailscaled.state")
    print("Validated two local-only connectivity inputs; profile name and secrets suppressed.")
PY

mkdir -p "$podman_root" "$podman_runroot"
podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --rm --security-opt label=disable \
  --volume "$workspace_dir:/workspace:rw" --workdir /workspace \
  "$image" -lc '
    set -euo pipefail
    project=/workspace/x810-btwdroid
    rootfs="$project/work/rootfs"
    tar --extract --gzip --file="$project/cache/windstation-connectivity.tar.gz" \
      --directory="$rootfs" --numeric-owner --same-owner --same-permissions
    chown root:root "$rootfs"/etc/NetworkManager/system-connections/*.nmconnection \
      "$rootfs/var/lib/tailscale/tailscaled.state"
    chmod 0600 "$rootfs"/etc/NetworkManager/system-connections/*.nmconnection \
      "$rootfs/var/lib/tailscale/tailscaled.state"
    echo "Imported one active Wi-Fi profile and the current Tailscale node state into the disposable rootfs."
    echo "Secret contents were not printed; Windstation itself was only read."
  '
