# Public rootfs release

`rootfs/build-rootfs.sh` produces `out/rootfs.tar.zst`, `out/manifest.json`,
and `out/SHA256SUMS`. GitHub Actions follows the shared multi-job graph:
`publication_identity`, `build_port_update`, `plan`, kernel-module
preparation, `resolve_rootfs`, `build_rootfs`, `publish_full_set`, and
`prune_old_releases`. The updater job independently builds Arch packages and
`update.zip`. The rootfs job separately builds its own package copies as part
of image construction and consumes only the verified module receipt; it has no
dependency on the updater job. The aggregate publisher validates and publishes
rootfs plus updater assets together, and pruning runs only after validation.
The manifest records the X810 kernel release and module/RPM hashes consumed
by the Arch image. The Python installer
downloads the release manifest and rootfs, verifies GitHub metadata and the
declared SHA-256/size, then performs content validation before showing an
install plan.

Before starting the expensive jobs, `plan` validates the latest complete
release's source commit, GitHub asset digests/sizes, rootfs manifest,
boot-image records, and checksum file. It downloads only the small manifest and
checksum file—not the multi-gigabyte rootfs—to make this decision. When it is
the already-published release for the same successful push, it reuses that
release and skips all build/publish jobs. A manual `rebuild` dispatch bypasses
reuse for refreshing the rolling Arch package set.

Actions caches reusable source and package downloads; the published rootfs is
reused only as part of an unchanged complete release, not as a cross-commit
build cache. Arch's rolling repository cache is external to the staged
image, is used with full signed `pacman -Syu` transactions, and is pruned to
the installed package versions before the next run saves it. The release
archive separately clears any bootstrap-local package archives and sync DBs.

The public archive is a generic installer image: its locked `alarm` seed is
replaced on every install with the account entered during that run. Build-time
account data, host SSH keys, authorized keys, saved NetworkManager profiles,
and Tailscale state are not included. Local caches and staged trees remain
ignored under `cache/`, `work/`, `tmp/`, and `out/`.
