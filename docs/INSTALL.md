# Installer and build checks

`tools/x810-install` is the Python host installer. It fetches the latest
verified GitHub rootfs release (or uses the local cache with `--no-update`),
validates the device in TWRP, formats only `linuxroot`, provisions a fresh
account, verifies the extracted tree, and stops without rebooting.

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
account identity/password and two exact confirmations. It writes no Android,
GPT, boot, recovery, vbmeta, or firmware partition, and never reboots.

The public rootfs build is `rootfs/build-rootfs.sh`; release publication uses
the same script in GitHub Actions. See [ROOTFS-ARTIFACT.md](ROOTFS-ARTIFACT.md).
