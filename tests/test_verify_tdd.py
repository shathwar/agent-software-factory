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

    def test_invalid_ref_range_raises_discovery_error(self):
        """Invalid git ref range raises GitDiscoveryError with diagnostic details."""
        with self.assertRaises(verify_tdd.GitDiscoveryError) as ctx:
            verify_tdd.get_changed_files("definitely-missing-ref")
        self.assertIn("Could not inspect changes", str(ctx.exception))

    def test_cli_invalid_ref_range_fails_strict_and_json(self):
        """CLI with invalid ref-range fails with exit code 1 and emits passed=false in JSON."""
        cmd = [
            sys.executable,
            str(VERIFY_TDD),
            "--ref-range", "definitely-missing-ref",
            "--strict",
            "--json",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        data = json.loads(res.stdout)
        self.assertFalse(data["passed"])
        self.assertIsNotNone(data["error"])
        self.assertIn("Could not inspect changes", data["error"])
        categories = [f["category"] for f in data["findings"]]
        self.assertIn("git_discovery", categories)

    def test_get_changed_files_in_pre_commit_repository(self):
        """Pre-commit repository must discover staged and untracked files without failing on HEAD."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init", "-b", "main"], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

            src_file = tmppath / "service.py"
            src_file.write_text("def run(): pass\n")
            test_file = tmppath / "test_service.py"
            test_file.write_text("def test_run(): assert True\n")
            subprocess.run(["git", "add", "service.py", "test_service.py"], cwd=tmppath, check=True)

            untracked_file = tmppath / "untracked.py"
            untracked_file.write_text("x = 1\n")

            files = verify_tdd.get_changed_files(repo_root=tmppath)
            self.assertIn("service.py", files)
            self.assertIn("test_service.py", files)
            self.assertIn("untracked.py", files)

            res = verify_tdd.audit_tdd(files, repo_root=tmppath, strict=True)
            self.assertTrue(res.passed)

    def test_anti_pattern_dunder_attributes_not_flagged(self):
        """Dunder attributes like __class__ or __name__ should not trigger whitebox_spy warnings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_dunder.py"
            test_file.write_text(
                "def test_dunder():\n"
                "    handler = AuthHandler()\n"
                "    assert handler.__class__.__name__ == 'AuthHandler'\n"
                "    assert handler.process.__name__ == 'process'\n"
            )
            findings = verify_tdd.check_anti_patterns(test_file)
            whitebox = [f for f in findings if f.category == "whitebox_spy"]
            self.assertEqual(whitebox, [])

    def test_js_modifiers_and_rust_test_definitions(self):
        """Modifiers like test.skip, it.only and Rust fn test_... must be recognized as valid tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # JS/TS with modifiers
            js_test = Path(tmpdir) / "service.spec.ts"
            js_test.write_text(
                "test.skip('skips gracefully', () => {\n"
                "    expect(1).toBe(1);\n"
                "});\n"
                "it.only('runs exclusively', () => {\n"
                "    expect(2).toBe(2);\n"
                "});\n"
            )
            js_findings = verify_tdd.check_anti_patterns(js_test)
            assertless_js = [f for f in js_findings if f.category == "assertless_test"]
            self.assertEqual(assertless_js, [])

            # Rust test
            rs_test = Path(tmpdir) / "engine_test.rs"
            rs_test.write_text(
                "#[test]\n"
                "fn test_engine_init() {\n"
                "    assert!(true);\n"
                "}\n"
            )
            rs_findings = verify_tdd.check_anti_patterns(rs_test)
            assertless_rs = [f for f in rs_findings if f.category == "assertless_test"]
            self.assertEqual(assertless_rs, [])

    def test_expanded_code_extensions(self):
        """C/C++ headers and modern language extensions must be recognized as production code."""
        self.assertTrue(verify_tdd.is_production_code("src/engine.hpp"))
        self.assertTrue(verify_tdd.is_production_code("include/api.h"))
        self.assertTrue(verify_tdd.is_production_code("ios/App.swift"))
        self.assertTrue(verify_tdd.is_production_code("backend/Server.scala"))
        self.assertTrue(verify_tdd.is_production_code("lib/widget.dart"))

    def test_async_tests_and_template_literals(self):
        """Async test functions and JS template literals must be audited for assertions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Assertless async python test
            py_file = Path(tmpdir) / "test_async.py"
            py_file.write_text(
                "async def test_async_worker():\n"
                "    await worker.run()\n"
            )
            py_findings = verify_tdd.check_anti_patterns(py_file)
            assertless = [f for f in py_findings if f.category == "assertless_test"]
            self.assertEqual(len(assertless), 1)
            self.assertEqual(assertless[0].line, 1)

            # 2. Assertless JS test using template literal backticks
            js_file = Path(tmpdir) / "test_template.js"
            js_file.write_text(
                "it(`processes template transactions`, async () => {\n"
                "    const res = await process();\n"
                "});\n"
            )
            js_findings = verify_tdd.check_anti_patterns(js_file)
            assertless_js = [f for f in js_findings if f.category == "assertless_test"]
            self.assertEqual(len(assertless_js), 1)

            # 3. Valid async python test with pytest.warns
            py_valid = Path(tmpdir) / "test_valid_async.py"
            py_valid.write_text(
                "async def test_async_valid():\n"
                "    with pytest.warns(UserWarning):\n"
                "        await worker.warn()\n"
            )
            valid_findings = verify_tdd.check_anti_patterns(py_valid)
            self.assertEqual([f for f in valid_findings if f.category == "assertless_test"], [])

    def test_trim_test_receipt_word_boundary_isolation(self):
        """Log messages containing 'fail' as a substring must not be falsely captured as failure traces."""
        raw_log = (
            "Building wheel for package...\n"
            "Downloading failure-analyzer-1.0.tar.gz (500KB)\n"
            "Unpacking files...\n"
            + "\n".join(f"info line {i}" for i in range(50))
            + "\n"
            "Ran 15 tests in 0.05s\n\nOK\n"
        )
        trimmed = verify_tdd.trim_test_receipt(raw_log)
        self.assertNotIn("🔴 Failure Trace:", trimmed)
        self.assertIn("Test Suite Summary:", trimmed)

    def test_type_definitions_exempt_from_parity(self):
        """Pure type/interface/DTO definitions must be exempted from 1:1 test parity requirements."""
        type_files = [
            "src/types/user.ts",
            "api/schema.d.ts",
            "db/schema.prisma",
            "models/account.dto.ts",
            "types.ts",
            "pkg/interfaces/service.go",
        ]
        for tf in type_files:
            self.assertTrue(verify_tdd.is_type_definition(tf), f"Failed for {tf}")
            self.assertFalse(verify_tdd.is_production_code(tf), f"Should not be production code: {tf}")

        # An edit containing only type definitions passes strict TDD parity with zero test files required
        result = verify_tdd.audit_tdd(type_files, strict=True)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.untested_files), 0)
        self.assertEqual(len(result.production_files), 0)


if __name__ == "__main__":
    unittest.main()

