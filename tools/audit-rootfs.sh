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
    docs="$project/docs"
    release=7.2.0-gts9wifi
    profile=ssh-first
    profile_file="$rootfs/etc/windstation-arch-profile"
    if [[ -f "$profile_file" ]]; then
      profile_count="$(grep -c "^profile=" "$profile_file" || true)"
      [[ "$profile_count" == 1 ]] || { echo "invalid Windstation profile marker" >&2; exit 1; }
      profile="$(sed -n "s/^profile=//p" "$profile_file")"
    fi
    [[ "$profile" == ssh-first || "$profile" == gnome ]] || {
      echo "unknown Arch rootfs profile: $profile" >&2
      exit 1
    }
    proot=(/opt/proot/src/proot -0 -q /usr/bin/qemu-aarch64-static \
      -r "$rootfs" -w / -b /dev -b /proc -b /sys -b /tmp)
    target() { "${proot[@]}" "$@"; }

    target /usr/bin/pacman -Q > "$docs/ARCH-ROOTFS-PACKAGES.txt"
    systemctl --root="$rootfs" list-unit-files --state=enabled --no-pager \
      > "$docs/ARCH-ROOTFS-ENABLED-UNITS.txt"

    # Hard assertions for the selected profile. None of these reads a secret.
    ! target /usr/bin/pacman -Q linux-aarch64 >/dev/null 2>&1
    target /usr/bin/pacman -Q x810-device-support networkmanager tailscale \
      zram-generator openssh >/dev/null
    if [[ "$profile" == gnome ]]; then
      target /usr/bin/pacman -Q gdm gnome-shell gnome-session \
        gnome-control-center gnome-terminal brave-bin bluez bluez-utils \
        pipewire-jack noto-fonts tab-companion >/dev/null
      for helper in \
        "$rootfs/usr/local/libexec/x810-boot-switch-core" \
        "$rootfs/usr/local/libexec/tab-companion-boot-status" \
        "$rootfs/usr/local/libexec/tab-companion-boot-switch"; do
        [[ -x "$helper" ]] || { echo "Missing Arch dualboot helper: $helper" >&2; exit 1; }
      done
      for path in \
        "$rootfs/usr/libexec/tab-companion-admin" \
        "$rootfs/usr/share/polkit-1/actions/io.github.agcarbajo.TabCompanion.Admin.policy" \
        "$rootfs/usr/share/polkit-1/actions/io.github.agcarbajo.TabCompanion.X810.policy" \
        "$rootfs/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/extension.js" \
        "$rootfs/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json"; do
        [[ -s "$path" ]] || { echo "Missing Arch dualboot integration file: $path" >&2; exit 1; }
      done
      grep -q archarm "$rootfs/usr/local/libexec/x810-boot-switch-core"
      grep -q "\"51\"" "$rootfs/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io/metadata.json"
      for package in gnome-console gnome-boxes gnome-books; do
        if target /usr/bin/pacman -Q "$package" >/dev/null 2>&1; then
          echo "optional GNOME app unexpectedly installed in minimal profile: $package" >&2
          exit 1
        fi
      done
      [[ "$(systemctl --root="$rootfs" is-enabled gdm.service)" == enabled ]]
      [[ "$(systemctl --root="$rootfs" get-default)" == graphical.target ]]
      [[ -f "$rootfs/usr/lib/systemd/system/gdm.service" ]]
      [[ -f "$rootfs/usr/lib/systemd/system/bluetooth.service" ]]
      [[ -L "$rootfs/etc/systemd/system/display-manager.service" ]]
      [[ -L "$rootfs/etc/systemd/system/default.target" ]]
      [[ "$(systemctl --root="$rootfs" is-enabled bluetooth.service)" == enabled ]]
      grep -qx AutoEnable=true "$rootfs/etc/bluetooth/main.conf"
    else
      for package in gdm gnome-shell tab-companion; do
        if target /usr/bin/pacman -Q "$package" >/dev/null 2>&1; then
          echo "desktop package unexpectedly installed in ssh-first profile: $package" >&2
          exit 1
        fi
      done
      [[ "$(systemctl --root="$rootfs" is-enabled gdm.service 2>/dev/null || true)" != enabled ]]
    fi
    python3 "$project/tools/configure-target-pacman.py" --check "$rootfs/etc/pacman.conf"
    target /usr/bin/sshd -t -f /etc/ssh/sshd_config
    ssh_effective="$(target /usr/bin/sshd -T -f /etc/ssh/sshd_config \
      -C user=slightlywind,host=localhost,addr=127.0.0.1)"
    grep -iFxq "authenticationmethods publickey" <<< "$ssh_effective"
    grep -iFxq "pubkeyauthentication yes" <<< "$ssh_effective"
    grep -iFxq "passwordauthentication no" <<< "$ssh_effective"
    grep -iFxq "kbdinteractiveauthentication no" <<< "$ssh_effective"
    grep -iFxq "permitrootlogin no" <<< "$ssh_effective"
    grep -iFxq "allowusers slightlywind" <<< "$ssh_effective"
    target /usr/bin/ssh-keygen -l -f /home/slightlywind/.ssh/authorized_keys >/dev/null
    root_status="$(target /usr/bin/passwd -S root)"
    read -r root_account root_lock_state _ <<< "$root_status"
    [[ "$root_account" == root && "$root_lock_state" == L ]]
    [[ "$(stat -c %u:%g:%a "$rootfs/etc/sudoers.d/40-windstation")" == 0:0:440 ]]
    [[ "$(stat -c %u:%g:%a "$rootfs/home/slightlywind/.ssh/authorized_keys")" == 1000:1000:600 ]]
    target /usr/bin/visudo -c
    [[ -f "$rootfs/usr/lib/modules/$release/modules.dep" ]]
    [[ -f "$rootfs/usr/lib/firmware/ath11k/WCN6855/hw2.1/board-2.bin" ]]
    [[ -f "$rootfs/var/lib/tailscale/tailscaled.state" ]]
    [[ "$(stat -c %a "$rootfs/var/lib/tailscale/tailscaled.state")" == 600 ]]
    [[ "$(find "$rootfs/etc/NetworkManager/system-connections" -maxdepth 1 -type f -name "*.nmconnection" | wc -l)" == 1 ]]
    [[ "$(stat -c %a "$(find "$rootfs/etc/NetworkManager/system-connections" -maxdepth 1 -type f -name "*.nmconnection" | head -n1)")" == 600 ]]
    grep -q "PARTLABEL=linuxroot" "$rootfs/etc/fstab"
    grep -q "PARTLABEL=Swap" "$rootfs/etc/fstab"
    grep -q "AuthenticationMethods publickey" "$rootfs/etc/ssh/sshd_config.d/90-windstation.conf"
    grep -q "PasswordAuthentication no" "$rootfs/etc/ssh/sshd_config.d/90-windstation.conf"
    [[ "$(systemctl --root="$rootfs" is-enabled sshd.service)" == enabled ]]
    [[ "$(systemctl --root="$rootfs" is-enabled NetworkManager.service)" == enabled ]]
    [[ "$(systemctl --root="$rootfs" is-enabled tailscaled.service)" == enabled ]]
    [[ "$(systemctl --root="$rootfs" is-enabled x810-thermal-limit.service 2>/dev/null || true)" != enabled ]]
    [[ "$(systemctl --root="$rootfs" is-enabled systemd-networkd.service 2>/dev/null || true)" != enabled ]]
    [[ "$(systemctl --root="$rootfs" is-enabled systemd-networkd-wait-online.service 2>/dev/null || true)" != enabled ]]
    [[ "$(systemctl --root="$rootfs" is-enabled NetworkManager-wait-online.service 2>/dev/null || true)" != enabled ]]
    [[ ! -e "$rootfs/etc/systemd/system/multi-user.target.wants/systemd-networkd.service" ]]
    [[ ! -e "$rootfs/etc/systemd/system/network-online.target.wants/NetworkManager-wait-online.service" ]]
    for unit in \
      systemd-networkd.service systemd-networkd.socket \
      systemd-network-generator.service \
      systemd-networkd-resolve-hook.socket \
      systemd-networkd-varlink.socket \
      systemd-networkd-varlink-metrics.socket; do
      [[ "$(readlink "$rootfs/etc/systemd/system/$unit")" == /dev/null ]]
    done
    if find "$rootfs/usr/lib/systemd/system" -maxdepth 1 -name "gts9wifi-*.service" -print -quit | grep -q .; then
      echo "Unexpected Fedora X810 service in rootfs" >&2
      exit 1
    fi

    module_source_digest="$(grep source_tree_sha256 "$docs/X810-MODULES.lock" | cut -d= -f2)"
    module_payload_digest="$(cd "$rootfs/usr/lib/modules/$release" && find . -type f -name "*.ko*" -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64)"
    firmware_dir="$rootfs/usr/lib/firmware/ath11k/WCN6855/hw2.1"
    cat > "$docs/ARCH-ROOTFS-AUDIT.txt" <<EOF
