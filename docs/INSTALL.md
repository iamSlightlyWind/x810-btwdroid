# Installer and build checks

`tools/x810-install` is the Python host installer. It fetches the latest
verified GitHub rootfs release (or uses the local cache with `--no-update`),
checks rooted/unlocked Android before fetching the release, prompts for manual
TWRP entry when started from Android (or accepts TWRP already open), saves the Android `boot`, `init_boot`,
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

The tablet may be in Android or already in TWRP:

```sh
python3 tools/x810-install doctor
python3 tools/x810-install install --plan-only
```

The installer does not fetch the large rootfs until the initial Android/TWRP
identity and unlock checks pass. These commands do not write tablet partitions. The normal install requires a new
account identity/password and exact confirmations. It reads a saved Android
set from the existing rootfs or, on a first install after explicit
confirmation, reads and backs up the four boot partitions. It formats
`linuxroot`, installs the rootfs, then writes and read-back-verifies the Linux
images to `boot`, `init_boot`, `vendor_boot`, and `dtbo`. GPT, userdata,
recovery, vbmeta, and firmware are not written. It never reboots; the next
normal boot should start Arch Linux ARM. The host backup retains Android's
original boot images for the dual-boot switcher or manual recovery.

The public rootfs build is `rootfs/build-rootfs.sh`; release publication uses
the same script in GitHub Actions. See [ROOTFS-ARTIFACT.md](ROOTFS-ARTIFACT.md).
