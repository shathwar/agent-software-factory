"""Unit tests for the independent verification engine (verification.py, models.py, ledger.py, gates.py)."""

import json
from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.models import VerificationRecord, VerificationTier, LifecyclePhase
from ship.lifecycle.verification import (
    parse_line_range,
    verify_finding_grounding,
    verify_review_grounding,
    execute_and_verify_tests,
    verify_test_quality,
    verify_spec_coverage,
    run_gate_verification,
    format_verification_summary,
)
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.gates import validate_delivery_readiness, determine_lifecycle_state
from ship.lifecycle.turns import get_next_turn_contract


class TestParseLineRange(unittest.TestCase):
    def test_single_line(self):
        self.assertEqual(parse_line_range("L10"), (10, 10))
        self.assertEqual(parse_line_range("10"), (10, 10))

    def test_range(self):
        self.assertEqual(parse_line_range("L10-L25"), (10, 25))
        self.assertEqual(parse_line_range("10-25"), (10, 25))

    def test_invalid_formats(self):
        with self.assertRaises(ValueError):
            parse_line_range("invalid")
        with self.assertRaises(ValueError):
            parse_line_range("L25-L10")  # inverted


class TestFindingGrounding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        # Create a sample source file
        self.src_file = self.root / "src" / "sample.py"
        self.src_file.parent.mkdir(parents=True, exist_ok=True)
        self.src_file.write_text(
            "def calculate_tax(amount):\n"
            "    if amount <= 0:\n"
            "        return 0.0\n"
            "    rate = 0.15\n"
            "    return amount * rate\n"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_grounded_finding(self):
        finding = {
            "id": "FINDING-001",
            "file": "src/sample.py",
            "line": "L2-L3",
            "evidence": "if amount <= 0:\n    return 0.0",
        }
        ok, reason = verify_finding_grounding(finding, self.root)
        self.assertTrue(ok)
        self.assertIn("Evidence grounded", reason)

    def test_nonexistent_file(self):
        finding = {
            "id": "FINDING-002",
            "file": "src/nonexistent.py",
            "line": "L1",
            "evidence": "foo()",
        }
        ok, reason = verify_finding_grounding(finding, self.root)
        self.assertFalse(ok)
        self.assertIn("does not exist", reason)

    def test_line_beyond_file(self):
        finding = {
            "id": "FINDING-003",
            "file": "src/sample.py",
            "line": "L50-L60",
            "evidence": "foo()",
        }
        ok, reason = verify_finding_grounding(finding, self.root)
        self.assertFalse(ok)
        self.assertIn("begins beyond file length", reason)

    def test_ungrounded_evidence_snippet(self):
        finding = {
            "id": "FINDING-004",
            "file": "src/sample.py",
            "line": "L1-L3",
            "evidence": "completely_fictitious_call_never_existed()",
        }
        ok, reason = verify_finding_grounding(finding, self.root)
        self.assertFalse(ok)
        self.assertIn("Evidence quote not found", reason)


class TestReviewGrounding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "auth.py"
        self.src.write_text("def check_token(token):\n    if not token:\n        raise ValueError('Missing token')\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_review_verified(self):
        report = {
            "reviewer": "judge",
            "status": "complete",
            "findings": [],
            "verdict": "PASS",
        }
        rec = verify_review_grounding(report, self.root)
        self.assertEqual(rec.verdict, "VERIFIED")
        self.assertEqual(rec.gate, "review")
        self.assertEqual(rec.tier, "grounding")

    def test_review_with_grounded_findings(self):
        report = {
            "reviewer": "judge",
            "status": "complete",
            "findings": [
                {
                    "id": "FINDING-001",
                    "file": "auth.py",
                    "line": "L2-L3",
                    "evidence": "if not token:\n    raise ValueError('Missing token')",
                }
            ],
        }
        rec = verify_review_grounding(report, self.root)
        self.assertEqual(rec.verdict, "VERIFIED")
        self.assertEqual(rec.score, 1.0)

    def test_review_with_ungrounded_findings(self):
        report = {
            "reviewer": "judge",
            "status": "complete",
            "findings": [
                {
                    "id": "FINDING-001",
                    "file": "auth.py",
                    "line": "L1-L2",
                    "evidence": "sql_inject_query = 'DROP TABLE users'",
                }
            ],
        }
        rec = verify_review_grounding(report, self.root)
        self.assertEqual(rec.verdict, "NOT_VERIFIED")
        self.assertEqual(rec.score, 0.0)


class TestExecuteAndVerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_passing_test_command(self):
        rec = execute_and_verify_tests(self.root, "true")
        self.assertEqual(rec.verdict, "VERIFIED")
        self.assertEqual(rec.gate, "implementation")
        self.assertEqual(rec.tier, "execution")
        self.assertEqual(rec.metadata["exit_code"], 0)

    def test_failing_test_command(self):
        rec = execute_and_verify_tests(self.root, "false")
        self.assertEqual(rec.verdict, "NOT_VERIFIED")
        self.assertNotEqual(rec.metadata["exit_code"], 0)

    def test_empty_test_command(self):
        rec = execute_and_verify_tests(self.root, "")
        self.assertEqual(rec.verdict, "NOT_VERIFIED")
        self.assertIn("No test command", rec.findings[0])

    def test_contradiction_detection(self):
        # Claimed passing, but actual exit is failure
        claimed = {"tests_passed": True, "exit_code": 0}
        rec = execute_and_verify_tests(self.root, "exit 1", claimed_evidence=claimed)
        self.assertEqual(rec.verdict, "NOT_VERIFIED")
        self.assertTrue(any("CONTRADICTION DETECTED" in f for f in rec.findings))


class TestSpecCoverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_specs_passes(self):
        rec = verify_spec_coverage(self.root, "test-change")
        self.assertEqual(rec.verdict, "VERIFIED")

    def test_specs_without_tests_fails(self):
        specs_dir = self.root / "openspec" / "changes" / "feature-x" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        (specs_dir / "auth.md").write_text("# Spec\nRequirements: R1, R2")

        rec = verify_spec_coverage(self.root, "feature-x")
        self.assertEqual(rec.verdict, "NOT_VERIFIED")
        self.assertIn("no test files were found", rec.findings[0])

    def test_specs_with_tests_passes(self):
        specs_dir = self.root / "openspec" / "changes" / "feature-x" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        (specs_dir / "auth.md").write_text("# Spec")

        tests_dir = self.root / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "test_auth.py").write_text("def test_ok(): pass")

        rec = verify_spec_coverage(self.root, "feature-x")
        self.assertEqual(rec.verdict, "VERIFIED")


class TestLedgerVerification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        FileLedgerStore.save(self.root, {
            "version": 1,
            "active_change_id": "feat-1",
            "changes": {
                "feat-1": {
                    "change_id": "feat-1",
                    "phase": "review",
                    "task_status": {"total": 1, "completed": 1, "pending": 0},
                    "blockers": [],
                    "revision_counter": 0,
                    "evidence": {},
                    "verification": {},
                    "checkpoints": {},
                    "turns": [],
                }
            }
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_passing_verification(self):
        record = VerificationRecord(
            claim="Tests pass",
            gate="implementation",
            tier="execution",
            verdict="VERIFIED",
            method="test",
            findings=["Exit code 0"],
        )
        entry = FileLedgerStore.record_verification(self.root, {"execution": record}, change_id="feat-1")
        self.assertIn("execution", entry["verification"])
        self.assertEqual(entry["verification"]["execution"]["verdict"], "VERIFIED")
        self.assertEqual(len(entry["blockers"]), 0)
        self.assertEqual(entry["turns"][-1]["skill"], "verification")

    def test_record_failing_verification_sets_blocker(self):
        record = VerificationRecord(
            claim="Tests pass",
            gate="implementation",
            tier="execution",
            verdict="NOT_VERIFIED",
            method="test",
            findings=["Exit code 1"],
        )
        entry = FileLedgerStore.record_verification(self.root, {"execution": record}, change_id="feat-1")
        self.assertIn("Verification: execution verification tier(s) failed", entry["blockers"])


class TestGateVerificationIntegration(unittest.TestCase):
    def test_gate_blocks_on_verification_failure_in_ledger(self):
        active_change = {
            "change_id": "c1",
            "blockers": ["Verification: execution verification tier(s) failed"],
            "verification": {"execution": {"verdict": "NOT_VERIFIED", "findings": ["test failed"]}},
        }
        pkg = {"change": "c1", "total_tasks": 1, "completed_tasks": 1, "pending_tasks": 0, "has_tasks": True}
        gate, state_key, reason = validate_delivery_readiness(
            review_report={"status": "complete", "reviewer": "judge", "findings": [], "verdict": "PASS"},
            active_pkg=pkg,
            git_info={"is_git": False},
            active_change=active_change,
        )
        self.assertEqual(gate, "review")
        self.assertEqual(state_key, "VERIFICATION_FAILED")
        self.assertIn("verification failure", reason)

    def test_turn_contract_for_verification_failed(self):
        active_change = {
            "change_id": "c1",
            "blockers": ["Verification: execution verification tier(s) failed"],
            "verification": {"execution": {"verdict": "NOT_VERIFIED", "findings": ["test failed"]}},
        }
        repo_eval = {
            "target_change": "c1",
            "state_key": "VERIFICATION_FAILED",
            "active_change": active_change,
            "git": {},
            "config": {},
        }
        contract = get_next_turn_contract(repo_eval)
        self.assertEqual(contract.phase, "VERIFICATION_FAILED")
        self.assertEqual(contract.skill, "tdd")  # routes execution failure to tdd craftsperson
        self.assertIn("execution", contract.inputs["failed_tiers"])


if __name__ == "__main__":
    unittest.main()
