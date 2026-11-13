# X810 BTWDroid

Arch Linux ARM GNOME rootfs and guarded installer for the Samsung Galaxy Tab
S9+ Wi-Fi (SM-X810, `gts9pwifi`). The installer replaces only the existing
`linuxroot` filesystem. It saves the four Android boot images to the host and
seeds verified copies into the new rootfs, but never writes the Android, boot,
GPT, or recovery partitions, and does not reboot.

## Install

With the tablet already in TWRP and attached to a Linux host:

```sh
python3 tools/x810-install doctor
python3 tools/x810-install install --plan-only
python3 tools/x810-install install
```

The Python installer fetches the latest GitHub release, verifies its manifest,
checksum, and rootfs contents, then prompts for a new account and explicit
format confirmation. If no staged Android set exists in the old rootfs, it
requires an additional explicit confirmation before treating the current boot
partitions as Android. `--no-update` selects an already cached release.

## Build and test

The Fedora-style layout keeps the public installer in `tools/` and the
internal build orchestration in `rootfs/`:

```sh
rootfs/build-rootfs.sh
```

It stages a fresh tree in `work/rootfs`, builds and audits the minimal GNOME /
GDM profile, then prepares `out/rootfs.tar.zst` and its release manifest.
GitHub Actions mirrors Fedora's job graph: `publication_identity`,
`build_port_update`, `plan`, kernel-module preparation, `resolve_rootfs`,
`build_rootfs`, `publish_full_set`, and `prune_old_releases`. The updater job
builds the Arch packages and `update.zip`; independently, the rootfs job builds
its own package copies while constructing the image. Only the final publisher
waits for both outputs. Arch has no kernel build stage because it uses the
matching X810 modules from the Fedora kernel release. The final release
contains both rootfs and Tab Companion update assets, and older Arch releases
are pruned only after the aggregate is verified. The build does not access
Windstation. See [docs/INSTALL.md](docs/INSTALL.md) for local tests.

GitHub Actions restores/saves the signed bootstrap, Arch builder package
archives, makepkg source downloads, and rolling target-rootfs package archives.
The target pacman cache is mounted outside `work/rootfs`; each build still runs
a full `-Syu` against current signed repositories, and only cached packages
matching installed versions are retained for reuse. Rootfs and sync-database
caches are removed before release, so no cache is shipped in the image.

The image includes GNOME Settings, GNOME Terminal, Brave, Bluetooth, and Tab
Companion. No build-time user, SSH key, Wi-Fi credentials, or Tailscale state
is part of the public rootfs.
