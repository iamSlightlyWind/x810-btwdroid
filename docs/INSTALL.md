# Installer and build checks

`tools/x810-install` is the Python host installer. It fetches the latest
verified GitHub rootfs release (or uses the local cache with `--no-update`),
validates the device in TWRP, saves the Android `boot`, `init_boot`,
`vendor_boot`, and `dtbo` images to a private host-side backup, formats only
`linuxroot`, stages and read-back-verifies those images in the new rootfs,
provisions a fresh account, verifies the extracted tree, and stops without
rebooting. It prefers a complete Android set already staged in the old
`linuxroot`. If none exists, it asks for a separate exact confirmation before
copying the current boot partitions as Android; partial or invalid staged sets
stop the install before formatting.

## Tests

Run from the repository root:

```sh
bash -n tools/*.sh rootfs/*.sh
python3 -m compileall -q tools
python3 tools/test-x810-install.py
python3 tools/test-target-pacman-policy.py
python3 tools/test-rootfs-image-profile.py
python3 tools/test-verify-rootfs-archive.py
python3 tools/test-tab-companion-overlay.py
```

## Recovery

With the tablet already in TWRP:

```sh
python3 tools/x810-install doctor
python3 tools/x810-install install --plan-only
```

These do not write tablet partitions. The normal install requires a new
account identity/password and exact confirmations. It reads a saved Android
set from the existing rootfs or, on a first install after explicit
confirmation, reads the four boot partitions. It writes only `linuxroot`; GPT,
boot, recovery, vbmeta, userdata, and firmware partitions are not written, and
it never reboots.

The public rootfs build is `rootfs/build-rootfs.sh`; release publication uses
the same script in GitHub Actions. See [ROOTFS-ARTIFACT.md](ROOTFS-ARTIFACT.md).
