# Private rootfs archive

The local rootfs under `work/rootfs/` contains private state (SSH host keys,
the user's authorized key, a saved NetworkManager connection, Tailscale node
state, and a salted `/etc/shadow` password hash). The timestamped archive is stored under
`out/private-rootfs/`; its exact path, SHA-256 and size are recorded in the
ignored local file `docs/ARCH-ROOTFS-ARTIFACT.lock`. Do not commit, upload,
or share it. The
packaging script creates a mode-0700 output directory and mode-0600 archive
and checksum sidecar. This is local filesystem protection, **not encryption**;
use encrypted storage if the artifact must leave this machine.

Create a private local snapshot from the devnode, when the rootfs is idle:

```sh
tools/package-rootfs-private.sh
```

The optional first argument may select a disposable rootfs below
`work/` or `tmp/`; the optional second
argument is a label. The script uses the project-local rootless Podman store
and must be run as an unprivileged devnode user; it rejects EUID 0. Image pulls
are disabled. The container mounts only the rootfs read-only and one output
file writable, disables networking, and does not run on Windstation.
It emits `out/private-rootfs/<label>-<UTC timestamp>.tar.zst` and a matching
SHA-256 sidecar. The archive itself is not checked into Git and contains no
plaintext password. It contains a `slightlywind` build-time SSH bootstrap; the
installer removes that account/home after extraction, prompts for the fresh
user's identity and password, then creates the requested account while
preserving only the authorized public SSH key.

The GNU tar archive is POSIX/PAX format and records numeric UID/GID, file
modes, timestamps, and sparse extents. It deliberately omits ACLs and xattrs:
the target TWRP Toybox tar cannot restore them, and the staged source tree may
carry host-inherited SELinux labels that must not be copied to the tablet.
File-capability xattrs are not restored either; this SSH-first rootfs does not
depend on them for its intended remote-work use. The archive excludes the
contents of volatile `/run` but retains its directory. It does not normalize
ownership, modes, or mtimes. The rootless build container is used because a
host-side tar would see subordinate host IDs instead of the target rootfs IDs.
The archive verifier checks zstd integrity, critical numeric owners/modes, the
absence of unsupported xattr/ACL metadata, required package-database records
for the explicit GNOME/GDM/Tab Companion profile, GDM's enablement and default
graphical target, the pacman filesystem/syscall sandbox policy, the single
private NetworkManager profile, required module/firmware paths, and the
deliberate `/run` exclusion without printing private file contents. It also
rejects plaintext-looking shadow fields and requires root to remain locked.

The real local private `work/rootfs` was archived and passed the metadata/
integrity verifier. Separate disposable synthetic tests confirmed UID/GID
0:0 and 1000:1000, modes, symlink/empty-directory handling, and metadata
handling in the recovery's Toybox tar. The builder tag is local, not a
repository lock: its Containerfile pins the
base image and PRoot commit, but its `pacman -Syu` layer depends on package state
at image-build time. Record/verify the local image digest separately when
exact tool-image repeatability is required.

For a privileged restore to an empty target rootfs, the corresponding GNU tar
options are:

```sh
tar --extract --zstd --file=windstation-arch-rootfs.tar.zst \
  --directory=/target/rootfs --numeric-owner --same-owner --same-permissions
```

Restore as root in the target environment. Verify the sidecar before use. A
successful archive/checksum only establishes transfer integrity; it does not
establish that the rootfs boots or that its private credentials are safe to
disclose.
