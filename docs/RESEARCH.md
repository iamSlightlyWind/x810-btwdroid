# Port research — 2026-11-11

## Findings

1. **A custom Arch ARM userspace is a supported generic-device use case.**
   Arch Linux ARM publishes a signed generic AArch64 root filesystem and says
   devices without a targeted image can use it with their own kernel. Its
   AArch64 repositories include GNOME Shell, Mutter and Mesa. The X810-specific
   kernel and graphics firmware remain our responsibility.
2. **I found no maintained native Arch boot image for the Tab S9 family.** The
   wider search surfaced a native Arch Linux ARM port for the *Galaxy S9
   phone* (Exynos 9810), Arch-in-Termux/PRoot or chroot setups for tablets, and
   Arch-hosted remote-display tools. None targets the Tab S9/S9+/Ultra's
   SM8550 tablet hardware. The original Tab S9 Wi-Fi Fedora porter reports
   trying Arch along with Gentoo, Void, Debian and Ubuntu, but that is not
   evidence of a published, maintained Arch image or of X810 validation.
   Two cross-device Arch references are checked out locally: `ztOS` (a beta
   native Arch ARM project for a Galaxy S9 phone; its README says the installer
   has not been tested on real hardware, so it is useful for image/build
   separation only) and
   `synport` (an Arch ARM next-to-Android installer, with a Galaxy Tab A
   listed as a port; its repository is releases/installer material, not a
   source port for this tablet). Neither supplies transferable X810 drivers.
3. **The S9 Ultra mainline ports are strong boot/userspace references.** The
   Ubuntu X910 project uses Linux 7.2.9 with GNOME 50 and Wayland; its hardware
   notes describe deliberately retaining a proven kernel/DTS while changing
   userspace. Its pmOS predecessor also separates the kernel/device layer
   from its rootfs. These projects share SM8550/Adreno 740, but X910 has
   WCN7850/ath12k, a Goodix touchscreen and a different panel. Windstation is
   X810 with WCN6855/ath11k, FTS1BA90A and the 2800×1752 panel. Reuse the
   architecture and methods, not those model-specific device settings.
4. **There is family-wide Ubuntu Touch work, but it is not an Arch reference.**
   Whitehat Hardware reports its X910 Ubuntu Touch port as stable and X710/X810
   as bring-up, explicitly meaning their builds have not been validated on
   those devices. Its firmware/revision-aware build strategy may inform later
   recovery packaging; Halium-specific kernel details do not replace our
   mainline X810 support.
5. **Tab Companion is partly ready for Arch.** It already has a PKGBUILD
   template and pacman-based app packaging. Its X810 kernel updater is still
   Fedora-specific: it expects Fedora release tags/manifests and downloads a
   `kernel.rpm`. For the first Arch image, defer in-app kernel updates; add an
   Arch-native X810 support package and update channel later.

## Relevant sources

- [Arch Linux ARM downloads and generic-device instructions](https://archlinuxarm.org/about/downloads)
- [Arch Linux ARM package-signing instructions](https://archlinuxarm.org/about/package-signing)
- [Arch Linux ARM AArch64 GNOME Shell](https://archlinuxarm.org/packages/aarch64/gnome-shell)
- [Arch Linux ARM AArch64 Mesa](https://archlinuxarm.org/packages/aarch64/mesa)
- [Ubuntu 26.04 on Galaxy Tab S9 Ultra](https://github.com/agcarbajo/ubuntu-galaxy-tab-s9-ultra)
- [pmOS mainline port for Galaxy Tab S9 Ultra](https://github.com/agcarbajo/postmarketos-galaxy-tab-s9-ultra)
- [Ubuntu Touch family port status](https://ports.whitehathardware.com/tab-s9/)
- [Original S9 Wi-Fi Fedora port](https://github.com/nacht20-de/gts9wifi-fedora-linux)
- [Original Fedora porter's report of trying other distributions](https://www.reddit.com/r/Fedora/comments/1wkwhu7/fedora_on_a_samsung_tab_s9/)
- [ztOS native Arch ARM on the Galaxy S9 phone](https://github.com/Zerone-Laboratories/ztOS)
- [synport Arch ARM phones/tablets installer project](https://github.com/VitaminDB/synport)
- [Arch in Termux/PRoot on the Galaxy Tab S9 Ultra](https://github.com/yanghoeg/usix-termux)
- [Tab S9 Wi-Fi upstream DTS series (X710 only)](https://lore.landau.one/lkml/179416929465.628393.6808030568990049146.b4-ty%40b4/)

## Local reference checkouts

See [`SOURCES.md`](SOURCES.md) for exact commit IDs and checked-out locations.
The local sources are research copies; preserve their licenses and do not copy
third-party code into a Windstation package without checking its file-level
license and provenance.

## Official Arch ARM base download status

The official generic AArch64 rootfs archive was downloaded to `cache/` and
cryptographically verified before being treated as a build input. Its SHA-256
is `42a4eeaa038994ffd31fa173256ef2f0ef511358eeb41b9ea1f8626391b9b319`; the
detached signature is also pinned in [`ALARM-ROOTFS.lock`](ALARM-ROOTFS.lock).
The embedded Arch Linux ARM keyring was extracted from the signed archive, and
the full signing fingerprint was checked against the official published
fingerprint `68B3537F39A313B3E574D06777193F152BDBE6A6`. GPG reported a good
signature (trust remains unassessed locally, as expected for an untrusted
keyring); the fingerprint comparison authenticates which key was used. Run
`tools/verify-alarm-rootfs.sh` to repeat the SHA-256, pinned-key and detached
signature checks before extracting it.

The tarball contains 165 installed package records, including the generic
`linux-aarch64 7.1.6-1`, `linux-firmware 20260622-1`, and
`linux-firmware-whence 20260622-1`. In the current prepared rootfs,
`linux-aarch64` is absent, but the `linux-firmware` split-package family is
still present in the 188-package inventory. Do not infer that all generic
firmware was removed: trimming that family remains follow-up work. Preserve
the existing `7.2.0-gts9wifi` boot set for the first userspace-only trial.
See [`ALARM-ROOTFS-PACKAGES.txt`](ALARM-ROOTFS-PACKAGES.txt) for the exact
base-package inventory.
