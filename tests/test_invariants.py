"""Formal Invariant Tests for AgentFlow Independent Verification and Convergence Governance.

Enforces the 8 foundational axioms:
1. No evidence → no verification.
2. No independent verification → no gate pass.
3. VERIFIED ≠ PASS — verification establishes a claim; the gate evaluates the complete policy.
4. Every remediation attempt gets a new evidence set; don't mutate the evidence that caused the failure.
5. Every loop iteration is bounded and recorded.
6. No progress / oscillation / repeated failure → halt.
7. A halted workflow cannot silently transition to delivery.
8. The final gate decision references the exact verified evidence and revision.

Guarantees:
Autonomy is permitted to continue only while the system can demonstrate bounded progress toward a verifiable state.
"""

import json
from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.convergence import ConvergenceController, evaluate_convergence
from ship.lifecycle.gates import determine_lifecycle_state, validate_delivery_readiness
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.models import StagnationType
from ship.lifecycle.verification import (
    execute_and_verify_tests,
    verify_review_grounding,
)


class TestArchitecturalInvariants(unittest.TestCase):

    def test_invariant_1_no_evidence_no_verification(self):
        """Invariant 1: No evidence → no verification.
        An independent verifier cannot verify absence of evidence.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Empty / missing test command yields NOT_VERIFIED
            rec = execute_and_verify_tests(tmppath, test_command="", claimed_evidence={})
            self.assertEqual(rec.verdict, "NOT_VERIFIED")
            self.assertIn("No test command configured", rec.findings[0])

            # Malformed / empty review report yields NOT_VERIFIED
            rec_review = verify_review_grounding({}, tmppath)
            self.assertEqual(rec_review.verdict, "INCONCLUSIVE")

            rec_invalid = verify_review_grounding(None, tmppath)  # type: ignore
            self.assertEqual(rec_invalid.verdict, "NOT_VERIFIED")

    def test_invariant_2_no_independent_verification_no_gate_pass(self):
        """Invariant 2: No independent verification → no gate pass.
        Delivery readiness cannot clear if independent verification is failing or unverified.
        """
        pkg = {"change": "c-invar", "total_tasks": 1, "completed_tasks": 1, "pending_tasks": 0, "has_tasks": True}
        # Change has failed verification in ledger
        change = {
            "change_id": "c-invar",
            "turns": [{"skill": "tdd"}],
            "blockers": ["Verification: Execution failed"],
            "verification": {"execution": {"verdict": "NOT_VERIFIED", "findings": ["test_fail"]}},
        }
        report = {
            "status": "complete", "reviewer": "judge", "is_judge": True,
            "change": "c-invar", "findings": [], "critical_or_high_count": 0,
            "test_evidence_passed": True, "verdict": "PASS", "judge_report_valid": True,
        }
        gate, state_key, reason = validate_delivery_readiness(
            review_report=report, active_pkg=pkg, git_info={"is_git": False}, active_change=change,
        )
        self.assertEqual(gate, "review")
        self.assertEqual(state_key, "VERIFICATION_FAILED")
        self.assertIn("Blocked by independent verification failure", reason)

    def test_invariant_3_verified_is_not_pass(self):
        """Invariant 3: VERIFIED ≠ PASS.
        Verification establishes a technical claim; the gate evaluates the complete holistic policy.
        """
        # Independent verification is VERIFIED, but tasks are still pending (policy violation)
        pkg = {"change": "c-policy", "total_tasks": 2, "completed_tasks": 1, "pending_tasks": 1, "has_tasks": True, "next_task": "Task 2"}
        change = {
            "change_id": "c-policy",
            "turns": [{"skill": "tdd"}],
            "blockers": [],
            "verification": {"execution": {"verdict": "VERIFIED"}, "grounding": {"verdict": "VERIFIED"}},
        }
        report = {
            "status": "complete", "reviewer": "judge", "is_judge": True,
            "change": "c-policy", "findings": [], "critical_or_high_count": 0,
            "test_evidence_passed": True, "verdict": "PASS", "judge_report_valid": True,
        }
        gate, state_key, reason = validate_delivery_readiness(
            review_report=report, active_pkg=pkg, git_info={"is_git": False}, active_change=change,
        )
        # VERIFIED claim exists, but gate evaluates complete policy and returns implementation
        self.assertNotEqual(gate, "delivery")
        self.assertEqual(gate, "implementation")
        self.assertEqual(state_key, "TDD_ACTIVE")

    def test_invariant_4_remediation_gets_new_evidence_immutable_history(self):
        """Invariant 4: Every remediation attempt gets a new evidence set; don't mutate the evidence that caused the failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create change
            FileLedgerStore.mutate_change(
                tmppath, "c-rem",
                lambda entry: entry.update({"phase": "implementation", "turns": []}),
                set_active=True,
            )

            # Turn 1: Failing test run
            FileLedgerStore.record_test_run(
                tmppath,
                test_summary={"exit_code": 1, "passed": False, "failed_count": 1, "tests_run": 10},
                change_id="c-rem",
            )
            ledger_1 = FileLedgerStore.load(tmppath, auto_sync=False)
            t1 = ledger_1["changes"]["c-rem"]["turns"][0]
            self.assertFalse(t1["evidence"]["tests_passed"])
            self.assertEqual(t1["evidence"]["failed_count"], 1)

            # Turn 2: Remediation test run (new evidence set)
            FileLedgerStore.record_test_run(
                tmppath,
                test_summary={"exit_code": 0, "passed": True, "failed_count": 0, "tests_run": 10},
                change_id="c-rem",
            )
            ledger_2 = FileLedgerStore.load(tmppath, auto_sync=False)
            turns = ledger_2["changes"]["c-rem"]["turns"]
            self.assertEqual(len(turns), 2)

            # Invariant check: Turn 1 evidence is IMMUTABLE and preserved
            self.assertFalse(turns[0]["evidence"]["tests_passed"])
            self.assertEqual(turns[0]["evidence"]["failed_count"], 1)

            # Turn 2 has distinct fresh evidence set
            self.assertTrue(turns[1]["evidence"]["tests_passed"])
            self.assertEqual(turns[1]["evidence"]["failed_count"], 0)

    def test_invariant_5_every_loop_iteration_bounded_and_recorded(self):
        """Invariant 5: Every loop iteration is bounded and recorded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            FileLedgerStore.mutate_change(
                tmppath, "c-bound",
                lambda entry: entry.update({"phase": "implementation", "turns": []}),
                set_active=True,
            )

            for i in range(3):
                FileLedgerStore.record_test_run(
                    tmppath,
                    test_summary={"exit_code": 1, "passed": False, "failures": [f"err-{i}"], "tests_run": 5},
                    change_id="c-bound",
                )

            ledger = FileLedgerStore.load(tmppath, auto_sync=False)
            change = ledger["changes"]["c-bound"]
            self.assertEqual(len(change["turns"]), 3)
            self.assertEqual(change["turns"][0]["turn_id"], "turn-001")
            self.assertEqual(change["turns"][1]["turn_id"], "turn-002")
            self.assertEqual(change["turns"][2]["turn_id"], "turn-003")

            # Convergence Controller evaluates bounded attempts
            controller = ConvergenceController(config={"max_remediation_attempts": 3})
            converged, reason = controller.certify_convergence(change)
            self.assertFalse(converged)
            self.assertIn("Maximum remediation attempts exceeded", reason)

    def test_invariant_6_no_progress_oscillation_repeated_failure_halts(self):
        """Invariant 6: No progress / oscillation / repeated failure → halt."""
        # Consecutive identical patches submitted
        turns = [
            {"skill": "tdd", "inputs": {"failed_tiers": ["execution"], "tree_fingerprint": "hash-stagnant"}},
            {"skill": "tdd", "inputs": {"failed_tiers": ["execution"], "tree_fingerprint": "hash-stagnant"}},
        ]
        change = {"change_id": "c-halt", "turns": turns, "blockers": []}
        status = evaluate_convergence(change)
        self.assertTrue(status.is_halted)
        self.assertEqual(status.stagnation_type, StagnationType.SAME_PATCH.value)

    def test_invariant_7_halted_workflow_cannot_silently_transition_to_delivery(self):
        """Invariant 7: A halted workflow cannot silently transition to delivery."""
        pkg = {"change": "c-gate-halt", "total_tasks": 1, "completed_tasks": 1, "pending_tasks": 0, "has_tasks": True}
        # Change has active halt blocker
        change = {
            "change_id": "c-gate-halt",
            "turns": [{"skill": "tdd"}],
            "blockers": ["Halt: NON_CONVERGING_REMEDIATION: Identical patch submitted 2 times"],
            "verification": {"execution": {"verdict": "VERIFIED"}},
        }
        report = {
            "status": "complete", "reviewer": "judge", "is_judge": True,
            "change": "c-gate-halt", "findings": [], "critical_or_high_count": 0,
            "test_evidence_passed": True, "verdict": "PASS", "judge_report_valid": True,
        }
        gate, state_key, reason = validate_delivery_readiness(
            review_report=report, active_pkg=pkg, git_info={"is_git": False}, active_change=change,
        )
        self.assertEqual(gate, "convergence")
        self.assertEqual(state_key, "AUTONOMY_HALTED")
        self.assertIn("Autonomy halted", reason)

    def test_invariant_8_final_gate_decision_references_exact_evidence_and_revision(self):
        """Invariant 8: The final gate decision references the exact verified evidence and revision."""
        pkg = {"change": "c-drift", "total_tasks": 1, "completed_tasks": 1, "pending_tasks": 0, "has_tasks": True}
        change = {
            "change_id": "c-drift",
            "revision_counter": 5,
            "turns": [{"skill": "tdd"}],
            "blockers": [],
            "verification": {"execution": {"verdict": "VERIFIED"}},
        }
        # Review report snapshot is tied to a specific commit SHA
        report = {
            "status": "complete", "reviewer": "judge", "is_judge": True,
            "change": "c-drift", "findings": [], "critical_or_high_count": 0,
            "test_evidence_passed": True, "verdict": "PASS", "judge_report_valid": True,
            "snapshot_sha": "a1b2c3d4e5f67890",
        }
        # Git working tree is at a DIFFERENT commit SHA (unreviewed drift!)
        git_drift = {
            "is_git": True,
            "commit": "ffffffffffffffff",
            "is_clean": True,
        }
        gate, state_key, reason = validate_delivery_readiness(
            review_report=report, active_pkg=pkg, git_info=git_drift, active_change=change,
        )
        self.assertEqual(gate, "review")
        self.assertEqual(state_key, "REVIEW_ACTIVE")
        self.assertIn("does not match current commit", reason)
