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
    candidate_roots=(/etc /home /root /usr /var /opt /srv /boot /tmp /mnt /media /run /lib /lib64 /bin /sbin)
    scan_roots=()
    target() { /opt/proot/src/proot -0 -q /usr/bin/qemu-aarch64-static \
      -r "$rootfs" -w / -b /dev -b /proc -b /sys -b /tmp "$@"; }
    target_tree() { /opt/proot/src/proot -0 -q /usr/bin/qemu-aarch64-static \
      -r "$rootfs" -w / -b /dev -b /proc -b /sys "$@"; }
    for candidate in "${candidate_roots[@]}"; do
      if target_tree /usr/bin/test -d "$candidate"; then
        scan_roots+=("$candidate")
      fi
    done
    audit_fail() { echo "Rootfs audit FAILED: $*" >&2; exit 1; }
    audit_check() {
      local label="$1"
      shift
      if "$@" >/dev/null; then
        echo "Rootfs audit OK: $label"
      else
        audit_fail "$label"
      fi
    }
    root_is_locked() { target /usr/bin/passwd -S root | grep -q "^root L "; }
    alarm_is_locked_if_present() {
      if target /usr/bin/getent passwd alarm >/dev/null 2>&1; then
        target /usr/bin/passwd -S alarm | grep -q "^alarm L "
      fi
    }
    no_private_ssh_wifi_paths() {
      local found
      found="$(target_tree /usr/bin/find "${scan_roots[@]}" \
        \( -iname ".ssh*" -o -iname "authorized_keys" \
          -o -iname "*ssh_host_*" \
          -o \( -iname "wpa_supplicant.conf" \
            ! -path "/usr/share/dbus-1/system.d/80-x810-wpa_supplicant.conf" \) \) -print -quit)"
      if [[ -n "$found" ]]; then
        echo "Private SSH or Wi-Fi credential path remains in target rootfs." >&2
        return 1
      fi
    }
    no_tailscale_state() {
      [[ -z "$(target_tree /usr/bin/find /var/lib -mindepth 1 -maxdepth 1 \
        -iname tailscale -print -quit)" ]]
    }
    no_extra_homes() {
      [[ -z "$(find "$rootfs/home" -mindepth 1 -maxdepth 1 ! -name alarm -print -quit 2>/dev/null)" ]]
    }
    no_nm_profiles() {
      [[ -z "$(find "$rootfs/etc/NetworkManager/system-connections" -type f -print -quit 2>/dev/null)" ]]
    }
    no_cached_packages() {
      [[ ! -d "$rootfs/var/cache/pacman/pkg" ]] \
        || [[ -z "$(find "$rootfs/var/cache/pacman/pkg" -type f -print -quit 2>/dev/null)" ]]
    }
    no_optional_apps() {
      local package
      for package in gnome-console gnome-boxes gnome-books; do
        if target /usr/bin/pacman -Q "$package" >/dev/null 2>&1; then
          echo "Optional GNOME application is installed: $package" >&2
          return 1
        fi
      done
    }
    audit_check "target pacman database is readable" target /usr/bin/pacman -Q
    audit_check "base packages are installed" target /usr/bin/pacman -Q \
      x810-device-support networkmanager wpa_supplicant openssh sudo zram-generator
    audit_check "optional GNOME applications are absent" no_optional_apps
    audit_check "GNOME, browser, Bluetooth, and Tab Companion packages are installed" \
      target /usr/bin/pacman -Q gdm gnome-shell gnome-session gnome-control-center \
      gnome-terminal brave-bin bluez bluez-utils tuned-ppd dtc pipewire-jack noto-fonts tab-companion
    if target /usr/bin/pacman -Q linux-aarch64 >/dev/null 2>&1; then
      audit_fail "generic linux-aarch64 kernel package must not be installed"
    fi
    echo "Rootfs audit OK: generic kernel package absent"
    audit_check "matching X810 module dependency map exists" test -s "$rootfs/usr/lib/modules/$release/modules.dep"
    audit_check "GDM is enabled" test "$(systemctl --root="$rootfs" is-enabled gdm.service)" = enabled
    audit_check "graphical.target is the default" test "$(systemctl --root="$rootfs" get-default)" = graphical.target
    audit_check "Bluetooth service is enabled" test "$(systemctl --root="$rootfs" is-enabled bluetooth.service)" = enabled
    for unit in tuned.service tuned-ppd.service x810-thermal-limit.service gts9wifi-device-control.service \
      gts9wifi-bt-provision.service x810-charge-limit.service; do
      audit_check "X810 feature unit is enabled: $unit" test "$(systemctl --root="$rootfs" is-enabled "$unit")" = enabled
    done
    for helper in gts9wifi-bt-provision gts9wifi-bt-revive gts9wifi-device-control x810-charge-limit; do
      audit_check "X810 feature helper is present: $helper" test -x "$rootfs/usr/libexec/$helper"
    done
    audit_check "GNOME device-controls extension is present" \
      test -f "$rootfs/usr/share/gnome-shell/extensions/gnome-gts9wifi@tabs9linux/extension.js"
    audit_check "display-manager.service points to GDM" test -L "$rootfs/etc/systemd/system/display-manager.service"
    audit_check "default.target symlink exists" test -L "$rootfs/etc/systemd/system/default.target"
    audit_check "BlueZ auto-enable is configured" grep -qx AutoEnable=true "$rootfs/etc/bluetooth/main.conf"
    audit_check "wpa_supplicant D-Bus policy is installed" \
      test -s "$rootfs/usr/share/dbus-1/system.d/80-x810-wpa_supplicant.conf"
    audit_check "GTK merge artifact workaround is installed" \
      grep -Fxq GSK_GPU_DISABLE=merge "$rootfs/etc/environment.d/91-x810-gtk-rendering.conf"
    audit_check "systemd boot progress is enabled" \
      grep -Fxq ShowStatus=yes "$rootfs/etc/systemd/system.conf.d/90-x810-boot-logs.conf"
    audit_check "target pacman sandbox policy is safe" \
      python3 "$project/tools/configure-target-pacman.py" --check "$rootfs/etc/pacman.conf"
    for helper in x810-boot-switch-core tab-companion-boot-status tab-companion-boot-switch; do
      audit_check "dualboot helper exists: $helper" test -x "$rootfs/usr/local/libexec/$helper"
    done
    audit_check "Tab Companion dualboot extension is present" \
      test -f "$rootfs/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/extension.js"
    audit_check "Arch Tab Companion port metadata is present" test -s "$rootfs/usr/share/tab-companion/port.json"
    audit_check "dualboot extension metadata is present" \
      test -f "$rootfs/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json"
    audit_check "root account is locked" root_is_locked
    audit_check "ALARM seed password is locked when present" alarm_is_locked_if_present
    audit_check "Tailscale device state is absent" no_tailscale_state
    audit_check "SSH and Wi-Fi credential paths are absent throughout rootfs" no_private_ssh_wifi_paths
    audit_check "NetworkManager saved profiles are absent" no_nm_profiles
    audit_check "downloaded pacman package archives are absent" no_cached_packages
    audit_check "no non-installer user home is included" no_extra_homes
    audit_check "password SSH is configured" grep -Fxq PasswordAuthentication\ yes "$rootfs/etc/ssh/sshd_config.d/90-windstation.conf"
    audit_check "root SSH login is disabled" grep -Fxq PermitRootLogin\ no "$rootfs/etc/ssh/sshd_config.d/90-windstation.conf"
    echo "Rootfs audit passed: Arch ARM GNOME/GDM, matching X810 modules, Bluetooth, Tab Companion dualboot, fresh-user provisioning, and no private credentials."
  '
