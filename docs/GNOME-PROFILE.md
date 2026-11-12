# GNOME rootfs profile

Build with `rootfs/build-rootfs.sh`. It creates a clean staged image, upgrades
the Arch ARM base, installs the X810 device package and minimal GNOME Shell,
session, GDM, Settings, GNOME Terminal, Brave, Bluetooth, and Tab Companion.
GDM and Bluetooth are enabled; GDM is not started during the build. The full
`gnome` group is avoided to exclude optional applications with unresolved ARM
dependencies; `gnome-console`, `gnome-boxes`, and `gnome-books` are omitted.

Tab Companion is built from the shared app source and uses distro adapters for
native package operations. Its Arch package supplies the Arch-aware dualboot
backend and GNOME Shell extension metadata. Browser memory limits are exposed
through the shared Performance page. The dualboot UI requires boot-set images
under `/var/lib/x810-boot-sets`; this build does not create those images.

Before release, the archive verifier checks package records, systemd links,
Bluetooth policy, the X810 module release, account seed, and absence of private
SSH/network/Tailscale state.
