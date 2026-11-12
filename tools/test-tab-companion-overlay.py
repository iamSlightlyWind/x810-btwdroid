#!/usr/bin/env python3
"""Static contract tests for the bundled Tab Companion browser-memory support."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "packages/tab-companion/overlay"


class BrowserOverlayTests(unittest.TestCase):
    def test_browser_selector_and_limits_are_in_arch_package_overlay(self):
        memory = (OVERLAY / "usr/lib/tab-companion/tab_companion/browser_memory.py").read_text()
        page = (OVERLAY / "usr/lib/tab-companion/tab_companion/power_profiles_page.py").read_text()
        agent = (OVERLAY / "usr/libexec/tab-companion-browser-memory-agent").read_text()
        helper = (OVERLAY / "usr/libexec/tab-companion-browser-memory-setting").read_text()
        service = (OVERLAY / "usr/lib/systemd/user/tab-companion-browser-memory.service").read_text()
        self.assertIn('SUPPORTED_BROWSERS = ("firefox", "brave")', memory)
        self.assertIn("BRAVE_SCOPE", memory)
        self.assertIn('title=_("Browser")', page)
        self.assertIn('model=Gtk.StringList.new(browser_names)', page)
        self.assertIn('_("Firefox"), _("Brave")', page)
        self.assertIn('"browser_sessions"', agent)
        self.assertIn("browser_scope_names(output, settings[\"browser\"])", agent)
        self.assertIn("settings['browser']", helper)
        self.assertIn("native browser memory limit", service)

    def test_arch_package_keeps_dualboot_with_arch_linux_arm_backend(self):
        pkgbuild = (ROOT / "packages/tab-companion/PKGBUILD").read_text()
        core = (OVERLAY / "usr/local/libexec/x810-boot-switch-core").read_text()
        status = (OVERLAY / "usr/local/libexec/tab-companion-boot-status").read_text()
        self.assertIn("archarm", core)
        self.assertIn("Arch Linux ARM", core)
        self.assertIn('"fedora"', status)
        self.assertIn("usr/local/libexec/x810-boot-switch-core", pkgbuild)
        self.assertIn("usr/local/libexec/tab-companion-boot-status", pkgbuild)
        self.assertNotIn('rm -f "$pkgdir/usr/local/libexec/x810-boot-switch-core"', pkgbuild)
        self.assertNotIn('rm -rf "$pkgdir/usr/share/gnome-shell/extensions/dualboot@agcarbajo.github.io"', pkgbuild)
        self.assertIn('chown -R root:root "$pkgdir"', pkgbuild)
        port = json.loads((ROOT / "packages/x810-device-support/files/usr/share/tab-companion/port.json").read_text())
        self.assertTrue(port["capabilities"]["dualboot"])
        self.assertEqual(port["kernel_update"], {"backend": "pacman", "available": False})
        self.assertEqual(port["port_update"], {"backend": "pacman", "available": False})
        for extension in (
            "dualboot@agcarbajo.github.io",
            "spen-dock@agcarbajo.github.io",
            "tab-companion-haptics@agcarbajo",
        ):
            metadata = json.loads((OVERLAY / f"usr/share/gnome-shell/extensions/{extension}/metadata.json").read_text())
            self.assertIn("51", metadata["shell-version"], extension)

    def test_package_installs_overlay_and_profile_requests_target_packages(self):
        pkgbuild = (ROOT / "packages/tab-companion/PKGBUILD").read_text()
        profile = (ROOT / "tools/install-gnome-profile.sh").read_text()
        build = (ROOT / "tools/build-packages.sh").read_text()
        brave = (ROOT / "packages/brave-bin/PKGBUILD").read_text()
        for relative in (
            "browser_memory.py",
            "power_profiles_page.py",
            "window.py",
            "tab-companion-browser-memory-agent",
            "tab-companion-browser-memory-setting",
            "tab-companion-browser-memory.service",
        ):
            self.assertIn(relative, pkgbuild)
        for package in ("brave-bin", "gnome-terminal", "bluez-utils"):
            self.assertIn(package, profile)
        self.assertIn("bluetooth.service", profile)
        self.assertIn("CARCH=aarch64", build)
        self.assertIn("brave-bin", build)
        self.assertIn("arch=('aarch64')", brave)
        self.assertIn("sha256sums_aarch64", brave)


if __name__ == "__main__":
    unittest.main()
