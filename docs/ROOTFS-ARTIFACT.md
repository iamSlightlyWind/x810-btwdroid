# Public rootfs release

`rootfs/build-rootfs.sh` produces `out/rootfs.tar.zst`, `out/manifest.json`,
and `out/SHA256SUMS`. The archive verifier checks the complete rootfs before
GitHub Actions publishes those files as one release. The Python installer
downloads the release manifest and rootfs, verifies GitHub metadata and the
declared SHA-256/size, then performs content validation before showing an
install plan.

The public archive is a generic installer image: its locked `alarm` seed is
replaced on every install with the account entered during that run. Build-time
account data, host SSH keys, authorized keys, saved NetworkManager profiles,
and Tailscale state are not included. Local caches and staged trees remain
ignored under `cache/`, `work/`, `tmp/`, and `out/`.
