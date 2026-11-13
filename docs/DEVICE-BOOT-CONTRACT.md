# Windstation boot contract

The existing X810 boot chain mounts the Linux root filesystem by the GPT
partition label `linuxroot`, as ext4, with `rootwait`. The Arch rootfs uses the
same label/filesystem contract. Device-node names such as `/dev/sda35` are
runtime details; the installer resolves and validates the labeled partition.

The first Arch trial reuses the existing X810 kernel and boot images. The
installer saves the four boot-set images (`boot`, `init_boot`, `vendor_boot`,
and `dtbo`) before formatting linuxroot, then stages the Android set under
`/var/lib/x810-boot-sets/android` for Tab Companion. It never writes the kernel,
DTB, initramfs, bootconfig, or any boot partition. This contract does not prove
that the Arch userspace boots or that its hardware support works; those require
on-device testing.
