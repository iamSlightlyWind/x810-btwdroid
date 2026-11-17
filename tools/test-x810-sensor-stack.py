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
    def test_x810_audio_profile_and_wireplumber_routing_are_packaged(self):
        pkgbuild = (PACKAGE / "PKGBUILD").read_text(encoding="utf-8")
        for dependency in ("alsa-ucm-conf", "pipewire", "pipewire-audio", "pipewire-alsa",
                          "pipewire-pulse", "wireplumber", "alsa-utils"):
            self.assertIn(f"'{dependency}'", pkgbuild)
        profile = read("usr/share/wireplumber/wireplumber.conf.d/90-x810-audio-routing.conf")
        self.assertIn("monitor.v4l2 = disabled", profile)
        self.assertIn('device.name = "alsa_card.comprC0"', profile)
        card = read("usr/share/alsa/ucm2/Qualcomm/sm8550/GTS9/Samsung-Galaxy-Tab-S9.conf")
        hifi = read("usr/share/alsa/ucm2/Qualcomm/sm8550/GTS9/HiFi.conf")
        self.assertIn('File "/Qualcomm/sm8550/GTS9/HiFi.conf"', card)
        self.assertIn('PlaybackPCM "hw:${CardId},0"', hifi)
        self.assertTrue((FILES / "usr/share/alsa/ucm2/conf.d/sm8550/Samsung-Galaxy-Tab-S9.conf").is_symlink())
        audio_service = read("usr/lib/systemd/system/gts9wifi-audio-session.service")
        audio_timer = read("usr/lib/systemd/system/gts9wifi-audio-session.timer")
        audio_helper = read("usr/libexec/gts9wifi-audio-session")
        self.assertIn("Wants=gts9wifi-adsp-boot.service hexagonrpcd-adsp-rootpd.service pd-mapper.service alsa-restore.service", audio_service)
        self.assertIn("OnBootSec=5s", audio_timer)
        self.assertIn("/dev/snd/controlC0", audio_helper)
        self.assertIn('name") == "alsa_card.platform-sound"', audio_helper)
        profile_script = (ROOT / "tools/install-gnome-profile.sh").read_text(encoding="utf-8")
        self.assertIn("gts9wifi-audio-session.timer", profile_script)
        self.assertIn("stage-x810-audioreach-topology.sh", (ROOT / "tools/build-packages.sh").read_text(encoding="utf-8"))
        self.assertIn("stage-x810-cs35l45-firmware.sh", (ROOT / "tools/build-packages.sh").read_text(encoding="utf-8"))
        topology_stager = (ROOT / "tools/stage-x810-audioreach-topology.sh").read_text(encoding="utf-8")
        self.assertIn("SM8550-HDK-tplg.bin", topology_stager)
        self.assertIn("Samsung-Galaxy-Tab-S9-tplg.bin", topology_stager)
        self.assertIn("I2S_SD1", topology_stager)
        self.assertIn("X810 AudioReach topology is missing", profile_script)
        self.assertIn("CS35L45 protection firmware is missing", profile_script)

    def test_panel_coldboot_recovery_runs_before_gdm_and_keeps_console(self):
        unit = read("usr/lib/systemd/system/gts9wifi-panel-coldboot-recover.service")
        helper = read("usr/libexec/gts9wifi-panel-coldboot-recover")
        profile = (ROOT / "tools/install-gnome-profile.sh").read_text(encoding="utf-8")
        hook = (PACKAGE / "x810-device-support.install").read_text(encoding="utf-8")
        self.assertIn("ConditionPathExists=/sys/power/pm_test", unit)
        self.assertIn("Before=display-manager.service", unit)
        self.assertIn("WantedBy=graphical.target", unit)
        self.assertIn('echo platform > "$PM_TEST"', helper)
        self.assertIn('echo mem > "$PM_STATE"', helper)
        self.assertIn('echo none > "$PM_TEST"', helper)
        self.assertIn("gts9wifi-panel-coldboot-recover.service", profile)
        self.assertIn("gts9wifi-panel-coldboot-recover.service", hook)
        self.assertIn("getty@tty3.service", profile)

    def test_unverified_suspend_targets_are_masked_for_x810(self):
        package = PACKAGE / "files"
        policy = (package / "etc/systemd/logind.conf.d/10-gts9wifi-lid.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn("HandleLidSwitch=ignore", policy)
        self.assertIn("HoldoffTimeoutSec=0", policy)
        for target in (
            "sleep.target",
            "suspend.target",
            "hibernate.target",
            "hybrid-sleep.target",
            "suspend-then-hibernate.target",
        ):
            mask = package / "etc/systemd/system" / target
            self.assertTrue(mask.is_symlink(), f"missing systemd mask: {mask}")
            self.assertEqual(mask.readlink(), Path("/dev/null"))
        self.assertIn("systemctl daemon-reload", (PACKAGE / "x810-device-support.install").read_text())

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
        self.assertIn("gts9wifi-audio-session.timer", hook)
        self.assertIn("getty@tty3.service", hook)
        self.assertNotIn("--now", hook)


if __name__ == "__main__":
    unittest.main()
