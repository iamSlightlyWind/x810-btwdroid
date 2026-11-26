#!/usr/bin/env bash
# Build the pinned, distro-neutral X810 kernel source for the Arch release.
# This intentionally does not depend on x810-fedroid's rolling GitHub release
# assets or Fedora rootfs job; the boot bundle and module tree are built here.
set -euo pipefail
umask 022

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
output_dir="${1:-$project_dir/out/kernel-build}"
[[ "$output_dir" == /* ]] || output_dir="$project_dir/$output_dir"
lock="$project_dir/kernel/SOURCE.lock"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ -f "$lock" && ! -L "$lock" ]] || die "missing/unsafe kernel source lock: $lock"
[[ "$output_dir" == "$project_dir/"* ]] || die "kernel output must remain under this repository"

declare -A cfg=()
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  [[ -n "${line//[[:space:]]/}" ]] || continue
  key="${line%%=*}"; value="${line#*=}"
  [[ "$key" != "$line" && -n "$key" && -n "$value" && -z "${cfg[$key]+x}" ]] \
    || die "invalid/duplicate kernel source lock entry: $line"
  cfg[$key]="$value"
done < "$lock"
for key in kernel_repository kernel_commit firmware_repository firmware_commit kernel_release \
           linux_source_url linux_source_sha256 fedora_base_compose fedora_updates_compose; do
  [[ -n "${cfg[$key]:-}" ]] || die "kernel source lock is missing $key"
done
[[ "${cfg[kernel_commit]}" =~ ^[0-9a-f]{40}$ ]] || die "invalid pinned X810 kernel source commit"
[[ "${cfg[firmware_commit]}" =~ ^[0-9a-f]{40}$ ]] || die "invalid pinned X810 firmware commit"
[[ "${cfg[linux_source_sha256]}" =~ ^[0-9a-f]{64}$ ]] || die "invalid Linux source checksum"

for command in git docker rpm2cpio cpio python3 sha256sum tar; do
  command -v "$command" >/dev/null 2>&1 || die "required kernel build tool is missing: $command"
done

cache="$project_dir/cache/kernel-build"
mkdir -p "$cache/sources" "$cache/ccache" "$cache/dnf" "$output_dir"
kernel_source="$cache/sources/x810-fedroid-${cfg[kernel_commit]}"
firmware_source="$cache/sources/x810-firmware-${cfg[firmware_commit]}"
fetch_pinned_repo() {
  local url="$1" commit="$2" destination="$3"
  if [[ ! -d "$destination/.git" ]]; then
    git clone --filter=blob:none --no-checkout "$url" "$destination"
  fi
  git -C "$destination" fetch --depth=1 origin "$commit"
  git -C "$destination" checkout --detach FETCH_HEAD
  [[ "$(git -C "$destination" rev-parse HEAD)" == "$commit" ]] \
    || die "checkout does not match pinned source commit: $destination"
}
fetch_pinned_repo "${cfg[kernel_repository]}" "${cfg[kernel_commit]}" "$kernel_source"
fetch_pinned_repo "${cfg[firmware_repository]}" "${cfg[firmware_commit]}" "$firmware_source"

mkdir -p "$output_dir/prepared"
docker run --rm \
  -e KVER="${cfg[kernel_release]}" \
  -e FEDORA_BASE_COMPOSE="${cfg[fedora_base_compose]}" \
  -e FEDORA_UPDATES_COMPOSE="${cfg[fedora_updates_compose]}" \
  -e LINUX_SOURCE_URL="${cfg[linux_source_url]}" \
  -e LINUX_SOURCE_SHA256="${cfg[linux_source_sha256]}" \
  -e KERNEL_SOURCE_COMMIT="${cfg[kernel_commit]}" \
  -e CCACHE_DIR=/x810-cache/ccache -e CCACHE_COMPILERCHECK=content -e CCACHE_MAXSIZE=6G \
  -v "$kernel_source:/upstream:ro" \
  -v "$firmware_source:/firmware-source:ro" \
  -v "$project_dir/tools/apply-arm64-u128-backport.py:/x810-tools/apply-arm64-u128-backport.py:ro" \
  -v "$project_dir/tools/verify-x810-arch-kernel-payload.py:/x810-tools/verify-x810-arch-kernel-payload.py:ro" \
  -v "$cache:/x810-cache:rw" \
  -v "$output_dir:/kernel-output:rw" \
  quay.io/fedora/fedora:44 bash -lc '
    set -euxo pipefail
    repo_root=https://kojipkgs.fedoraproject.org/compose
    [[ "$FEDORA_BASE_COMPOSE" =~ ^Fedora-44-[0-9]{8}\.[0-9]+$ ]]
    [[ "$FEDORA_UPDATES_COMPOSE" =~ ^Fedora-44-updates-[0-9]{8}\.[0-9]+$ ]]
    base_url="$repo_root/44/$FEDORA_BASE_COMPOSE/compose/Everything/aarch64/os/"
    updates_url="$repo_root/updates/$FEDORA_UPDATES_COMPOSE/compose/Everything/aarch64/os/"
    repo_args=(--disablerepo="*" \
      --repofrompath=x810-fedora-snapshot,"$base_url" \
      --repofrompath=x810-updates-snapshot,"$updates_url" \
      --setopt=cachedir=/x810-cache/dnf --setopt=system_cachedir=/x810-cache/dnf \
      --setopt=keepcache=True --setopt=x810-fedora-snapshot.gpgcheck=1 \
      --setopt=x810-updates-snapshot.gpgcheck=1 \
      --enablerepo=x810-fedora-snapshot --enablerepo=x810-updates-snapshot)
    mkdir -p /x810-cache/dnf
    dnf -y "${repo_args[@]}" install make gcc clang lld llvm bc flex bison perl git \
      openssl openssl-devel elfutils-libelf-devel python3 tar xz zstd rpm-build \
      ccache dtc findutils dwarves dracut cpio lz4 iproute gzip >/dev/null
    mkdir -p /x810-cache/ccache-bin /x810-cache
    ln -sf "$(command -v ccache)" /x810-cache/ccache-bin/clang
    export PATH="/x810-cache/ccache-bin:$PATH"
    source_tar=/x810-cache/linux-7.2.tar.xz
    if [ ! -s "$source_tar" ] || [ "$(sha256sum "$source_tar" | cut -d" " -f1)" != "$LINUX_SOURCE_SHA256" ]; then
      curl -sfL "$LINUX_SOURCE_URL" -o "$source_tar.partial"
      echo "$LINUX_SOURCE_SHA256  $source_tar.partial" | sha256sum -c -
      mv "$source_tar.partial" "$source_tar"
    fi
    echo "$LINUX_SOURCE_SHA256  $source_tar" | sha256sum -c -
    mkdir -p /tmp/x810-build && cd /tmp/x810-build
    tar xf "$source_tar"
    cd linux-7.2
    export SOURCE_DATE_EPOCH=0 KBUILD_BUILD_TIMESTAMP="1970-01-01 00:00:00 UTC"
    export KBUILD_BUILD_USER=x810-reproducible KBUILD_BUILD_HOST=x810-reproducible LC_ALL=C
    python3 /upstream/tools/test-dpu-color-resource-modeset.py \
      drivers/gpu/drm/msm/disp/dpu1/dpu_crtc.c drivers/gpu/drm/msm/msm_atomic.c
    python3 /upstream/tools/test-drm-bridge-oob-hotplug.py \
      drivers/gpu/drm/display/drm_bridge_connector.c
    python3 /upstream/tools/test-x810-pps-refresh-timing.py
    bash /upstream/kernel/prepare.sh .
    python3 /x810-tools/apply-arm64-u128-backport.py tools/include/linux/types.h
    echo "-gts9wifi" > localversion-gts9wifi
    cd ..
    mv linux-7.2 linux-prepared
    tar --sort=name --mtime="@0" --owner=0 --group=0 --numeric-owner \
      --format=gnu -cf - linux-prepared | gzip -n -9 > linux-prepared.tar.gz
    mkdir -p ~/rpmbuild/SOURCES /kernel-output/boot
    cp linux-prepared.tar.gz ~/rpmbuild/SOURCES/
    rpmbuild -bb --define "kversion 7.2.0" /upstream/kernel/kernel.spec
    rpms=(~/rpmbuild/RPMS/aarch64/linux-x810-*.rpm)
    [ "${#rpms[@]}" -eq 1 ] || { echo "expected one X810 kernel RPM" >&2; exit 1; }
    cp "${rpms[0]}" /kernel-output/kernel.rpm
    dnf -y "${repo_args[@]}" install "${rpms[0]}"
    # Only firmware required before linuxroot mounts is put in vendor_boot;
    # the Arch rootfs and Android vendor mounts supply runtime firmware.
    mkdir -p /usr/lib/firmware
    for component in cirrus qca qca6490 qcom; do
      cp -a "/firmware-source/$component" /usr/lib/firmware/
    done
    python3 /upstream/tools/x810-gpu-firmware.py stage \
      --source /upstream/firmware/x810-cyg1 --dest /usr/lib/firmware/qcom
    python3 /upstream/tools/x810-vpu-firmware.py stage \
      --source /upstream/firmware/x810-vpu-cyg1/vpu30_4v.mbn \
      --dest /usr/lib/firmware/qcom/vpu
    cp -a /upstream/boot/dracut/90gts9wifi-usbnet /usr/lib/dracut/modules.d/
    cp /upstream/boot/dracut/dracut.conf.d/gts9wifi.conf /usr/lib/dracut/dracut.conf.d/
    dracut --kver "$KVER" --force /tmp/initramfs.img
    bash /upstream/boot/build-bundle.sh \
      --vmlinuz "/boot/vmlinuz-$KVER" \
      --dtb /boot/dtbs-7.2.0-gts9wifi/qcom/sm8550-samsung-gts9wifi.dtb \
      --initramfs /tmp/initramfs.img --cmdline /upstream/boot/cmdline.txt \
      --bootconfig /upstream/boot/bootconfig.txt --out /kernel-output/boot
    python3 /x810-tools/verify-x810-arch-kernel-payload.py \
      "/boot/vmlinuz-$KVER" /upstream/kernel/files/samsung_stm32_pogo.c \
      /upstream/boot/extract-zboot-payload.py
    python3 /upstream/tools/x810-gpu-firmware.py check-vendor-boot /kernel-output/boot/vendor_boot.img
    ccache --show-stats
  '

root="$output_dir/prepared"
mkdir -p "$root/usr/lib/modules" "$root/boot"
rpm2cpio "$output_dir/kernel.rpm" | (cd "$root" && cpio -idm --quiet --no-absolute-filenames)
for name in boot init_boot vendor_boot dtbo; do
  cp -- "$output_dir/boot/$name.img" "$root/boot/$name.img"
done
python3 - "$project_dir/tools/fetch-x810-kernel.py" "$output_dir/kernel.rpm" \
  "${cfg[kernel_commit]}" "$root" "$output_dir/kernel.json" <<'PY'
import hashlib
import importlib.util
import sys
from pathlib import Path

tool_path, rpm_arg, source_commit, root_arg, receipt_arg = sys.argv[1:]
spec = importlib.util.spec_from_file_location("fetch_x810_kernel", tool_path)
if spec is None or spec.loader is None:
    raise SystemExit("could not load X810 kernel receipt verifier")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
rpm, root, receipt_path = Path(rpm_arg), Path(root_arg), Path(receipt_arg)
boot = root / "boot"
boot_assets = {
    name: {"sha256": tool.sha256_file(boot / f"{name}.img"),
           "size_bytes": (boot / f"{name}.img").stat().st_size}
    for name in tool.BOOT_IMAGE_SIZES
}
release = {"tag_name": f"x810-fedora-source-{source_commit[:12]}"}
manifest = {"source_commit": source_commit}
asset = {"sha256": tool.sha256_file(rpm), "size_bytes": rpm.stat().st_size}
tool.write_kernel_receipt(receipt_path, release, manifest, asset,
                          root / "usr/lib/modules" / tool.KERNEL_RELEASE, boot_assets)
PY
python3 "$project_dir/tools/fetch-x810-kernel.py" --receipt "$output_dir/kernel.json" \
  --prepared-root "$root" --verify-prepared
mkdir -p "$output_dir/transfer"
cp -- "$output_dir/kernel.json" "$output_dir/transfer/kernel.json"
tar -C "$root/usr/lib/modules" -czf "$output_dir/transfer/modules.tar.gz" "${cfg[kernel_release]}"
tar -C "$root" -czf "$output_dir/transfer/boot-images.tar.gz" boot
(cd "$output_dir/transfer" && sha256sum kernel.json modules.tar.gz boot-images.tar.gz > SHA256SUMS)
echo "Built verified X810 kernel and boot set from ${cfg[kernel_commit]}."
