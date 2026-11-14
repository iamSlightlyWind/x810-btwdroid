#!/usr/bin/env python3
"""Static safety and GNOME auto-rotation contract for the X810 SSC stack."""

from pathlib import Path
import hashlib
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "packages/x810-device-support/files"
PACKAGE = ROOT / "packages/x810-device-support"


def read(relative: str) -> str:
    return (FILES / relative).read_text(encoding="utf-8")


class SensorStackTests(unittest.TestCase):
    def test_android_logical_partition_mapping_is_verified_read_only(self):
        helper = read("usr/libexec/gts9wifi-android-parts")
        self.assertIn('["dmsetup", "--readonly", "create", map_name', helper)
        self.assertIn('ro.stdout.strip() != "1"', helper)
        self.assertIn('"/dev/disk/by-partlabel/super"', helper)

    def test_all_android_mounts_are_read_only(self):
        self.assertIn("Options=ro", read("usr/lib/systemd/system/vendor.mount"))
        self.assertIn("Options=ro", read("usr/lib/systemd/system/vendor-firmware_mnt.mount"))
        self.assertIn("Options=ro,noload", read("usr/lib/systemd/system/vendor-dsp.mount"))
        persist = read("usr/lib/systemd/system/mnt-vendor-persist.mount")
        self.assertIn("Options=ro,noload,nosuid,nodev,noexec", persist)
        self.assertNotRegex(persist, r"(?m)^Options=.*\brw\b")

    def test_late_adsp_sensor_stack_and_timer_do_not_gate_boot(self):
        timer = read("usr/lib/systemd/system/gts9wifi-wait-sensor-proxy.timer")
        service = read("usr/lib/systemd/system/gts9wifi-wait-sensor-proxy.service")
        adsp = read("usr/lib/systemd/system/gts9wifi-adsp-boot.service")
        self.assertIn("OnBootSec=15s", timer)
        self.assertIn("After=display-manager.service", service)
        self.assertIn("RequiresMountsFor=/vendor /vendor/firmware_mnt /vendor/dsp /mnt/vendor/persist", service)
        self.assertLess(service.index("RequiresMountsFor="), service.index("[Service]"))
        self.assertIn("ExecStartPre=/bin/sleep 25", adsp)
        self.assertIn("Requires=vendor-firmware_mnt.mount", adsp)
        self.assertIn("Wants=hexagonrpcd-adsp-sensorspd.service", service)
        sensorpd = read("etc/systemd/system/hexagonrpcd-adsp-sensorspd.service.d/10-gts9wifi-hexagonfs.conf")
        self.assertRegex(sensorpd, r"(?m)^Requires=.*\bpd-mapper\.service\b")
        self.assertIn("Restart=no", sensorpd)

    def test_ssc_accelerometer_is_exposed_to_standard_sensor_proxy_api(self):
        rules = read("usr/lib/udev/rules.d/61-gts9wifi-sensor-mount-matrix.rules")
        self.assertIn('ENV{IIO_SENSOR_PROXY_TYPE}+="ssc-accel"', rules)
        self.assertIn('ENV{ACCEL_MOUNT_MATRIX}="0,1,0;-1,0,0;0,0,1"', rules)
        self.assertTrue((FILES / "usr/libexec/iio-sensor-proxy").is_file())
        service = read("usr/lib/systemd/system/iio-sensor-proxy.service")
        self.assertIn("BusName=net.hadess.SensorProxy", service)
        self.assertTrue((FILES / "usr/share/dbus-1/system-services/net.hadess.SensorProxy.service").is_file())

    def test_package_replaces_generic_proxy_with_ssc_backend(self):
        pkgbuild = (ROOT / "packages/x810-device-support/PKGBUILD").read_text(encoding="utf-8")
        self.assertIn("arch=('aarch64')", pkgbuild)
        self.assertIn("provides=('iio-sensor-proxy=3.9')", pkgbuild)
        self.assertIn("conflicts=('iio-sensor-proxy' 'libssc')", pkgbuild)
        self.assertIn("replaces=('iio-sensor-proxy' 'libssc')", pkgbuild)
        self.assertIn("LICENSE.qcom.txt", pkgbuild)
        self.assertIn("'device-mapper'", pkgbuild)
        for executable in ("hexagonrpcd", "pd-mapper", "ssccli", "monitor-sensor"):
            self.assertTrue((FILES / f"usr/bin/{executable}").is_file(), executable)
        for library in ("libssc.so.2", "libhexagonrpc.so.0.4", "libqrtr.so.1"):
            self.assertTrue((FILES / f"usr/lib/{library}").exists(), library)

    def test_sensor_runtime_artifacts_match_the_reviewed_hash_lock(self):
        lock = ROOT / "packages/x810-device-support/SENSOR-SOURCES.lock"
        for line in lock.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) != 2 or not fields[0].startswith(("usr/", "licenses/")):
                continue
            path, expected = fields
            base = FILES if path.startswith("usr/") else PACKAGE
            actual = hashlib.sha256((base / path).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, path)
        for relative in ("usr/bin/hexagonrpcd", "usr/bin/pd-mapper", "usr/bin/ssccli",
                         "usr/bin/monitor-sensor", "usr/libexec/iio-sensor-proxy"):
            elf = (FILES / relative).read_bytes()
            self.assertEqual(elf[:4], b"\x7fELF", relative)
            self.assertEqual(elf[4], 2, relative)  # ELFCLASS64
            self.assertEqual(int.from_bytes(elf[18:20], "little"), 183, relative)  # EM_AARCH64

    def test_profile_enables_only_deferred_sensor_recovery(self):
        profile = (ROOT / "tools/install-gnome-profile.sh").read_text(encoding="utf-8")
        self.assertIn("gts9wifi-wait-sensor-proxy.timer", profile)
        self.assertNotIn('enable gts9wifi-adsp-boot.service', profile)
        self.assertNotIn('enable hexagonrpcd-adsp-sensorspd.service', profile)
        self.assertIn("Android persist must be mounted read-only", profile)

    def test_package_upgrade_enables_sensor_units_for_existing_installs(self):
        hook = (ROOT / "packages/x810-device-support/x810-device-support.install").read_text(encoding="utf-8")
        self.assertIn("post_upgrade()", hook)
        self.assertIn("systemctl --root=/ enable", hook)
        self.assertIn("gts9wifi-wait-sensor-proxy.timer", hook)
        self.assertNotIn("--now", hook)


if __name__ == "__main__":
    unittest.main()
