# Windstation Arch Linux ARM port

Target: Samsung Galaxy Tab S9+ Wi-Fi (SM-X810, `gts9pwifi`). The port uses
the existing X810 boot chain and kernel/module release `7.2.0-gts9wifi`; it
does not install a generic kernel. The installer formats only the existing
`PARTLABEL=linuxroot` partition and stops in TWRP.

## Build

`rootfs/build-rootfs.sh` is the internal builder, following the Fedora port's
`rootfs/build-rootfs.sh` layout. It downloads the pinned Arch ARM bootstrap,
fetches the matching public X810 kernel package, builds the GNOME profile,
audits it, and creates a public release set in `out/`. It refuses a non-empty
`work/rootfs`; move a staged tree aside explicitly before a clean build.
GitHub Actions runs this full build and publishes `rootfs.tar.zst`,
`manifest.json`, and `SHA256SUMS`.

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
`/var/lib/x810-boot-sets`. Display, touch, audio, Bluetooth, charging,
thermal, and suspend/resume still require device validation.
