#!/usr/bin/env bash
# Configure first-boot networking and password-based SSH without embedding
# any account, Wi-Fi, SSH-host-key, or Tailscale state in the public image.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
workspace_dir="$(cd -- "$project_dir/.." && pwd -P)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
rootfs="$project_dir/work/rootfs"

[[ -d "$rootfs/etc" ]] || { echo "Missing target rootfs: $rootfs" >&2; exit 1; }
mkdir -p "$podman_root" "$podman_runroot"

podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --rm --security-opt label=disable \
  --volume "$workspace_dir:/workspace:rw" --workdir /workspace \
  "$image" -lc '
    set -euo pipefail
    rootfs=/workspace/x810-btwdroid/work/rootfs
    release=7.2.0-gts9wifi
    proot=(/opt/proot/src/proot -0 -q /usr/bin/qemu-aarch64-static \
      -r "$rootfs" -w / -b /dev -b /proc -b /sys -b /tmp)
    target() { "${proot[@]}" "$@"; }

    for package in networkmanager wpa_supplicant openssh sudo; do
      target /usr/bin/pacman -Q "$package" >/dev/null || {
        echo "required first-boot package is missing: $package" >&2; exit 1;
      }
    done
    [[ -f "$rootfs/usr/lib/modules/$release/modules.dep" ]] || {
      echo "matching X810 module tree is missing" >&2; exit 1;
    }

    # Generic ALARM bootstraps use alarm as their default UID 1000 account.
    # Lock it in the build image; the installer discards it and creates the
    # user requested during the fresh-install flow.
    target /usr/bin/passwd --lock root
    if target /usr/bin/getent passwd alarm >/dev/null; then
      target /usr/bin/passwd --lock alarm
    fi

    install -d -m 0755 "$rootfs/etc/ssh/sshd_config.d" "$rootfs/etc/sudoers.d"
    cat > "$rootfs/etc/ssh/sshd_config.d/90-windstation.conf" <<EOF
PasswordAuthentication yes
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin no
EOF
    cat > "$rootfs/etc/sudoers.d/40-windstation" <<EOF
%wheel ALL=(ALL:ALL) ALL
EOF
    chmod 0440 "$rootfs/etc/sudoers.d/40-windstation"
    cat > "$rootfs/etc/fstab" <<EOF
# Windstation (SM-X810), existing partition labels.
PARTLABEL=linuxroot  /     ext4  defaults,noatime  0 1
PARTLABEL=Swap       none  swap  defaults          0 0
EOF
    printf "%s\n" windstation > "$rootfs/etc/hostname"
    cat > "$rootfs/etc/hosts" <<EOF
127.0.0.1 localhost.localdomain localhost windstation
::1       localhost.localdomain localhost
EOF
    ln -sfn /usr/share/zoneinfo/Asia/Ho_Chi_Minh "$rootfs/etc/localtime"
    printf "%s\n" "LANG=C.UTF-8" > "$rootfs/etc/locale.conf"

    # Do not publish generated host keys, Wi-Fi profiles, Tailscale identity,
    # or histories from a reused staging tree. The outer build starts from a
    # fresh archive; these removals are a final defense-in-depth check.
    rm -f "$rootfs"/etc/ssh/ssh_host_*_key "$rootfs"/etc/ssh/ssh_host_*_key.pub
    find "$rootfs/etc/NetworkManager/system-connections" -mindepth 1 -maxdepth 1 \
      -exec rm -rf -- {} + 2>/dev/null || true
    rm -f "$rootfs/etc/wpa_supplicant/wpa_supplicant.conf"
    rm -rf "$rootfs/var/lib/tailscale"
    # Remove SSH state for every account and every depth, not just the stock
    # ALARM home. The public installer image is always a clean seed.
    for home_root in "$rootfs/home" "$rootfs/root"; do
      if [[ -d "$home_root" ]]; then
        find "$home_root" -mindepth 1 -name .ssh\* -prune \
          -exec rm -rf -- {} + || {
            echo "could not remove SSH material under $home_root" >&2
            exit 1
          }
      fi
    done
    rm -f "$rootfs"/home/alarm/.bash_history "$rootfs"/root/.bash_history

    # NetworkManager owns networking on the installed system. Disable the
    # generic networkd preset instead of allowing two competing managers.
    for unit in \
      systemd-networkd.service systemd-networkd.socket \
      systemd-network-generator.service systemd-networkd-wait-online.service \
      systemd-networkd-wait-online@.service NetworkManager-wait-online.service; do
      systemctl --root="$rootfs" disable "$unit" >/dev/null 2>&1 || true
      rm -f "$rootfs/etc/systemd/system/multi-user.target.wants/$unit" \
        "$rootfs/etc/systemd/system/sysinit.target.wants/$unit" \
        "$rootfs/etc/systemd/system/sockets.target.wants/$unit" \
        "$rootfs/etc/systemd/system/network-online.target.wants/$unit"
    done
    for unit in systemd-networkd.service systemd-networkd.socket systemd-network-generator.service; do
      ln -sfn /dev/null "$rootfs/etc/systemd/system/$unit"
    done
    rm -f "$rootfs/etc/systemd/system/dbus-org.freedesktop.network1.service"
    systemctl --root="$rootfs" enable sshd.service NetworkManager.service \
      systemd-resolved.service >/dev/null
    systemctl --root="$rootfs" disable NetworkManager-wait-online.service >/dev/null 2>&1 || true

    # Generate throw-away keys only to validate sshd configuration, then
    # remove them so the first boot creates device-unique host keys.
    target /usr/bin/ssh-keygen -A
    target /usr/bin/sshd -t -f /etc/ssh/sshd_config
    rm -f "$rootfs"/etc/ssh/ssh_host_*_key "$rootfs"/etc/ssh/ssh_host_*_key.pub
    target /usr/bin/visudo -c
    target /usr/bin/passwd -S root | grep -q "^root L "
    target /usr/bin/pacman -Q openssh networkmanager sudo >/dev/null
    echo "Enabled first-boot NetworkManager, systemd-resolved, and password-authenticated sshd."
    echo "Root and ALARM bootstrap passwords are locked; install will create a fresh account."
    echo "No private Wi-Fi, SSH, account, or Tailscale state was imported."
  '
