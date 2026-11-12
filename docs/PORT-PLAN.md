# Windstation Arch Linux ARM port

## Scope and safety boundary

The target is the Samsung Galaxy Tab S9+ Wi-Fi (SM-X810, `gts9pwifi`). The
port builds an Arch Linux ARM AArch64 userspace for the existing X810 boot
chain and kernel. `tools/x810-install` replaces only the ext4 filesystem
identified as `PARTLABEL=linuxroot`; it does not repartition, write Android or
boot-related partitions, or reboot. The installer validates the target and
stops in TWRP.

The currently supported kernel/module pair is `7.2.0-gts9wifi`. Do not install
a generic Arch kernel or copy model-specific firmware and settings from the
X910 Tab S9 Ultra. The X810 uses WCN6855/ath11k; the X910's WCN7850/ath12k and
other board-specific settings do not apply.

## Rebuild and validation

The source and integrity pins are recorded in `ALARM-ROOTFS.lock`,
`X810-MODULES.lock`, and the package `SOURCE.lock` files. The signed generic
Arch ARM bootstrap is verified before extraction. Device modules and selected
Wi-Fi firmware are staged from local inputs with pinned hashes. Firmware and
module payloads, reference checkouts, build trees, package archives, and the
rootfs archive are deliberately excluded from Git.

A clean build needs the signed Arch ARM bootstrap and signature, the matching
module tree, an authorized SSH public key, a private connectivity snapshot,
and the sibling `x810-fedroid` checkout for its pinned BDF parser. Keep these
under ignored `cache/`; never commit credentials or device state.

Run `./x810-build` from the repository root. It builds the pinned builder,
verifies or prepares the bootstrap rootfs, installs the base networking
packages, stages modules and Wi-Fi support, imports the private connectivity
inputs, configures SSH, builds the packages, applies the GNOME profile, and
archives the audited rootfs. It reuses an existing staged rootfs and never
deletes it; move a tree aside explicitly before requesting a clean build.

The build scripts modify only `work/rootfs` on the build host. The profile
step audits and archives that tree under ignored `out/private-rootfs/`. That
archive contains credentials and device state; it is neither a public release
artifact nor safe to upload. See [ROOTFS-ARTIFACT.md](ROOTFS-ARTIFACT.md).

## Desktop and device support

The GNOME profile installs the X810 device-support package (zram defaults and
a disabled thermal limiter), GNOME Shell/session, GDM, Settings, GNOME
Terminal, Brave, BlueZ utilities, and Tab Companion. It avoids the broad
`gnome` group because some optional ARM packages have unresolved dependencies.
The image enables GDM and Bluetooth and sets BlueZ `AutoEnable=true`.

Tab Companion's Arch package overlays the browser selector and per-browser
RAM limit, retains the X810 dualboot UI/helpers and shell extension, and
reports the actual Arch Linux ARM name while preserving the shared legacy
Linux boot-set ID used by the Android selector. A boot-set image is not
included in the rootfs build: the dualboot page can report status, but a
switch requires valid Android/Linux boot sets under
`/var/lib/x810-boot-sets`. The Fedora RPM/kernel updater is not an Arch kernel
updater; Arch system updates use a complete `pacman -Syu` transaction.

Bluetooth, display, touchscreen, audio, thermal, charging, and suspend/resume
must be validated on the device before claiming full hardware support. Do not
enable deferred Fedora services wholesale; port and review each component for
Arch paths, dependencies, firmware, and partition-write behavior first.
