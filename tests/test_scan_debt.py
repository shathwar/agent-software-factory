"""Unit tests for ponytail debt scanner (scan_debt.py)."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCAN_DEBT = ROOT / "skills" / "ponytail" / "scripts" / "scan_debt.py"

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


if __name__ == "__main__":
    unittest.main()
