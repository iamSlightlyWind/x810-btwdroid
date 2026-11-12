# GNOME rootfs profile

`./x810-build` is the single repository-root entry point. It orchestrates the
builder, rootfs preparation, baseline and desktop package transactions, local
device support/Tab Companion/Brave packages, audit, and private archive. All
rootfs changes are confined to `work/rootfs`; it does not access, install to,
or reboot Windstation.

The profile includes the X810 device-support package (zram defaults and a disabled thermal limiter), GNOME Shell/session, GDM, Settings, GNOME Terminal, Brave (`brave-bin`), BlueZ/BlueZ utilities, required audio/fonts and Tab Companion. GDM is enabled and the default target is graphical; the build does not start GDM. `bluetooth.service` is enabled and BlueZ `AutoEnable=true` is explicit. The GNOME group is avoided to exclude optional apps with unsatisfied ARM dependencies; `gnome-console`, `gnome-boxes` and `gnome-books` are omitted.

Build the complete local profile with one repository-root command:

```sh
./x810-build
```

Brave is built as a pinned AArch64 package from Brave's Linux ARM64 release. Tab Companion's local Arch package overlays the Firefox/Brave browser selector, per-browser RAM limiter, Arch-aware X810 dualboot backend, and GNOME Shell 51 extension metadata into its pinned bundle. The Performance control limits native browser cgroups; Flatpak scopes are excluded. The dualboot page remains visible, but switching requires valid Android and Linux boot-set images under `/var/lib/x810-boot-sets`; none are currently staged in the local image.

The archive verifier requires the package database records, enabled GDM/Bluetooth units, graphical default, `AutoEnable=true`, and the existing filesystem, account, SSH, module and firmware invariants. The private rootfs/archive contains credentials and must remain ignored and local.
