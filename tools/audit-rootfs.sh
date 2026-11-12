#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
workspace_dir="$(cd -- "$project_dir/.." && pwd)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
mkdir -p "$podman_root" "$podman_runroot"

podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --rm --security-opt label=disable \
  --volume "$workspace_dir:/workspace:rw" --workdir /workspace \
  "$image" -lc '
    set -euo pipefail
    project=/workspace/x810-btwdroid
    rootfs="$project/work/rootfs"
    release=7.2.0-gts9wifi
    target() { /opt/proot/src/proot -0 -q /usr/bin/qemu-aarch64-static \
      -r "$rootfs" -w / -b /dev -b /proc -b /sys -b /tmp "$@"; }
    target /usr/bin/pacman -Q > /dev/null
    target /usr/bin/pacman -Q x810-device-support networkmanager wpa_supplicant \
      openssh sudo zram-generator >/dev/null
    target /usr/bin/pacman -Q gdm gnome-shell gnome-session \
      gnome-control-center gnome-terminal brave-bin bluez bluez-utils \
      pipewire-jack noto-fonts tab-companion >/dev/null
    ! target /usr/bin/pacman -Q linux-aarch64 >/dev/null 2>&1
    [[ -s "$rootfs/usr/lib/modules/$release/modules.dep" ]]
    [[ "$(systemctl --root="$rootfs" is-enabled gdm.service)" == enabled ]]
    [[ "$(systemctl --root="$rootfs" get-default)" == graphical.target ]]
    [[ "$(systemctl --root="$rootfs" is-enabled bluetooth.service)" == enabled ]]
    [[ -L "$rootfs/etc/systemd/system/display-manager.service" ]]
    [[ -L "$rootfs/etc/systemd/system/default.target" ]]
    grep -qx AutoEnable=true "$rootfs/etc/bluetooth/main.conf"
    python3 "$project/tools/configure-target-pacman.py" --check "$rootfs/etc/pacman.conf"
    for helper in x810-boot-switch-core tab-companion-boot-status tab-companion-boot-switch; do
      [[ -x "$rootfs/usr/local/libexec/$helper" ]]
    done
    [[ -f "$rootfs/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/extension.js" ]]
    [[ -f "$rootfs/usr/share/tab-companion/port.json" ]]
    [[ -f "$rootfs/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json" ]]
    target /usr/bin/passwd -S root | grep -q "^root L "
    if target /usr/bin/getent passwd alarm >/dev/null 2>&1; then
      target /usr/bin/passwd -S alarm | grep -q "^alarm L "
    fi
    [[ ! -e "$rootfs/var/lib/tailscale/tailscaled.state" ]]
    [[ ! -e "$rootfs/etc/ssh/ssh_host_ed25519_key" ]]
    [[ -z "$(find "$rootfs/etc/NetworkManager/system-connections" -type f -print -quit 2>/dev/null)" ]]
    [[ ! -e "$rootfs/etc/wpa_supplicant/wpa_supplicant.conf" ]]
    [[ -z "$(find "$rootfs/home" "$rootfs/root" -path "*/.ssh*" -print -quit 2>/dev/null)" ]]
    [[ -z "$(find "$rootfs/home" -mindepth 1 -maxdepth 1 ! -name alarm -print -quit 2>/dev/null)" ]]
    grep -Fxq PasswordAuthentication\ yes "$rootfs/etc/ssh/sshd_config.d/90-windstation.conf"
    grep -Fxq PermitRootLogin\ no "$rootfs/etc/ssh/sshd_config.d/90-windstation.conf"
    echo "Rootfs audit passed: Arch ARM GNOME/GDM, matching X810 modules, Bluetooth, Tab Companion dualboot, fresh-user provisioning, and no private credentials."
  '
