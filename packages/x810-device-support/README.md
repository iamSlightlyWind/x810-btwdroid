# x810-device-support (initial Arch package)

This first package intentionally covers only the OS-independent, low-risk
thermal limiter and zram configuration. Its helper and systemd unit are
copied from `x810-fedroid` at commit
`691763578b51f859f51568a6efa3946a7b366eb7`; exact source hashes are recorded
in `SOURCE.lock`. The MIT license is bundled.

The Arch package is `arch=('any')`: it contains Python/systemd configuration,
not kernel modules or compiled code. It does **not** install or enable boot
image mutators, panel suspend/resume recovery, firmware-mount units, Wi-Fi
PCIe re-enumeration, or the Fedora-specific TuneD integration. In particular,
`gts9wifi-bt-provision.service`, `gts9wifi-mem-reclaim.service`, and
`gts9wifi-grow-rootfs.service` are excluded from the first image. Those
services write the boot/vendor_boot partitions or resize a filesystem and
must not run during this rootfs-only experiment.

`makepkg` does not enable services. The current SSH-first rootfs installs the
unit but deliberately leaves `x810-thermal-limit.service` disabled. The exact
`7.2.0-gts9wifi` module tree has been staged, but the thermal sysfs paths and
policy still need physical validation before a later opt-in enables it.

This is an initial bring-up package, not the complete X810 support layer. The
current local rootfs stages basic NetworkManager/wpa_supplicant Wi-Fi
configuration and the exact WCN6855 firmware separately from this package;
that setup remains unverified until a real-device boot. Wi-Fi recovery,
Bluetooth, audio, sensors, display recovery, power-key handling, charging
controls and camera support remain separate follow-up work.

## GNOME/GDM boundary

GNOME package selection, `gdm.service` enablement, and `graphical.target` belong
to the Arch image profile (`../../docs/GNOME-PROFILE.md`), not this package.
The Fedora reference builder enables GDM but has no X810-specific GDM override.
Its schema override enables a Fedora-only Shell extension, while its
`power-button-action='nothing'` dconf setting is paired with Fedora's
`x810-powerkey.service`; importing either into Arch without its matching
service would be incorrect. No Fedora GDM/service preset or power-key policy
is imported here. Wayland startup, panel behavior, rotation, and touch remain
hardware validation items; no panel-specific GDM policy is justified by the
current evidence.
