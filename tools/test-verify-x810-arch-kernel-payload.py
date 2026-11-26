#!/usr/bin/env python3
"""Unit tests for the Arch X810 zboot payload marker check."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


PATH = Path(__file__).resolve().with_name("verify-x810-arch-kernel-payload.py")
SPEC = importlib.util.spec_from_file_location("verify_x810_arch_payload", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PayloadTests(unittest.TestCase):
    def test_accepts_current_pps_settle_path_and_pogo_revision(self):
        payload = b"driver_revision=12\0PPS bus did not settle: target=%dmV measured=%dmV\0Handling deferred source Alert after PPS AMS\0"
        MODULE.verify(payload, "static int driver_revision=12;\n")

    def test_rejects_old_or_incomplete_kernel_payload(self):
        payload = b"driver_revision=12\0same-point PPS keep-alive completed without parking pump\0Handling deferred source Alert after PPS AMS\0"
        with self.assertRaisesRegex(ValueError, "PPS bus did not settle"):
            MODULE.verify(payload, "static int driver_revision=12;\n")


if __name__ == "__main__":
    unittest.main()
