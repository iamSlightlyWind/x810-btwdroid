# Public rootfs release

`rootfs/build-rootfs.sh` produces `out/rootfs.tar.zst`, `out/manifest.json`,
and `out/SHA256SUMS`. GitHub Actions follows Fedora's multi-job graph:
`publication_identity`, `build_port_update`, `plan`, kernel-module
preparation, `resolve_rootfs`, `build_rootfs`, `publish_full_set`, and
`prune_old_releases`. The updater job tests/builds the Arch packages and
`update.zip`; the rootfs job consumes those exact package artifacts and the
verified module receipt. The aggregate publisher validates and publishes
rootfs plus updater assets together, and pruning runs only after validation.
The manifest records the Fedora kernel release and module/RPM hashes consumed
by the Arch image. The Python installer
downloads the release manifest and rootfs, verifies GitHub metadata and the
declared SHA-256/size, then performs content validation before showing an
install plan.

The public archive is a generic installer image: its locked `alarm` seed is
replaced on every install with the account entered during that run. Build-time
account data, host SSH keys, authorized keys, saved NetworkManager profiles,
and Tailscale state are not included. Local caches and staged trees remain
ignored under `cache/`, `work/`, `tmp/`, and `out/`.
