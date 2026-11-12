# Windstation Arch Linux ARM port

Target: Samsung Galaxy Tab S9+ Wi-Fi (SM-X810, `gts9pwifi`). The port uses
the existing X810 boot chain and kernel/module release `7.2.0-gts9wifi`; it
does not install a generic kernel. The installer formats only the existing
`PARTLABEL=linuxroot` partition and stops in TWRP.

## Build

`rootfs/build-rootfs.sh` is the local Fedora-style entry point. The GitHub
workflow uses Fedora's job graph: `publication_identity`,
`build_port_update`, `plan`, kernel component preparation, `resolve_rootfs`,
`build_rootfs`, `publish_full_set`, then `prune_old_releases`. The updater job
runs the contract tests, builds all Arch packages, and hands off `update.zip`
and the exact package archives. The rootfs job consumes those package
archives and the separately verified X810 kernel-module artifact. Arch uses
the existing Fedora kernel release rather than building a kernel. Its rolling
repositories mean every rootfs is freshly built, not reused from a source-only
fingerprint.

The internal script downloads the pinned Arch ARM bootstrap, stages the
matching module tree, builds the GNOME profile, audits it, and creates the
rootfs set under `out/`. It refuses a non-empty `work/rootfs`; move a staged
tree aside explicitly before a clean build. The aggregate GitHub release
contains `rootfs.tar.zst`, `manifest.json`, `SHA256SUMS`, and the Tab Companion
`update.zip`.

The ignored `cache/`, `work/`, `tmp/`, and `out/` paths are local build state.
No device account, SSH key, saved Wi-Fi profile, or Tailscale state is imported
into the public image.

## Device support

The profile contains a minimal GNOME Shell/session, GDM, Settings, GNOME
Terminal, Brave, Bluetooth, and Tab Companion. It avoids the full `gnome`
package group because of unresolved optional ARM dependencies. Tab Companion
uses a shared distro backend for package operations; its Arch package provides
the X810 dualboot UI/helpers. No kernel updater is advertised for Arch.

The dualboot interface needs valid Android and Linux boot sets under
`/var/lib/x810-boot-sets`. Tab Companion's Arch port-update feed uses the
published `x810-device-support` pacman package; kernel updates remain disabled.
Display, touch, audio, Bluetooth, charging, thermal, and suspend/resume still
require device validation.
