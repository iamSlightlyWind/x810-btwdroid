# X810 BTWDroid

Arch Linux ARM rootfs preparation and rootfs-only installer for the Samsung
Galaxy Tab S9+ Wi-Fi (SM-X810 / `gts9pwifi`). It reuses the device's existing
kernel and boot chain; the installer targets only the existing
`PARTLABEL=linuxroot` filesystem and stops in recovery without rebooting.

## Build the GNOME profile

From the repository root, restore the local-only inputs described in
[`docs/PORT-PLAN.md`](docs/PORT-PLAN.md), then run the single entry point:

```sh
./x810-build
```

It prepares the staged rootfs if needed, builds the local packages, applies
the GNOME profile, audits it, and creates a private archive. Existing
`work/rootfs` is reused but never deleted. The script does not install
packages on the build host or access Windstation.

The profile provides the X810 zram/thermal defaults, GNOME Shell, GDM,
Settings, GNOME Terminal, Brave, Bluetooth utilities, and Tab Companion.
Tab Companion includes browser RAM limits and the Arch-aware dualboot page.
Boot-image sets are not part of the
rootfs build, so switching is unavailable until valid Android and Linux sets
are staged under `/var/lib/x810-boot-sets`.

## Validate and install

Run the contract tests with the commands in [`docs/INSTALL.md`](docs/INSTALL.md).
For a connected tablet in TWRP, `tools/x810-install doctor` and
`tools/x810-install install --plan-only` perform read-only checks. A normal
`install` erases and replaces only `linuxroot`, provisions a fresh account,
verifies the result, and stops in TWRP. Review the target, checksum, and typed
confirmation prompts before proceeding.

GitHub Actions runs source, installer, profile, and archive-verifier tests.
A manual workflow can build the AArch64 packages; it does not build or publish
the private rootfs or access the tablet.

## Local-only build state

`cache/`, `work/`, `out/`, `tmp/`, `gnupg/`, and `references/` are ignored.
The staged rootfs and private archive contain SSH keys, network credentials,
Tailscale state, and account data. Keep them local; do not commit or upload
them.
