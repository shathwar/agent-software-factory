"""Tests for ship-sdlc packaging, CLI subcommands, and flag backward compatibility."""

import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ship.cli import main as ship_cli_main


class PackagingTests(unittest.TestCase):
    def test_pyproject_toml_structure_and_metadata(self):
        """pyproject.toml conforms to standard PEP 518/621 specification."""
        pyproject_path = ROOT / "pyproject.toml"
        self.assertTrue(pyproject_path.exists())
        content = pyproject_path.read_text(encoding="utf-8")
        self.assertIn('name = "ship-sdlc"', content)
        self.assertIn('version = "1.0.0"', content)
        self.assertIn('agentflow = "ship.cli:main"', content)
        self.assertIn('ship = "ship.cli:main"', content)
        self.assertIn('requires-python = ">=3.10"', content)
        self.assertIn('dependencies = []', content)

    def test_cli_version_and_help(self):
        """ship --version and ship --help return expected information."""
        # Version
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            ret = ship_cli_main(["--version"])
        finally:
            sys.stdout = old_stdout
        self.assertEqual(ret, 0)
        self.assertIn("1.0.0", buf.getvalue())

        # Help
        buf = io.StringIO()
        try:
            sys.stdout = buf
            ret = ship_cli_main(["--help"])
        finally:
            sys.stdout = old_stdout
        self.assertEqual(ret, 0)
        self.assertIn("AgentFlow SDLC CLI v1.0.0", buf.getvalue())
        self.assertIn("agentflow status", buf.getvalue())
        self.assertIn("agentflow turn", buf.getvalue())
        self.assertIn("ship mcp", buf.getvalue())

    def test_cli_subcommands_and_flag_parity(self):
        """Subcommands execute equivalent lifecycle operations as legacy flags."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            # Initialize git repository
            for args in [("init", "-b", "main"), ("config", "user.name", "Dev"),
                         ("config", "user.email", "dev@example.com"), ("config", "commit.gpgsign", "false")]:
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            (root / "README.md").write_text("# Project\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)

            # 1. ship turn / ship next-turn / ship next
            buf = io.StringIO()
            old_stdout = sys.stdout
            try:
                sys.stdout = buf
                ret = ship_cli_main(["next", "--path", str(root)])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("TURN CONTRACT: DESIGN", buf.getvalue())
            self.assertIn("SUGGESTED INVOCATION:", buf.getvalue())

            # 2. ship doctor
            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["doctor", "--path", str(root)])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("Ship 1.0.0", buf.getvalue())
            self.assertIn("OK python:", buf.getvalue())

            # 3. ship status on unready repo with --json
            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["status", "--json", "--path", str(root)])
            finally:
                sys.stdout = old_stdout
            self.assertNotEqual(ret, 0)
            status_json = json.loads(buf.getvalue())
            self.assertFalse(status_json["ready"])
            self.assertEqual(status_json["gate"], "design")

            # 4. Specialist tool subcommands
            # ship tdd
            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["tdd", "--files"])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("TDD Audit & Verification Report", buf.getvalue())

            # ship simplify
            (root / "example.py").write_text("# simplify: In-memory list. Ceiling: 100 items. Upgrade: SQLite.\n")
            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["simplify", str(root)])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("Operational Ceiling", buf.getvalue())

            # ship spike
            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["spike", "--cmd", "echo ok", "--iterations", "3", "--warmup", "1"])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("Empirical Results", buf.getvalue())

            # 5. ship checkpoint and ship rollback
            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["checkpoint", "design", "--change", "feat-test", "--path", str(root)])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("Created checkpoint for design", buf.getvalue())

            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["rollback", "design", "--change", "feat-test", "--path", str(root), "--force"])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("rolled back", buf.getvalue())

            # 6. ship trailers
            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["trailers", "feat-test", "--path", str(root)])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("Ship-Change: feat-test", buf.getvalue())
            self.assertIn("Ship-Design: BLOCKED", buf.getvalue())

            # 7. ship record-review
            rev_file = root / "review_report.json"
            rev_file.write_text(json.dumps({
                "reviewer": "judge",
                "status": "complete",
                "verdict": "PASS",
                "findings": [],
                "coverage": ["all"],
                "questions": [],
                "routing_notes": []
            }))
            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["record-review", str(rev_file), "--change", "feat-test", "--path", str(root)])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("Recorded review report", buf.getvalue())

            # 8. ship verify
            (root / "openspec" / "changes" / "feat-test").mkdir(parents=True, exist_ok=True)
            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["verify", "feat-test", "--tier", "grounding", "--path", str(root)])
            finally:
                sys.stdout = old_stdout
            # An unbound review is inconclusive, not a successful verification.
            self.assertEqual(ret, 1)
            self.assertIn("INCONCLUSIVE", buf.getvalue())
            self.assertIn("INDEPENDENT VERIFICATION SUMMARY", buf.getvalue())

            # 9. ship resume
            buf = io.StringIO()
            try:
                sys.stdout = buf
                ret = ship_cli_main(["resume", "feat-test", "--path", str(root)])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("Halt blocker cleared and autonomy resumed", buf.getvalue())

    def test_skills_and_src_byte_for_byte_parity(self):
        """All mapped files between src/ship/ and skills/ must be 100% byte-for-byte identical."""
        sync_script = ROOT / "scripts" / "sync_skills.py"
        self.assertTrue(sync_script.exists())
        res = subprocess.run(
            [sys.executable, str(sync_script), "--check", "--path", str(ROOT)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"Parity mismatch between src/ship and skills/:\n{res.stderr}\n{res.stdout}\nRun 'python3 scripts/sync_skills.py' to synchronize.",
        )
        self.assertIn("Parity check passed", res.stdout)


    def test_agentflow_extended_subcommands(self):
        """Extended agentflow subcommands (budget, events replay, benchmark) execute cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            # 1. agentflow budget show
            buf = io.StringIO()
            old_stdout = sys.stdout
            try:
                sys.stdout = buf
                ret = ship_cli_main(["budget", "show", "--path", str(root)])
            finally:
                sys.stdout = old_stdout
            self.assertEqual(ret, 0)
            self.assertIn("RESOURCE BUDGET REPORT", buf.getvalue())

            # 2. agentflow events replay --help
            buf = io.StringIO()
            try:
                sys.stdout = buf
                with self.assertRaises(SystemExit) as ctx:
                    ship_cli_main(["events", "replay", "--help"])
                self.assertEqual(ctx.exception.code, 0)
            finally:
                sys.stdout = old_stdout
            self.assertIn("events replay", buf.getvalue())

            # 3. agentflow benchmark --help
            buf = io.StringIO()
            try:
                sys.stdout = buf
                with self.assertRaises(SystemExit) as ctx:
                    ship_cli_main(["benchmark", "--help"])
                self.assertEqual(ctx.exception.code, 0)
            finally:
                sys.stdout = old_stdout
            self.assertIn("benchmark", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
