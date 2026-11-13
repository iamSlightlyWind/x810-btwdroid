# x810-device-support

Arch support package for Samsung Galaxy Tab S9+ Wi-Fi (SM-X810). It supplies
the tablet-specific Tab Companion controls, GNOME device-settings extension,
thermal limiter, zram defaults, Bluetooth address provisioning, charge-limit
restore, udev permissions, boot log and GTK rendering settings, and the
`wpa_supplicant` D-Bus policy.

The clean GNOME image profile enables the validated thermal limiter,
`gts9wifi-device-control`, Bluetooth address provisioner, charge-limit restore,
BlueZ, and `tuned-ppd` (the standard PowerProfiles D-Bus API backed by TuneD). The BT provisioner reads the native address
from EFS read-only and patches only the Linux boot and vendor_boot DTBs when
needed; Android system/userdata partitions are not touched. It is a oneshot
unit so a later kernel-image update is repaired on the next boot. The BT
revive helper is manual-only and does not auto-run.

The charge-limit helper stores only an explicitly selected cap in
`/var/lib/x810-arch/charge-limit.conf`; the oneshot restore unit is enabled but
has no effect unless that file exists. Fast charge starts off. Thermal policy
is defined in `/etc/x810-thermal-limit.json` and its runtime health report is
available to Tab Companion.

The package itself does not enable units; image profile policy owns enablement.
The Arch profile is kept separate from Fedora-specific TuneD, power-key, and
package-manager integrations.
