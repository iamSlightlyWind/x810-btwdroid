#!/usr/bin/env python3
"""Integration tests for Arch port-update bundling and aggregate release assembly."""

from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_info = load("arch_port_build_info", "write-arch-port-build-info.py")
bundle = load("arch_port_bundle", "make-arch-port-update-bundle.py")
assembler = load("arch_release_assembler", "assemble-arch-release.py")


@unittest.skipUnless(shutil.which("zstd"), "zstd is required")
class ArchPortReleaseTests(unittest.TestCase):
    def make_package(self, path: Path, *, pkgname="x810-device-support") -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tar_path = Path(temporary) / "package.tar"
            pkginfo = f"pkgname = {pkgname}\npkgver = 0.1.0-3\narch = any\n".encode()
            with tarfile.open(tar_path, "w") as archive:
                for name, content in (
                    (".PKGINFO", pkginfo),
                    ("usr/share/tab-companion/port.json", b'{"port_id":"x810-arch"}\n'),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
            with path.open("wb") as output:
                result = subprocess.run(["zstd", "-q", "-c", str(tar_path)], stdout=output, stderr=subprocess.PIPE)
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors="replace"))

    def make_update_zip(self, root: Path) -> tuple[Path, int, int, str, str]:
        run_id, run_number = 1234, 17
        commit, branch = "a" * 40, "main"
        info_path = root / "port-build.json"
        build_info.write_build_info(
            info_path, version="0.1.0", run_id=run_id, run_number=run_number,
            commit=commit, branch=branch,
        )
        package = root / "x810-device-support-0.1.0-3-any.pkg.tar.zst"
        self.make_package(package)
        output = root / "update.zip"
        bundle.create_bundle(package, info_path, output)
        return output, run_id, run_number, commit, branch

    def test_port_update_bundle_has_native_arch_package_and_push_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            update, run_id, run_number, commit, branch = self.make_update_zip(root)
            with zipfile.ZipFile(update) as archive:
                manifest = json.loads(archive.read("tab-companion-update.json"))
                record = manifest["assets"][0]
                payload = archive.read(record["name"])
            self.assertEqual(manifest["project"], "x810-arch")
            self.assertEqual((manifest["run_id"], manifest["run_number"], manifest["commit"], manifest["branch"]),
                             (run_id, run_number, commit, branch))
            self.assertEqual(record["format"], "pacman-local")
            self.assertEqual(record["package_name"], "x810-device-support")
            self.assertEqual(record["target"], {
                "os_id": "archarm", "os_version": "rolling", "arch": "aarch64", "device": "SM-X810",
            })
            self.assertEqual(hashlib.sha256(payload).hexdigest(), record["sha256"])

    def test_full_release_assembly_carries_rootfs_and_tab_companion_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_dir = root / "release"
            release_dir.mkdir()
            archive = release_dir / "rootfs.tar.zst"
            archive.write_bytes(b"verified-rootfs-test-payload")
            commit, input_key = "a" * 40, "b" * 64
            update, run_id, run_number, commit, branch = self.make_update_zip(root)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            (release_dir / "manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "type": "x810-arch-release",
                "release_tag": f"x810-arch-build-{run_id}",
                "source_commit": commit,
                "build_inputs_key": input_key,
                "device": {"model": "SM-X810", "codename": "gts9pwifi"},
                "os": {"id": "archarm", "arch": "aarch64"},
                "rootfs": {"archive": archive.name, "size_bytes": archive.stat().st_size, "sha256": digest},
                "assets": [{"name": archive.name, "size_bytes": archive.stat().st_size, "sha256": digest}],
            }))
            manifest = assembler.assemble(
                release_dir, update, tag=f"x810-arch-build-{run_id}", run_id=run_id,
                run_number=run_number, commit=commit, branch=branch, input_key=input_key,
                port_version="0.1.0",
            )
            self.assertEqual([asset["name"] for asset in manifest["assets"]], ["rootfs.tar.zst", "update.zip"])
            self.assertEqual(manifest["port_update"]["package_name"], "x810-device-support")
            self.assertTrue((release_dir / "SHA256SUMS").read_text().find("update.zip") >= 0)
            self.assertEqual((release_dir / "update.zip").read_bytes(), update.read_bytes())

    def test_port_build_info_rejects_invalid_provenance(self):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(ValueError, "commit"):
            build_info.write_build_info(
                Path(temporary) / "port-build.json", version="0.1.0", run_id=1,
                run_number=1, commit="bad", branch="main",
            )


if __name__ == "__main__":
    unittest.main()
