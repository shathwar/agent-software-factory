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

    def test_assertion_pattern_polyglot_and_context_managers(self):
        """Polyglot assertions and context managers satisfy assertion check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_polyglot.py"
            test_file.write_text(
                "def test_pytest_raises():\n"
                "    with pytest.raises(ValueError):\n"
                "        raise ValueError('boom')\n"
                "\n"
                "def test_rust_assert_eq():\n"
                "    assert_eq!(1, 1)\n"
                "\n"
                "def test_go_require():\n"
                "    require.NoError(t, err)\n"
                "\n"
                "def test_c_style_assert():\n"
                "    assert(x == 1)\n"
            )
            findings = verify_tdd.check_anti_patterns(test_file)
            assertless = [f for f in findings if f.category == "assertless_test"]
            self.assertEqual(assertless, [])

    def test_comment_lines_do_not_trigger_whitebox_spy(self):
        """Comments mentioning private variables should not be flagged as whitebox spys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_comments.py"
            test_file.write_text(
                "# Note: do not test obj._internal directly\n"
                "// Or check service._cache in other tests\n"
                "/* Another comment about db._pool */\n"
                "* star comment obj._hidden\n"
                "def test_public():\n"
                "    assert run_action() == 42\n"
            )
            findings = verify_tdd.check_anti_patterns(test_file)
            whitebox = [f for f in findings if f.category == "whitebox_spy"]
            self.assertEqual(whitebox, [])

    def test_mock_counter_ignores_dispatch(self):
        """Methods like dispatch or dispatcher should not falsely increment mock count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_dispatch.py"
            code_lines = ["def test_event_dispatcher():\n"]
            for i in range(10):
                code_lines.append(f"    dispatcher.dispatch_event('evt_{i}')\n")
            code_lines.append("    assert dispatcher.count == 10\n")
            test_file.write_text("".join(code_lines))
            findings = verify_tdd.check_anti_patterns(test_file)
            hollow_mocks = [f for f in findings if f.category == "hollow_mock"]
            self.assertEqual(hollow_mocks, [])


if __name__ == "__main__":
    unittest.main()
