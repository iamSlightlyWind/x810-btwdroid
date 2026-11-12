# X810 BTWDroid

Arch Linux ARM GNOME rootfs and guarded installer for the Samsung Galaxy Tab
S9+ Wi-Fi (SM-X810, `gts9pwifi`). The installer replaces only the existing
`linuxroot` filesystem; Android, boot partitions, GPT, and recovery are not
written, and it does not reboot.

## Install

With the tablet already in TWRP and attached to a Linux host:

```sh
python3 tools/x810-install doctor
python3 tools/x810-install install --plan-only
python3 tools/x810-install install
```

The Python installer fetches the latest GitHub release, verifies its manifest,
checksum, and rootfs contents, then prompts for a new account and explicit
format confirmation. `--no-update` selects an already cached release.

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
tests/builds the Arch packages and `update.zip` independently; the rootfs job
uses those exact packages. Arch has no kernel build stage because it uses the
matching X810 modules from the Fedora kernel release. The final release
contains both rootfs and Tab Companion update assets, and older Arch releases
are pruned only after the aggregate is verified. The build does not access
Windstation. See [docs/INSTALL.md](docs/INSTALL.md) for local tests.

The image includes GNOME Settings, GNOME Terminal, Brave, Bluetooth, and Tab
Companion. No build-time user, SSH key, Wi-Fi credentials, or Tailscale state
is part of the public rootfs.
