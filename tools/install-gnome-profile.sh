#!/usr/bin/env bash
set -euo pipefail
umask 077

# Build-only profile step. This mutates only work/rootfs on
# devnode, then audits and archives that tree; it never connects to Windstation.
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
rootfs="$project_dir/work/rootfs"
packages_dir="$project_dir/out/packages"
pacman_conf="$rootfs/etc/pacman.conf"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

[[ -d "$rootfs/etc/pacman.d" && ! -L "$rootfs" ]] \
    || die "missing/non-directory target rootfs: $rootfs (run prepare/configuration first)"
[[ -f "$pacman_conf" && ! -L "$pacman_conf" ]] \
    || die "missing or unsafe target pacman.conf: $pacman_conf"
[[ -d "$packages_dir" && ! -L "$packages_dir" ]] \
    || die "missing package output directory: $packages_dir"

shopt -s nullglob
device_packages=("$packages_dir"/x810-device-support-*-aarch64.pkg.tar.zst)
app_packages=("$packages_dir"/tab-companion-*-any.pkg.tar.zst)
shopt -u nullglob
(( ${#device_packages[@]} == 1 )) \
    || die "expected exactly one local x810-device-support *-aarch64.pkg.tar.zst under $packages_dir; run tools/build-packages.sh and remove stale duplicates"
device_package="${device_packages[0]}"
[[ -f "$device_package" && ! -L "$device_package" && -s "$device_package" ]] \
    || die "X810 device-support package is not a non-empty regular file: $device_package"
device_files="$(tar --zstd -tf "$device_package")" \
    || die "could not list local X810 device-support package contents"
grep -Fxq 'usr/share/tab-companion/port.json' <<< "$device_files" \
    || die "X810 device-support package is missing usr/share/tab-companion/port.json"
(( ${#app_packages[@]} == 1 )) \
    || die "expected exactly one local tab-companion *-any.pkg.tar.zst under $packages_dir; run tools/build-packages.sh and remove stale duplicates"
app_package="${app_packages[0]}"
[[ -f "$app_package" && ! -L "$app_package" && -s "$app_package" ]] \
    || die "Tab Companion package is not a non-empty regular file: $app_package"
app_files="$(tar --zstd -tf "$app_package")" \
    || die "could not list local Tab Companion package contents"
grep -Fxq 'usr/share/glib-2.0/schemas/io.github.agcarbajo.TabCompanion.gschema.xml' \
    <<< "$app_files" || die "Tab Companion package is missing its GSettings schema XML"
if grep -Fxq 'usr/share/glib-2.0/schemas/gschemas.compiled' <<< "$app_files"; then
    die "Tab Companion package must not ship the generated shared gschemas.compiled cache"
fi

brave_packages=("$packages_dir"/brave-bin-*-aarch64.pkg.tar.zst)
(( ${#brave_packages[@]} == 1 )) \
    || die "expected exactly one local brave-bin *-aarch64.pkg.tar.zst under $packages_dir; run tools/build-packages.sh and remove stale duplicates"
brave_package="${brave_packages[0]}"
[[ -f "$brave_package" && ! -L "$brave_package" && -s "$brave_package" ]] \
    || die "Brave package is not a non-empty regular file: $brave_package"
brave_info="$("$script_dir/pacman-target.sh" --builder-mode -Qip "/work/packages/$(basename -- "$brave_package")")"
brave_identity="$(awk -F: '
    $1 ~ /^[[:space:]]*Name[[:space:]]*$/ { name = $2; gsub(/^[[:space:]]+|[[:space:]]+$/, "", name) }
    $1 ~ /^[[:space:]]*Architecture[[:space:]]*$/ { arch = $2; gsub(/^[[:space:]]+|[[:space:]]+$/, "", arch) }
    END { print name, arch }
' <<< "$brave_info")"
[[ "$brave_identity" == "brave-bin aarch64" ]] \
    || die "local package metadata is not an AArch64 brave-bin package"

device_info="$("$script_dir/pacman-target.sh" --builder-mode -Qip "/work/packages/$(basename -- "$device_package")")"
device_identity="$(awk -F: '
    $1 ~ /^[[:space:]]*Name[[:space:]]*$/ { name = $2; gsub(/^[[:space:]]+|[[:space:]]+$/, "", name) }
    $1 ~ /^[[:space:]]*Architecture[[:space:]]*$/ { arch = $2; gsub(/^[[:space:]]+|[[:space:]]+$/, "", arch) }
    END { print name, arch }
' <<< "$device_info")"
[[ "$device_identity" == "x810-device-support aarch64" ]] \
    || die "local package metadata is not an AArch64 x810-device-support package"

# Pacman's recent filesystem sandbox depends on Landlock, which is missing in
# the shipped X810 kernel configuration. Disable only that sandbox in the
# staged target config; leave the syscall sandbox active.
"$script_dir/configure-target-pacman.py" "$pacman_conf"

app_name="$(basename -- "$app_package")"
app_info="$("$script_dir/pacman-target.sh" --builder-mode -Qip "/work/packages/$app_name")"
app_identity="$(awk -F: '
    $1 ~ /^[[:space:]]*Name[[:space:]]*$/ { name = $2; gsub(/^[[:space:]]+|[[:space:]]+$/, "", name) }
    $1 ~ /^[[:space:]]*Architecture[[:space:]]*$/ { arch = $2; gsub(/^[[:space:]]+|[[:space:]]+$/, "", arch) }
    END { print name, arch }
' <<< "$app_info")"
[[ "$app_identity" == "tab-companion any" ]] \
    || die "local package metadata is not an architecture-independent tab-companion package"

# Do not install the whole `gnome` group: its current ARM metadata includes
# applications with unresolved deps in the Arch Linux ARM repositories. Use a
# known core shell/session/display-manager set plus a few small session tools.
# The existing upgrade-rootfs script runs a full -Syu for the whole system and
# these desktop/application targets, then updates archlinux-keyring separately
# outside PRoot/QEMU. No partial -Sy is used.
desktop_packages=(
    gnome-shell
    gnome-session
    gdm
    gnome-control-center
    gnome-terminal
    bluez
    bluez-utils
    tuned-ppd
    dtc
    pipewire-jack
    noto-fonts
    python
    python-gobject
    python-dbus
    gtk4
    libadwaita
    glib2
    polkit
    systemd
    dbus
    zram-generator
)
"$script_dir/upgrade-rootfs.sh" "${desktop_packages[@]}"

# Pacman -S accepts repository targets, not a local package archive. Install
# the already-verified local packages with -U only after the full -Syu has
# installed their declared repository dependencies above. The local device
# support package provides the X810 zram configuration and conservative
# full X810 tablet control layer and conservative thermal limiter.
# GNOME pulls in the repository iio-sensor-proxy. The X810 package deliberately
# replaces it with the SSC-capable implementation; remove the generic package
# first, in this disposable target rootfs, so --noconfirm cannot reject the
# conflict prompt and abort the profile build.
for conflicting_package in iio-sensor-proxy libssc; do
    if "$script_dir/pacman-target.sh" --builder-mode -Q "$conflicting_package" >/dev/null 2>&1; then
        "$script_dir/pacman-target.sh" --builder-mode -Rdd --noconfirm "$conflicting_package"
    fi
done
"$script_dir/pacman-target.sh" --builder-mode -U --noconfirm \
    "/work/packages/$(basename -- "$device_package")" \
    "/work/packages/$app_name" \
    "/work/packages/$(basename -- "$brave_package")"
glib-compile-schemas "$rootfs/usr/share/glib-2.0/schemas"
[[ -s "$rootfs/usr/share/tab-companion/port.json" ]] \
    || die "Arch port.json was not installed from x810-device-support"
[[ -s "$rootfs/usr/share/dbus-1/system.d/80-x810-wpa_supplicant.conf" ]] \
    || die "wpa_supplicant D-Bus policy is missing from x810-device-support"
[[ -s "$rootfs/etc/environment.d/91-x810-gtk-rendering.conf" ]] \
    || die "X810 GTK rendering workaround is missing from x810-device-support"
[[ -s "$rootfs/etc/systemd/system.conf.d/90-x810-boot-logs.conf" ]] \
    || die "systemd boot progress policy is missing from x810-device-support"
[[ -s "$rootfs/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json" ]] \
    || die "Arch dualboot extension metadata was not installed"

# Keep the clean image to the shell/session/settings core, not standalone
# applications selected by the broad `gnome` group. Never repair an old staged
# install here; the build entry point starts from the signed ALARM archive.

"$script_dir/configure-target-pacman.py" --check "$pacman_conf"

systemctl --root="$rootfs" set-default graphical.target
systemctl --root="$rootfs" enable gdm.service >/dev/null
systemctl --root="$rootfs" enable bluetooth.service >/dev/null
systemctl --root="$rootfs" enable tuned.service tuned-ppd.service >/dev/null
systemctl --root="$rootfs" enable x810-thermal-limit.service >/dev/null
systemctl --root="$rootfs" enable gts9wifi-device-control.service >/dev/null
systemctl --root="$rootfs" enable gts9wifi-bt-provision.service >/dev/null
systemctl --root="$rootfs" enable x810-charge-limit.service >/dev/null
systemctl --root="$rootfs" enable \
    gts9wifi-android-parts.service vendor.mount vendor-firmware_mnt.mount \
    vendor-dsp.mount mnt-vendor-persist.mount gts9wifi-wait-sensor-proxy.timer >/dev/null

# Make the supported controller auto-power policy explicit in the target.
python3 - "$rootfs/etc/bluetooth/main.conf" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
updated, count = re.subn(r"(?m)^\s*#?\s*AutoEnable\s*=.*$", "AutoEnable=true", text)
if count != 1:
    raise SystemExit(f"expected one BlueZ AutoEnable setting in {path}; found {count}")
path.write_text(updated, encoding="utf-8")
PY

for package in x810-device-support zram-generator gdm gnome-shell gnome-session gnome-control-center \
    gnome-terminal brave-bin bluez bluez-utils tuned-ppd dtc pipewire-jack noto-fonts tab-companion; do
    "$script_dir/pacman-target.sh" --builder-mode -Q "$package" >/dev/null \
        || die "expected desktop package is missing from staged rootfs: $package"
done
for helper in x810-boot-switch-core tab-companion-boot-status tab-companion-boot-switch; do
    [[ -x "$rootfs/usr/local/libexec/$helper" ]] \
        || die "Arch Tab Companion dualboot helper is missing: $helper"
done
[[ -f "$rootfs/usr/libexec/tab-companion-admin" ]] \
    || die "Arch Tab Companion administrator dispatcher is missing"
[[ -f "$rootfs/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/extension.js" ]] \
    || die "Arch Tab Companion dualboot GNOME integration is missing"
grep -q archarm "$rootfs/usr/local/libexec/x810-boot-switch-core" \
    || die "the installed dualboot backend does not recognize Arch Linux ARM"
[[ -f "$rootfs/usr/lib/systemd/system/gdm.service" ]] \
    || die "GDM package did not install gdm.service"
[[ -f "$rootfs/usr/lib/systemd/system/bluetooth.service" ]] \
    || die "BlueZ package did not install bluetooth.service"
for unit in tuned.service tuned-ppd.service x810-thermal-limit.service gts9wifi-device-control.service \
    gts9wifi-bt-provision.service x810-charge-limit.service gts9wifi-android-parts.service \
    vendor.mount vendor-firmware_mnt.mount vendor-dsp.mount mnt-vendor-persist.mount \
    gts9wifi-wait-sensor-proxy.timer; do
    [[ -f "$rootfs/usr/lib/systemd/system/$unit" ]] \
        || die "X810 feature unit is missing: $unit"
    [[ "$(systemctl --root="$rootfs" is-enabled "$unit")" == enabled ]] \
        || die "X810 feature unit is not enabled: $unit"
done
for helper in gts9wifi-bt-provision gts9wifi-bt-revive gts9wifi-device-control x810-charge-limit; do
    [[ -x "$rootfs/usr/libexec/$helper" ]] || die "X810 feature helper is missing: $helper"
done
[[ -s "$rootfs/usr/share/gnome-shell/extensions/gnome-gts9wifi@tabs9linux/extension.js" ]] \
    || die "X810 GNOME device-controls extension is missing"
grep -Fq "'gnome-gts9wifi@tabs9linux'" "$rootfs/usr/share/glib-2.0/schemas/gschemas.compiled" \
    || die "X810 GNOME device-controls extension is not in the compiled default schema"
[[ "$(systemctl --root="$rootfs" is-enabled gdm.service)" == enabled ]] \
    || die "GDM is not enabled in the staged rootfs"
[[ "$(systemctl --root="$rootfs" is-enabled bluetooth.service)" == enabled ]] \
    || die "Bluetooth service is not enabled in the staged rootfs"
grep -qx 'AutoEnable=true' "$rootfs/etc/bluetooth/main.conf" \
    || die "BlueZ AutoEnable is not enabled in the staged rootfs"
grep -Fxq 'Options=ro,noload,nosuid,nodev,noexec' \
    "$rootfs/usr/lib/systemd/system/mnt-vendor-persist.mount" \
    || die "Android persist must be mounted read-only without journal replay"
grep -Fxq 'Type=erofs' "$rootfs/usr/lib/systemd/system/vendor.mount" \
    || die "Android vendor logical partition mount is missing"
for helper in gts9wifi-adsp-boot gts9wifi-android-parts gts9wifi-sensor-registry-perms \
    gts9wifi-sensors-resume gts9wifi-wait-fastrpc gts9wifi-wait-sensor-proxy \
    iio-sensor-proxy; do
    [[ -x "$rootfs/usr/libexec/$helper" ]] || die "X810 sensor helper is missing: $helper"
done
for executable in hexagonrpcd pd-mapper ssccli; do
    [[ -x "$rootfs/usr/bin/$executable" ]] || die "X810 sensor executable is missing: $executable"
done
[[ -e "$rootfs/usr/lib/libssc.so.2" && -e "$rootfs/usr/lib/libhexagonrpc.so.0.4" \
    && -e "$rootfs/usr/lib/libqrtr.so.1" ]] || die "X810 sensor runtime libraries are missing"
grep -Fxq 'GSK_GPU_DISABLE=merge' "$rootfs/etc/environment.d/91-x810-gtk-rendering.conf" \
    || die "GTK draw-merge workaround is not enabled in the staged rootfs"
grep -Fxq 'ShowStatus=yes' "$rootfs/etc/systemd/system.conf.d/90-x810-boot-logs.conf" \
    || die "systemd boot status output is not enabled in the staged rootfs"
[[ "$(systemctl --root="$rootfs" get-default)" == graphical.target ]] \
    || die "staged rootfs default target is not graphical.target"

cat > "$rootfs/etc/windstation-arch-profile" <<'EOF'
profile=gnome
display_manager=gdm
tab_companion=installed
bluetooth=enabled
pacman_disable_sandbox_filesystem=yes
pacman_disable_sandbox_syscalls=no
EOF
chmod 0644 "$rootfs/etc/windstation-arch-profile"

# Package hooks can create or expose credentials after the initial SSH setup.
# Scrub all release-private state using PRoot's fake-root view of the target.
"$script_dir/scrub-rootfs-private-state.sh"

# Remove only build-time package archives and sync databases from the staged
# image.  CI may keep the verified package archives in an external Actions
# cache; pacman -Scc would erase that reusable cache as well.  -Sc removes
# only obsolete versions from that external cache, retaining archives for the
# currently installed packages for reuse by the next rolling-repository build.
if [[ -n "${X810_PACMAN_CACHE_DIR:-}" ]]; then
    "$script_dir/pacman-target.sh" --builder-mode -Sc --noconfirm
fi
"$script_dir/clean-rootfs-cache.sh"

"$script_dir/audit-rootfs.sh"

echo "Built and audited the GNOME/GDM Arch profile in the staged rootfs."
echo "Packages: X810 zram/thermal defaults, minimal GNOME Shell/session/GDM/Settings, GNOME Terminal, Brave, BlueZ utilities, required fonts/audio and Tab Companion dependencies; no GNOME app group."
echo "Default target: graphical.target; GNOME, Bluetooth, power profiles, thermal/device controls, charge-limit restore, and Bluetooth provisioning are enabled."
echo "Pacman: filesystem sandbox disabled for the X810 kernel; syscall sandbox remains enabled."
echo "The public image contains no human account or private SSH/network state; the installer creates a fresh account."
echo "Windstation was not accessed, rebooted, or written."
