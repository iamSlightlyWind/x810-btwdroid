#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(cd -- "$script_dir/.." && pwd)"
workspace_dir="$(cd -- "$project_dir/.." && pwd)"
podman_root="${PODMAN_ROOT_OVERRIDE:-$project_dir/tmp/podman-root}"
podman_runroot="${PODMAN_RUNROOT_OVERRIDE:-$project_dir/tmp/podman-run}"
image="localhost/windstation-arch-builder:2026-11-11"
rootfs="$project_dir/work/rootfs"
authorized_keys="$project_dir/cache/ssh-authorized_keys"

[[ -s "$authorized_keys" ]] || { echo "Missing cached SSH public keys: $authorized_keys" >&2; exit 1; }
[[ -d "$rootfs/etc" ]] || { echo "Missing target rootfs: $rootfs" >&2; exit 1; }
mkdir -p "$podman_root" "$podman_runroot"

podman --root "$podman_root" --runroot "$podman_runroot" --storage-driver=vfs \
  run --rm --security-opt label=disable \
  --volume "$workspace_dir:/workspace:rw" --workdir /workspace \
  "$image" -lc '
    set -euo pipefail
    project=/workspace/x810-btwdroid
    rootfs="$project/work/rootfs"
    user=slightlywind
    tailscale_state="$rootfs/var/lib/tailscale/tailscaled.state"
    nm_connections="$rootfs/etc/NetworkManager/system-connections"
    [[ -s "$tailscale_state" && "$(stat -c %a "$tailscale_state")" == 600 \
      && "$(stat -c %u:%g "$tailscale_state")" == 0:0 ]] || {
      echo "Refusing to enable tailscaled without the imported root-owned mode-600 state" >&2
      exit 1
    }
    profile_count="$(find "$nm_connections" -maxdepth 1 -type f -name "*.nmconnection" | wc -l)"
    [[ "$profile_count" == 1 ]] || {
      echo "Expected one imported NetworkManager profile before configuring first-boot access" >&2
      exit 1
    }
    nm_profile="$(find "$nm_connections" -maxdepth 1 -type f -name "*.nmconnection" -print -quit)"
    [[ "$(stat -c %a "$nm_profile")" == 600 && "$(stat -c %u:%g "$nm_profile")" == 0:0 ]] || {
      echo "Refusing profile with unexpected owner/mode" >&2
      exit 1
    }
    proot=(/opt/proot/src/proot -0 -q /usr/bin/qemu-aarch64-static \
      -r "$rootfs" -w / -b /dev -b /proc -b /sys -b /tmp)
    target() { "${proot[@]}" "$@"; }

    # Build-time SSH bootstrap used for local staging/trial connectivity. The
    # installer later discards this account and creates the prompted user.
    # Match the host SSH alias and do not retain the generic ALARM account name.
    if target /usr/bin/getent passwd alarm >/dev/null; then
      if ! target /usr/bin/getent group "$user" >/dev/null; then
        target /usr/bin/groupmod --new-name "$user" alarm
      fi
      target /usr/bin/usermod --login "$user" alarm
      target /usr/bin/usermod --home "/home/$user" --move-home "$user"
    elif ! target /usr/bin/getent passwd "$user" >/dev/null; then
      echo "Neither alarm nor $user exists in the target rootfs" >&2
      exit 1
    fi
    target /usr/bin/usermod --append --groups wheel,video,audio,input,storage "$user"
    target /usr/bin/passwd --lock root

    # Give the key-only bootstrap account a random, unrecorded password hash. SSH
    # password and keyboard-interactive auth are disabled below; wheel gets
    # passwordless sudo so the owner can administer over the authorized key.
    random_password="$(openssl rand -base64 48)"
    random_salt="$(openssl rand -hex 16)"
    password_hash="$(openssl passwd -6 -salt "$random_salt" "$random_password")"
    unset random_password random_salt
    printf "%s:%s\n" "$user" "$password_hash" | target /usr/bin/chpasswd --encrypted
    unset password_hash

    install -d -m 0700 "$rootfs/home/$user/.ssh"
    install -m 0600 "$project/cache/ssh-authorized_keys" "$rootfs/home/$user/.ssh/authorized_keys"
    target /usr/bin/chown -R "$user:$user" "/home/$user/.ssh"
    target /usr/bin/chmod 0700 "/home/$user/.ssh"
    target /usr/bin/chmod 0600 "/home/$user/.ssh/authorized_keys"

    install -d -m 0755 "$rootfs/etc/ssh/sshd_config.d" "$rootfs/etc/sudoers.d"
    cat > "$rootfs/etc/ssh/sshd_config.d/90-windstation.conf" <<EOF
