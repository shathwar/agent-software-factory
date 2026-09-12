"""Unit tests for ship lifecycle inspector (inspect_lifecycle.py)."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSPECT_LIFECYCLE = ROOT / "skills" / "ship" / "scripts" / "inspect_lifecycle.py"

sys.path.insert(0, str(INSPECT_LIFECYCLE.parent))
import inspect_lifecycle


class TestInspectLifecycle(unittest.TestCase):
    def test_gate1_empty_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            res = inspect_lifecycle.evaluate_repository(Path(tmpdir))
            self.assertEqual(res["gate"], "GATE 1: SPECIFICATION & DESIGN")
            self.assertEqual(res["state_key"], "INITIAL_PROPOSAL")
            self.assertIn("Run '/adversarial-design'", res["next_action"])

    def test_gate1b_active_spike(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            spike_dir = tmppath / ".scratch" / "spike_redis_perf"
            spike_dir.mkdir(parents=True)

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 1b: EMPIRICAL SPIKE ACTIVE")
            self.assertEqual(res["state_key"], "SPIKE_ACTIVE")
            self.assertIn("spike_redis_perf", res["next_action"])

    def test_gate1_adr_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            adr_dir = tmppath / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "ADR-0001-events.md").write_text("# ADR\n**Status**: ACCEPTED\n")

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 1: SPECIFICATION & DESIGN")
            self.assertEqual(res["state_key"], "ADR_ACCEPTED")
            self.assertEqual(len(res["adrs"]), 1)
            self.assertEqual(res["adrs"][0]["status"], "ACCEPTED")

    def test_gate2_tdd_active_with_pending_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "webhooks"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "proposal.md").write_text("# Webhooks\n")
            (pkg_dir / "tasks.md").write_text(
                "# Tasks\n"
                "- [x] 1. Setup endpoint\n"
                "- [ ] 2. Handle retries with jitter\n"
                "- [ ] 3. Verify signature\n"
            )

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 2: IMPLEMENTATION (TDD + PONYTAIL)")
            self.assertEqual(res["state_key"], "TDD_ACTIVE")
            self.assertIn("1/3 tasks complete", res["next_action"])
            self.assertIn("2. Handle retries with jitter", res["next_action"])

    def test_gate3_audit_active_when_tasks_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "webhooks"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text(
                "# Tasks\n"
                "- [x] 1. Setup endpoint\n"
                "- [x] 2. Handle retries with jitter\n"
            )

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
            self.assertIn("review-loop mode", res["next_action"])

    def test_gate4_ready_to_ship_with_passed_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "webhooks"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text(
                "# Tasks\n"
                "- [x] 1. All done\n"
            )
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            (scratch_dir / "review_report.json").write_text(
                json.dumps({"reviewer": "judge", "status": "pass", "findings": []})
            )

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 4: READY TO SHIP")
            self.assertEqual(res["state_key"], "DELIVERY_READY")
            self.assertIn("Delivery Walkthrough", res["next_action"])

    def test_cli_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [sys.executable, str(INSPECT_LIFECYCLE), "--path", str(tmpdir), "--format", "json"]
            run = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0)
            data = json.loads(run.stdout)
            self.assertEqual(data["gate"], "GATE 1: SPECIFICATION & DESIGN")
            self.assertEqual(data["state_key"], "INITIAL_PROPOSAL")


if __name__ == "__main__":
    unittest.main()