Arch Linux ARM Windstation rootfs audit
Captured: $(date -u +%F) UTC
Target: SM-X810 / gts9pwifi / PARTLABEL=linuxroot
Profile: $profile
Base input: signed Arch Linux ARM generic AArch64 bootstrap (docs/ALARM-ROOTFS.lock)
Kernel: external active X810 kernel $release; generic linux-aarch64 package absent
Installed packages: docs/ARCH-ROOTFS-PACKAGES.txt
Enabled unit files: docs/ARCH-ROOTFS-ENABLED-UNITS.txt
Root filesystem size: $(du -sh "$rootfs" | cut -f1)
Installed package count: $(wc -l < "$docs/ARCH-ROOTFS-PACKAGES.txt")
Matching kernel module objects: $(find "$rootfs/usr/lib/modules/$release" -type f -name "*.ko*" | wc -l)
Read-only source module-tree digest (all $(( $(find "$project/cache/modules/$release" -type f | wc -l) )) files): $module_source_digest
Installed kernel module payload digest (*.ko* list): $module_payload_digest
WCN6855 amss.bin SHA-256: $(sha256sum "$firmware_dir/amss.bin" | cut -d" " -f1)
WCN6855 m3.bin SHA-256: $(sha256sum "$firmware_dir/m3.bin" | cut -d" " -f1)
WCN6855 board-2.bin SHA-256: $(sha256sum "$firmware_dir/board-2.bin" | cut -d" " -f1)
Active Wi-Fi profile and Tailscale state: staged privately under work/rootfs; values intentionally not recorded here.
Account/SSH policy: root locked; slightlywind uid 1000; effective sshd policy is public-key-only, password/root login disabled, and limited to slightlywind; sudoers and authorized-key ownership/modes validated.
Validation: pacman database, sshd -t and -T, visudo -c, package/service assertions, module and firmware paths, and fstab checks passed.
Desktop: $(if [[ "$profile" == gnome ]]; then echo "GNOME Shell and GDM installed; display-manager.service aliases GDM; graphical.target default; Tab Companion installed."; else echo "SSH-first only; GNOME, GDM and Tab Companion not installed."; fi)
Pacman sandbox: filesystem sandbox disabled for the X810 kernel (no Landlock); syscall sandbox remains enabled.
Device interaction: this audit reads only the staged local rootfs; it does not access or modify Windstation.
EOF
    cat "$docs/ARCH-ROOTFS-AUDIT.txt"
  '
