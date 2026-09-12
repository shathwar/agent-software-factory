"""Unit tests for verify_tdd.py (TDD verification and anti-pattern auditor)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VERIFY_TDD = ROOT / "skills/tdd/scripts/verify_tdd.py"

sys.path.insert(0, str(ROOT / "skills/tdd/scripts"))
import verify_tdd


class TestVerifyTDD(unittest.TestCase):
    def test_file_categorization(self):
        # Production files
        self.assertTrue(verify_tdd.is_production_code("src/user_service.py"))
        self.assertTrue(verify_tdd.is_production_code("pkg/auth/handler.go"))
        self.assertTrue(verify_tdd.is_production_code("app/services/payment.ts"))

        # Test files
        self.assertTrue(verify_tdd.is_test_file("tests/test_user.py"))
        self.assertTrue(verify_tdd.is_test_file("src/user_service_test.go"))
        self.assertTrue(verify_tdd.is_test_file("tests/payment.spec.ts"))
        self.assertFalse(verify_tdd.is_production_code("tests/test_user.py"))

        # Excluded paths
        self.assertTrue(verify_tdd.is_excluded("docs/architecture.md"))
        self.assertTrue(verify_tdd.is_excluded(".scratch/spike/bench.py"))
        self.assertTrue(verify_tdd.is_excluded("config.json"))
        self.assertFalse(verify_tdd.is_production_code("docs/architecture.md"))

    def test_anti_pattern_assertless_test(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_example.py"
            test_file.write_text(
                "def test_foo():\n"
                "    x = 1 + 1\n"
                "    y = x * 2\n"
            )
            findings = verify_tdd.check_anti_patterns(test_file)
            categories = [f.category for f in findings]
            self.assertIn("assertless_test", categories)

    def test_anti_pattern_whitebox_spy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_example.py"
            test_file.write_text(
                "def test_internal_state():\n"
                "    svc = UserService()\n"
                "    assert svc._internal_cache == {}\n"
            )
            findings = verify_tdd.check_anti_patterns(test_file)
            categories = [f.category for f in findings]
            self.assertIn("whitebox_spy", categories)

    def test_anti_pattern_clean_test(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_clean.py"
            test_file.write_text(
                "def test_public_outcome():\n"
                "    svc = UserService()\n"
                "    result = svc.register('alice')\n"
                "    assert result.is_active is True\n"
            )
            findings = verify_tdd.check_anti_patterns(test_file)
            self.assertEqual(findings, [])

    def test_audit_tdd_parity_failure(self):
        # Production files modified with zero test files
        files = ["src/billing/engine.py", "src/billing/invoices.py"]
        result = verify_tdd.audit_tdd(files, strict=True)
        self.assertFalse(result.passed)
        self.assertEqual(len(result.untested_files), 2)
        categories = [f.category for f in result.findings]
        self.assertIn("test_parity", categories)

    def test_audit_tdd_parity_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = Path(tmpdir) / "test_engine.py"
            test_path.write_text(
                "def test_engine():\n"
                "    assert 1 == 1\n"
            )
            files = ["src/billing/engine.py", str(test_path)]
            result = verify_tdd.audit_tdd(files, strict=True)
            self.assertTrue(result.passed)
            self.assertEqual(len(result.untested_files), 0)

    def test_trim_test_receipt(self):
        raw_lines = [f"Compiling dependency package #{i}..." for i in range(50)]
        raw_lines.extend([
            "FAILED tests/test_payment.py::test_charge - AssertionError: expected 200 got 500",
            "Traceback (most recent call last):",
            "  File 'test_payment.py', line 22, in test_charge",
            "    assert res.status_code == 200",
            "AssertionError: expected 200 got 500",
            "=================== 1 failed, 24 passed in 1.42s ==================="
        ])
        raw_log = "\n".join(raw_lines)
        trimmed = verify_tdd.trim_test_receipt(raw_log, max_lines=20)
        self.assertIn("TDD Receipt Trimmer: Compact Output", trimmed)
        self.assertIn("AssertionError", trimmed)
        self.assertIn("1 failed, 24 passed", trimmed)
        self.assertNotIn("Compiling dependency package #10", trimmed)

    def test_cli_execution(self):
        res = subprocess.run([sys.executable, str(VERIFY_TDD), "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("--ref-range", res.stdout)
        self.assertIn("--trim-receipt", res.stdout)


if __name__ == "__main__":
    unittest.main()