PubkeyAuthentication yes
AuthenticationMethods publickey
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin no
AllowUsers $user
EOF
    cat > "$rootfs/etc/sudoers.d/40-windstation" <<EOF
$user ALL=(ALL:ALL) NOPASSWD: ALL
EOF
    chmod 0440 "$rootfs/etc/sudoers.d/40-windstation"

    cat > "$rootfs/etc/fstab" <<EOF
# Windstation (SM-X810), existing GPT labels from the read-only Fedora baseline.
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

    # The generic ALARM preset enables networkd. Use NetworkManager as the
    # single network owner; remove all networkd and NetworkManager wait-online
    # enablement links, and mask networkd service/socket activation paths.
    for unit in \
      systemd-networkd.service systemd-networkd.socket \
      systemd-network-generator.service \
      systemd-networkd-wait-online.service systemd-networkd-wait-online@.service \
      systemd-networkd-resolve-hook.socket \
      systemd-networkd-varlink.socket \
      systemd-networkd-varlink-metrics.socket \
      NetworkManager-wait-online.service; do
      systemctl --root="$rootfs" disable "$unit" >/dev/null 2>&1 || true
    done
    for unit in \
      systemd-networkd.service systemd-networkd.socket \
      systemd-network-generator.service \
      systemd-networkd-wait-online.service systemd-networkd-wait-online@.service \
      systemd-networkd-resolve-hook.socket \
      systemd-networkd-varlink.socket \
      systemd-networkd-varlink-metrics.socket; do
      for target in multi-user.target.wants sysinit.target.wants sockets.target.wants \
        network-online.target.wants; do
        rm -f "$rootfs/etc/systemd/system/$target/$unit"
      done
    done
    for unit in \
      systemd-networkd.service systemd-networkd.socket \
      systemd-network-generator.service \
      systemd-networkd-resolve-hook.socket \
      systemd-networkd-varlink.socket \
      systemd-networkd-varlink-metrics.socket; do
      ln -sfn /dev/null "$rootfs/etc/systemd/system/$unit"
    done
    for unit in systemd-networkd-wait-online.service systemd-networkd-wait-online@.service; do
      rm -f "$rootfs/etc/systemd/system/multi-user.target.wants/$unit" \
        "$rootfs/etc/systemd/system/network-online.target.wants/$unit"
    done
    rm -f "$rootfs/etc/systemd/system/dbus-org.freedesktop.network1.service"
    systemctl --root="$rootfs" enable sshd.service NetworkManager.service \
      systemd-resolved.service tailscaled.service >/dev/null
    # NetworkManager.service has an Also= relationship that re-enables its
    # wait-online helper; disable it after enabling NetworkManager itself.
    systemctl --root="$rootfs" disable NetworkManager-wait-online.service \
      >/dev/null 2>&1 || true

    # Generate unique host keys inside this local staging tree (never on
    # Windstation); sshdgenkeys.service will then be an idempotent no-op.
    target /usr/bin/ssh-keygen -A

    # Validate important offline configuration from inside the target root.
    target /usr/bin/sshd -t -f /etc/ssh/sshd_config
    target /usr/bin/visudo -c
    [[ "$(target /usr/bin/id -u "$user")" == 1000 ]]
    [[ "$(target /usr/bin/id -Gn "$user")" == *wheel* ]]
    [[ -f "$rootfs/usr/lib/modules/7.2.0-gts9wifi/modules.dep" ]]
    [[ -f "$rootfs/usr/lib/firmware/ath11k/WCN6855/hw2.1/board-2.bin" ]]

    echo "Configured Arch rootfs build-time SSH bootstrap $user; credentials were not printed."
    echo "Enabled: sshd, NetworkManager, systemd-resolved, tailscaled; generic getty, timesyncd, userdbd, and remote-fs defaults remain."
    echo "Disabled/masked: networkd service/socket/generator/sockets and wait-online. No device-specific units were enabled."
  '
