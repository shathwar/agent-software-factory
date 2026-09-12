"""Unit tests for ponytail debt scanner (scan_debt.py)."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCAN_DEBT = ROOT / "skills" / "simplify" / "scripts" / "scan_debt.py"

sys.path.insert(0, str(SCAN_DEBT.parent))
import scan_debt


class TestScanDebt(unittest.TestCase):
    def test_parse_valid_marker(self):
        line = "// ponytail: In-memory cache. Ceiling: 1,000 items. Upgrade: Redis."
        res = scan_debt.parse_debt_marker(line, "src/cache.ts", 42)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["shortcut"], "In-memory cache")
        self.assertEqual(res["ceiling"], "1,000 items")
        self.assertEqual(res["upgrade"], "Redis")
        self.assertEqual(res["file"], "src/cache.ts")
        self.assertEqual(res["line"], 42)
        self.assertEqual(len(res["errors"]), 0)

    def test_parse_valid_simplify_marker(self):
        line = "// simplify: In-memory cache. Ceiling: 1,000 items. Upgrade: Redis."
        res = scan_debt.parse_debt_marker(line, "src/cache.ts", 42)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["shortcut"], "In-memory cache")
        self.assertEqual(res["ceiling"], "1,000 items")
        self.assertEqual(res["upgrade"], "Redis")
        self.assertEqual(res["file"], "src/cache.ts")
        self.assertEqual(res["line"], 42)
        self.assertEqual(len(res["errors"]), 0)

    def test_parse_missing_ceiling(self):
        line = "# ponytail: Simple SQLite. Upgrade: Postgres RDS."
        res = scan_debt.parse_debt_marker(line, "db.py", 10)
        self.assertFalse(res["is_valid"])
        self.assertIn("Missing 'Ceiling:' threshold", res["errors"])

    def test_parse_missing_upgrade(self):
        line = "/* ponytail: O(N) array filter. Ceiling: 50 users. */"
        res = scan_debt.parse_debt_marker(line, "users.c", 88)
        self.assertFalse(res["is_valid"])
        self.assertIn("Missing 'Upgrade:' path", res["errors"])

    def test_parse_vague_description(self):
        line = "// ponytail: todo. Ceiling: 100. Upgrade: fix it."
        res = scan_debt.parse_debt_marker(line, "app.go", 15)
        self.assertFalse(res["is_valid"])
        self.assertTrue(any("Vague or missing" in e for e in res["errors"]))

    def test_scan_directory_and_formatting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            f1 = tmppath / "valid.py"
            f1.write_text(
                "# ponytail: Local dict map. Ceiling: 5,000 keys. Upgrade: Memcached.\n"
                "def get_user(): pass\n"
            )
            f2 = tmppath / "invalid.js"
            f2.write_text(
                "// ponytail: Temp mock data. Ceiling: Local dev only.\n"
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
            f.write_text("# ponytail: Shortcut without ceiling.\n")

            cmd = [sys.executable, str(SCAN_DEBT), "--strict", str(tmppath)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn("invalid debt marker", res.stderr)

    def test_cli_json_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            f = tmppath / "good.go"
            f.write_text("// ponytail: Mutex lock. Ceiling: 1k RPS. Upgrade: Channel fan-out.\n")

            cmd = [sys.executable, str(SCAN_DEBT), "--format", "json", str(tmppath)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            data = json.loads(res.stdout)
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]["is_valid"])
            self.assertEqual(data[0]["ceiling"], "1k RPS")

    def test_empty_required_fields_and_pipe_separated_format(self):
        # 1. Empty required fields must fail validation
        empty_line = "// ponytail: In-memory store. Ceiling: . Upgrade: ."
        res_empty = scan_debt.parse_debt_marker(empty_line, "store.ts", 12)
        self.assertFalse(res_empty["is_valid"])
        self.assertIn("Empty 'Ceiling:' threshold", res_empty["errors"])
        self.assertIn("Empty 'Upgrade:' path", res_empty["errors"])

        # 2. Pipe-separated format must correctly isolate ceiling and upgrade
        pipe_line = "// ponytail: In-memory store | Ceiling: 500 req/s | Upgrade: Redis cache"
        res_pipe = scan_debt.parse_debt_marker(pipe_line, "store.ts", 20)
        self.assertTrue(res_pipe["is_valid"])
        self.assertEqual(res_pipe["shortcut"], "In-memory store")
        self.assertEqual(res_pipe["ceiling"], "500 req/s")
        self.assertEqual(res_pipe["upgrade"], "Redis cache")

    def test_vague_ceiling_and_upgrade_placeholders_are_rejected(self):
        for placeholder in ["none", "N/A", "TBD", "todo", "fixme"]:
            with self.subTest(placeholder=placeholder):
                line = f"// ponytail: Quick cache. Ceiling: {placeholder}. Upgrade: Redis."
                res = scan_debt.parse_debt_marker(line, "cache.py", 10)
                self.assertFalse(res["is_valid"])
                self.assertTrue(any("Ceiling" in e for e in res["errors"]))

                line2 = f"// ponytail: Quick cache. Ceiling: 1k users. Upgrade: {placeholder}."
                res2 = scan_debt.parse_debt_marker(line2, "cache.py", 12)
                self.assertFalse(res2["is_valid"])
                self.assertTrue(any("Upgrade" in e for e in res2["errors"]))

    def test_binary_files_are_safely_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            binary_file = tmppath / "image.png"
            # Write binary bytes including null bytes and substring ponytail:
            binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRponytail: bad\x00\x00")

            markers = scan_debt.scan_paths([tmppath])
            self.assertEqual(len(markers), 0)

    def test_non_comment_strings_and_code_are_ignored(self):
        non_comments = [
            'if "ponytail:" in line.lower():',
            'MARKER_PATTERN = re.compile(r"ponytail:\s*(.+)$", re.IGNORECASE)',
            '│   • Code Refactorer: Simplifies under green; adds ponytail: debt markers    │',
            'Scan codebases for ponytail: technical debt markers',
            'const markerName = "ponytail: custom";',
        ]
        for line in non_comments:
            with self.subTest(line=line):
                res = scan_debt.parse_debt_marker(line, "app.py", 1)
                self.assertEqual(res, {})

    def test_markdown_headings_and_asset_extensions_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            md_file = tmppath / "README.md"
            md_file.write_text("# ponytail: Lazy Senior Developer Engine\n")

            pdf_file = tmppath / "doc.pdf"
            pdf_file.write_text("ponytail: text in pdf")

            markers = scan_debt.scan_paths([tmppath])
            self.assertEqual(len(markers), 0)

    def test_template_syntax_placeholders_are_rejected(self):
        """Syntax example templates like <Shortcut>, <Threshold/Limit>, <Next Architecture> must fail validation."""
        template_line = "// ponytail: <Shortcut>. Ceiling: <Threshold/Limit>. Upgrade: <Next Architecture>."
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
                '"""\nExample:\n    // ponytail: <Shortcut>. Ceiling: <Limit>. Upgrade: <Next>.\n"""\n'
                '# ponytail: Real shortcut. Ceiling: 50 RPS. Upgrade: Worker pool.\ndef work(): pass\n'
            )
            md_file = tmppath / "guide.md"
            md_file.write_text(
                '# Guide\n```text\n// ponytail: <Shortcut>. Ceiling: <Limit>. Upgrade: <Next>.\n```\n'
                '```go\n// ponytail: Go map. Ceiling: 100 users. Upgrade: Postgres.\n```\n'
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
                '# ponytail: Unbounded cache.\n'
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


if __name__ == "__main__":
    unittest.main()
