# Rootfs-only installer

`tools/x810-install` installs an audited Arch rootfs from TWRP onto the
existing `linuxroot` partition. It does not repartition the tablet or write
Android, boot, recovery, or firmware partitions. It does not reboot.

## Host checks

Run from the repository root:

```sh
bash -n tools/*.sh tools/x810-install x810-build
python3 -m compileall -q tools
python3 tools/test-x810-install.py
python3 tools/test-target-pacman-policy.py
python3 tools/test-rootfs-image-profile.py
python3 tools/test-verify-rootfs-archive.py
python3 tools/test-tab-companion-overlay.py
```

## Recovery checks

With the intended tablet already in TWRP and attached by USB:

```sh
tools/x810-install doctor
tools/x810-install install --plan-only
```

These commands are read-only. Review device identity, the `linuxroot` target,
rootfs profile, archive SHA-256, and backup summary. Only after review, run
`tools/x810-install install` to replace `linuxroot`. The installer requires
fresh account details and exact typed confirmations, verifies the written
filesystem, and stops in TWRP.

The installer accepts only an audited, checksummed artifact under
`out/private-rootfs/`. See [ROOTFS-ARTIFACT.md](ROOTFS-ARTIFACT.md) for its
contents and handling requirements. These artifacts are private local build
outputs and must not be published.
