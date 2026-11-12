# Tab Companion image package

This optional package uses Tab Companion's existing Arch-capable source
builder, pinned to the upstream commit recorded in `SOURCE.lock`. The local
PKGBUILD follows `packaging/arch/PKGBUILD.in`: it assembles the self-contained
application bundle, installs it as an `arch=('any')` package, and removes the
Fedora port-origin file so it cannot label the Arch rootfs as Fedora.

Build on an Arch/base-devel host or in an equivalent Arch build environment,
as a normal user (not root):

```sh
makepkg --nodeps --noconfirm --cleanbuild
```

The resulting package is `tab-companion-1.4.2-3-any.pkg.tar.zst`. The
`--nodeps` flag is for the build environment only; the package declares its
runtime dependencies, which must be present in the image. In particular,
`gnome-shell` is a declared dependency, so this package belongs in the GNOME
image profile, not a minimal SSH-only profile. The package is architecture
independent and has no native compilation step; a later rootfs installation
still needs the matching AArch64 pacman environment/transaction.

The Arch wrapper strips the generated `gschemas.compiled` cache from the
shared Fedora bundle but keeps the `*.gschema.xml` source. Arch's glib2
libalpm hook owns and regenerates the shared cache after the package XML is
installed; shipping that cache causes a file conflict after the full rootfs
upgrade has already compiled installed schemas.

The upstream shared application bundle contains Fedora-specific X810 helper
files. The GTK Updates page exposes the guarded kernel/boot section only on an
RPM system with the SM-X810 and `x810-fedora` port identity; the TUI exposes
that menu only for an RPM manager on SM-X810. The Arch package manager is
`pacman`, so neither interface offers the Fedora kernel updater here. This
package does not add an Arch kernel updater.

The package keeps Fedora's X810 dualboot page and adds an Arch-aware backend.
Arch Linux ARM is displayed by its real name but uses the legacy `fedora` set
ID so the Android-side selector remains compatible. Switching requires a
complete Android and Linux boot set under `/var/lib/x810-boot-sets`; the
authenticated helper validates SM-X810 identity, partition sizes and
read-back before touching only `boot`, `init_boot`, `vendor_boot`, and `dtbo`.
The package build never runs that helper. The current rootfs build has no
boot-set images staged, so the tab will appear but no switch is ready until
those sets are provided. The Fedora kernel updater remains Fedora-only and is
not exposed as an Arch kernel updater.
The generic Arch port-update page is available only after the separate Arch
device-support package installs its own `/usr/share/tab-companion/port.json`.
The currently built `x810-device-support-0.1.0-1` package does not yet include
that file, so this image-prep package does not currently activate a port-update
feed; add metadata only once a public Arch release workflow/repository is
available and its manifest matches the updater contract.

This recipe does not add the app to the signed Arch Linux ARM bootstrap
inventory (`docs/ALARM-ROOTFS-PACKAGES.txt`); that file records only packages
already present in the downloaded base archive. Image assembly must explicitly
build and install this optional package in a later preparation step.
