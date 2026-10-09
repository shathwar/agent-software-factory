"""Unit tests for simplify debt scanner (scan_debt.py)."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCAN_DEBT = ROOT / "skills" / "simplify" / "scripts" / "scan_debt.py"
if not SCAN_DEBT.exists() or not SCAN_DEBT.is_file():
    SCAN_DEBT = ROOT / "src" / "ship" / "tools" / "simplify.py"
try:
    SCAN_DEBT.read_bytes()
except (PermissionError, OSError):
    SCAN_DEBT = ROOT / "src" / "ship" / "tools" / "simplify.py"

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCAN_DEBT.parent))
try:
    import scan_debt
except (ImportError, PermissionError):
    from ship.tools import simplify as scan_debt


class TestScanDebt(unittest.TestCase):
    def test_parse_valid_marker(self):
        line = "// simplify: In-memory cache. Ceiling: 1,000 items. Upgrade: Redis."
        res = scan_debt.parse_debt_marker(line, "src/cache.ts", 42)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["shortcut"], "In-memory cache")
        self.assertEqual(res["ceiling"], "1,000 items")
        self.assertEqual(res["upgrade"], "Redis")
        self.assertEqual(res["file"], "src/cache.ts")
        self.assertEqual(res["line"], 42)
        self.assertEqual(len(res["errors"]), 0)

    def test_legacy_ponytail_marker_ignored(self):
        line = "// ponytail: In-memory cache. Ceiling: 1,000 items. Upgrade: Redis."
        res = scan_debt.parse_debt_marker(line, "src/cache.ts", 42)
        self.assertEqual(res, {})

    def test_parse_missing_ceiling(self):
        line = "# simplify: Simple SQLite. Upgrade: Postgres RDS."
        res = scan_debt.parse_debt_marker(line, "db.py", 10)
        self.assertFalse(res["is_valid"])
        self.assertIn("Missing 'Ceiling:' threshold", res["errors"])

    def test_parse_missing_upgrade(self):
        line = "/* simplify: O(N) array filter. Ceiling: 50 users. */"
        res = scan_debt.parse_debt_marker(line, "users.c", 88)
        self.assertFalse(res["is_valid"])
        self.assertIn("Missing 'Upgrade:' path", res["errors"])

    def test_parse_vague_description(self):
        line = "// simplify: todo. Ceiling: 100. Upgrade: fix it."
        res = scan_debt.parse_debt_marker(line, "app.go", 15)
        self.assertFalse(res["is_valid"])
        self.assertTrue(any("Vague or missing" in e for e in res["errors"]))

    def test_scan_directory_and_formatting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            f1 = tmppath / "valid.py"
            f1.write_text(
                "# simplify: Local dict map. Ceiling: 5,000 keys. Upgrade: Memcached.\n"
                "def get_user(): pass\n"
            )
            f2 = tmppath / "invalid.js"
            f2.write_text(
                "// simplify: Temp mock data. Ceiling: Local dev only.\n"
            )

            markers = scan_debt.scan_paths([tmppath])
            self.assertEqual(len(markers), 2)
            valid = [m for m in markers if m["is_valid"]]
            invalid = [m for m in markers if not m["is_valid"]]
            self.assertEqual(len(valid), 1)
            self.assertEqual(len(invalid), 1)

            table_output = scan_debt.format_table(markers)
            self.assertIn("Local dict map", table_output)
            self.assertIn("✅ Valid", table_output)
            self.assertIn("❌ Invalid", table_output)

    def test_cli_strict_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            f = tmppath / "bad.py"
            f.write_text("# simplify: Shortcut without ceiling.\n")

            cmd = [sys.executable, str(SCAN_DEBT), "--strict", str(tmppath)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn("invalid debt marker", res.stderr)

    def test_cli_json_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            f = tmppath / "good.go"
            f.write_text("// simplify: Mutex lock. Ceiling: 1k RPS. Upgrade: Channel fan-out.\n")

            cmd = [sys.executable, str(SCAN_DEBT), "--format", "json", str(tmppath)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            data = json.loads(res.stdout)
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]["is_valid"])
            self.assertEqual(data[0]["ceiling"], "1k RPS")

    def test_empty_required_fields_and_pipe_separated_format(self):
        # 1. Empty required fields must fail validation
        empty_line = "// simplify: In-memory store. Ceiling: . Upgrade: ."
        res_empty = scan_debt.parse_debt_marker(empty_line, "store.ts", 12)
        self.assertFalse(res_empty["is_valid"])
        self.assertIn("Empty 'Ceiling:' threshold", res_empty["errors"])
        self.assertIn("Empty 'Upgrade:' path", res_empty["errors"])

        # 2. Pipe-separated format must correctly isolate ceiling and upgrade
        pipe_line = "// simplify: In-memory store | Ceiling: 500 req/s | Upgrade: Redis cache"
        res_pipe = scan_debt.parse_debt_marker(pipe_line, "store.ts", 20)
        self.assertTrue(res_pipe["is_valid"])
        self.assertEqual(res_pipe["shortcut"], "In-memory store")
        self.assertEqual(res_pipe["ceiling"], "500 req/s")
        self.assertEqual(res_pipe["upgrade"], "Redis cache")

    def test_vague_ceiling_and_upgrade_placeholders_are_rejected(self):
        for placeholder in ["none", "N/A", "TBD", "todo", "fixme"]:
            with self.subTest(placeholder=placeholder):
                line = f"// simplify: Quick cache. Ceiling: {placeholder}. Upgrade: Redis."
                res = scan_debt.parse_debt_marker(line, "cache.py", 10)
                self.assertFalse(res["is_valid"])
                self.assertTrue(any("Ceiling" in e for e in res["errors"]))

                line2 = f"// simplify: Quick cache. Ceiling: 1k users. Upgrade: {placeholder}."
                res2 = scan_debt.parse_debt_marker(line2, "cache.py", 12)
                self.assertFalse(res2["is_valid"])
                self.assertTrue(any("Upgrade" in e for e in res2["errors"]))

    def test_binary_files_are_safely_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            binary_file = tmppath / "image.png"
            # Write binary bytes including null bytes and substring simplify:
            binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRsimplify: bad\x00\x00")

            markers = scan_debt.scan_paths([tmppath])
            self.assertEqual(len(markers), 0)

    def test_non_comment_strings_and_code_are_ignored(self):
        non_comments = [
            'if "simplify:" in line.lower():',
            r'MARKER_PATTERN = re.compile(r"simplify:\s*(.+)$", re.IGNORECASE)',
            '│   • Code Refactorer: Simplifies under green; adds simplify: debt markers    │',
            'Scan codebases for simplify: technical debt markers',
            'const markerName = "simplify: custom";',
        ]
        for line in non_comments:
            with self.subTest(line=line):
                res = scan_debt.parse_debt_marker(line, "app.py", 1)
                self.assertEqual(res, {})

    def test_markdown_headings_and_asset_extensions_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            md_file = tmppath / "README.md"
            md_file.write_text("# simplify: Lazy Senior Developer Engine\n")

            pdf_file = tmppath / "doc.pdf"
            pdf_file.write_text("simplify: text in pdf")

            markers = scan_debt.scan_paths([tmppath])
            self.assertEqual(len(markers), 0)

    def test_template_syntax_placeholders_are_rejected(self):
        """Syntax example templates like <Shortcut>, <Threshold/Limit>, <Next Architecture> must fail validation."""
        template_line = "// simplify: <Shortcut>. Ceiling: <Threshold/Limit>. Upgrade: <Next Architecture>."
        res = scan_debt.parse_debt_marker(template_line, "syntax.ts", 5)
        self.assertFalse(res["is_valid"])
        self.assertTrue(any("placeholder in shortcut description" in e for e in res["errors"]))
        self.assertTrue(any("placeholder in 'Ceiling:'" in e for e in res["errors"]))
        self.assertTrue(any("placeholder in 'Upgrade:'" in e for e in res["errors"]))

    def test_python_docstrings_and_markdown_text_fences_are_skipped(self):
        """Docstring examples in Python files and text code fences in markdown files must be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            py_file = tmppath / "tool.py"
            py_file.write_text(
                '"""\nExample:\n    // simplify: <Shortcut>. Ceiling: <Limit>. Upgrade: <Next>.\n"""\n'
                '# simplify: Real shortcut. Ceiling: 50 RPS. Upgrade: Worker pool.\ndef work(): pass\n'
            )
            md_file = tmppath / "guide.md"
            md_file.write_text(
                '# Guide\n```text\n// simplify: <Shortcut>. Ceiling: <Limit>. Upgrade: <Next>.\n```\n'
                '```go\n// simplify: Go map. Ceiling: 100 users. Upgrade: Postgres.\n```\n'
            )

            markers = scan_debt.scan_paths([tmppath])
            self.assertEqual(len(markers), 2)
            shortcuts = {m["shortcut"] for m in markers}
            self.assertIn("Real shortcut", shortcuts)
            self.assertIn("Go map", shortcuts)
            self.assertNotIn("<Shortcut>", shortcuts)

    def test_tokenizer_detects_debt_marker_after_triple_quote_string(self):
        """Standard-library tokenizer accurately detects debt comment after single-line string with triple quotes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            py_file = tmppath / "parser.py"
            py_file.write_text(
                'DELIMITER = \'"""\'\n'
                '# simplify: Unbounded cache.\n'
            )

            markers = scan_debt.scan_paths([tmppath])
            self.assertEqual(len(markers), 1)
            self.assertEqual(markers[0]["shortcut"], "Unbounded cache")
            self.assertFalse(markers[0]["is_valid"])

            # In strict mode, CLI must fail
            cmd = [sys.executable, str(SCAN_DEBT), "--strict", str(tmppath)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn("invalid debt marker", res.stderr)

    def test_scan_simplify_markers_in_python_and_typescript(self):
        """CLI and file scanner properly discover and validate simplify: markers in Python and TypeScript."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            py_file = tmppath / "service.py"
            py_file.write_text(
                "# simplify: In-memory cache. Ceiling: 5k RPS. Upgrade: Redis cluster.\n"
                "def get_user(): pass\n"
                "# simplify: Broken shortcut without ceiling.\n"
            )

            ts_file = tmppath / "handler.ts"
            ts_file.write_text(
                "// simplify: O(N) filter. Ceiling: 100 items. Upgrade: Map index.\n"
                "const filterUsers = () => [];\n"
                "// simplify: Missing upgrade path. Ceiling: 50 users.\n"
            )

            markers = scan_debt.scan_paths([tmppath])
            self.assertEqual(len(markers), 4)
            valid_markers = [m for m in markers if m["is_valid"]]
            invalid_markers = [m for m in markers if not m["is_valid"]]
            self.assertEqual(len(valid_markers), 2)
            self.assertEqual(len(invalid_markers), 2)

            # In strict mode, CLI must fail with exit code 1
            cmd_strict = [sys.executable, str(SCAN_DEBT), "--strict", str(tmppath)]
            res_strict = subprocess.run(cmd_strict, capture_output=True, text=True)
            self.assertEqual(res_strict.returncode, 1)
            self.assertIn("Found 2 invalid debt marker(s)", res_strict.stderr)

            # In normal mode, CLI must exit 0 and render table
            cmd_normal = [sys.executable, str(SCAN_DEBT), str(tmppath)]
            res_normal = subprocess.run(cmd_normal, capture_output=True, text=True)
            self.assertEqual(res_normal.returncode, 0)
            self.assertIn("In-memory cache", res_normal.stdout)
            self.assertIn("O(N) filter", res_normal.stdout)

    def test_audit_code_simplicity_redundant_dependencies(self):
        js_code = 'import { v4 } from "uuid";\nimport clone from "lodash.clonedeep";\n'
        findings = scan_debt.audit_code_simplicity("test.js", js_code)
        self.assertEqual(len(findings), 2)
        self.assertTrue(all(f["rule_id"] == "SMP-DEP-001" for f in findings))
        self.assertTrue(all(f["severity"] == "ERROR" for f in findings))

    def test_audit_code_simplicity_speculative_factory_and_wrapper(self):
        py_code = (
            "class SvcFactory:\n"
            "    @staticmethod\n"
            "    def create(): return None\n\n"
            "class SvcWrapper:\n"
            "    def __init__(self, inner):\n"
            "        self._inner = inner\n"
            "    def a(self): return self._inner.a()\n"
            "    def b(self): return self._inner.b()\n"
        )
        findings = scan_debt.audit_code_simplicity("svc.py", py_code)
        rule_ids = {f["rule_id"] for f in findings}
        self.assertIn("SMP-ABS-001", rule_ids)
        self.assertIn("SMP-WRAP-001", rule_ids)

    def test_simplify_fixtures(self):
        fixtures_dir = ROOT / "tests/fixtures/simplify"

        # 01-unrequested-abstraction
        f1 = fixtures_dir / "01-unrequested-abstraction/user_factory.py"
        findings_1 = scan_debt.audit_code_simplicity(f1)
        rules_1 = {f["rule_id"] for f in findings_1}
        self.assertIn("SMP-ABS-001", rules_1)
        self.assertIn("SMP-WRAP-001", rules_1)

        # 02-dependency-inflation
        f2 = fixtures_dir / "02-dependency-inflation/id_generator.ts"
        findings_2 = scan_debt.audit_code_simplicity(f2)
        rules_2 = {f["rule_id"] for f in findings_2}
        self.assertIn("SMP-DEP-001", rules_2)

        # 03-destructive-deletion
        f3 = fixtures_dir / "03-destructive-deletion/diff.patch"
        self.assertTrue(f3.exists())
        self.assertIn("-        if not user_id", f3.read_text())

        # 04-invalid-debt-marker
        f4 = fixtures_dir / "04-invalid-debt-marker/cache_service.py"
        markers_4 = scan_debt.scan_paths([f4])
        self.assertEqual(len(markers_4), 2)
        self.assertTrue(all(not m["is_valid"] for m in markers_4))

    def test_evaluate_simplify_rubric(self):
        sys.path.insert(0, str(ROOT / "tests/evaluation"))
        import evaluate_simplify_rubric

        evaluator = evaluate_simplify_rubric.SimplifyRubricEvaluator(passing_threshold=0.80)

        # Clean minimal code
        good_code = (
            "import os\n"
            "from pathlib import Path\n\n"
            "class ConfigReader:\n"
            "    def __init__(self, base_dir: Path):\n"
            "        self.base_dir = base_dir\n"
            "    def read_key(self, key: str, default: str = '') -> str:\n"
            "        return os.environ.get(key, default)\n"
        )
        report_good = evaluator.evaluate_code(good_code, "GoodConfig")
        self.assertTrue(report_good.passed)
        self.assertEqual(report_good.status, "PASS")

        # Over-engineered / redundant code
        bad_code = (
            "import cloneDeep from 'lodash.clonedeep';\n"
            "class UserFactory:\n"
            "    def create(): pass\n"
        )
        report_bad = evaluator.evaluate_code(bad_code, "BadCode")
        self.assertFalse(report_bad.passed)
        self.assertIn("Redundant 3rd-party dependency", report_bad.domain_scores["stdlib_first"].feedback[0])

    def test_modern_redundant_dependencies_detected(self):
        """Newly added redundant dependencies (axios, mock, six, etc.) are detected."""
        findings = scan_debt.audit_code_simplicity("src/client.ts", content="import axios from 'axios';")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule_id"], "SMP-DEP-001")

        py_findings = scan_debt.audit_code_simplicity("src/test_shim.py", content="import mock\nimport six")
        self.assertEqual(len(py_findings), 2)
        rules = [f["rule_id"] for f in py_findings]
        self.assertEqual(rules, ["SMP-DEP-001", "SMP-DEP-001"])


if __name__ == "__main__":
    unittest.main()

