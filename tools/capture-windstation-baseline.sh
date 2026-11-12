#!/usr/bin/env bash
# Read-only state snapshot; this script does not write to the target device.
set -euo pipefail

host="${1:-windstation}"
ssh "$host" /bin/bash -s <<'REMOTE'
set -u
printf '%s\n' '=== identity ==='
printf 'model: '
tr -d '\0' < /sys/firmware/devicetree/base/model 2>/dev/null || true
printf '\n'
cat /etc/os-release
printf 'kernel: '; uname -a
printf '\n%s\n' '=== memory and swap ==='
uptime
free -h
swapon --show --bytes 2>/dev/null || true
printf '\n%s\n' '=== root boot contract (filtered kernel args only) ==='
printf 'kernel: '; uname -r
printf 'mounted root: '; findmnt -n -o SOURCE,FSTYPE /
tr ' ' '\n' </proc/cmdline | grep -E '^(root=|rootflags=|rootfstype=|rootwait$)' || true
printf '\n%s\n' '=== root and block layout ==='
findmnt -n -o TARGET,SOURCE,FSTYPE,OPTIONS /
df -h /
lsblk -o NAME,TYPE,SIZE,FSTYPE,LABEL,PARTLABEL,MOUNTPOINTS
printf '\n%s\n' '=== running services ==='
systemctl list-units --type=service --state=running --no-legend --no-pager
printf '\n%s\n' '=== largest processes (KiB; PSS may be unavailable for protected processes) ==='
printf '%-8s %-22s %10s %10s\n' PID COMMAND RSS_KiB PSS_KiB
ps -eo pid=,comm=,rss= --sort=-rss | head -n 20 | while read -r pid command rss; do
    pss="$(awk '/^Pss:/ { total += $2 } END { if (NR) print total }' "/proc/$pid/smaps_rollup" 2>/dev/null || true)"
    [[ -n "$pss" ]] || pss=n/a
    printf '%-8s %-22s %10s %10s\n' "$pid" "$command" "$rss" "$pss"
done
REMOTE
