"""Unit tests for Convergence Control and Anti-Infinite Loop Guardrails (convergence.py, gates.py, turns.py, ledger.py)."""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.models import StagnationType
from ship.lifecycle.convergence import (
    evaluate_convergence,
    detect_same_evidence,
    detect_same_finding,
    detect_same_patch,
    detect_same_verifier_failure,
    detect_oscillating_state,
)
from ship.lifecycle.gates import determine_lifecycle_state, validate_delivery_readiness
from ship.lifecycle.turns import get_next_turn_contract
from ship.lifecycle.ledger import FileLedgerStore


class TestStagnationDetectors(unittest.TestCase):
    def test_same_evidence_detection(self):
        # 1. Below threshold
        turns = [{"evidence": {"test_output": "AssertionError: expected 1 got 0"}}]
        detected, _ = detect_same_evidence(turns, max_same=2)
        self.assertFalse(detected)

        # 2. Duplicate evidence
        turns.append({"evidence": {"test_output": "AssertionError: expected 1 got 0"}})
        detected, msg = detect_same_evidence(turns, max_same=2)
        self.assertTrue(detected)
        self.assertIn("Identical evidence payload submitted 2 consecutive times", msg)

        # 3. New different evidence resets
        turns.append({"evidence": {"test_output": "KeyError: 'token'"}})
        detected, _ = detect_same_evidence(turns, max_same=2)
        self.assertFalse(detected)

    def test_same_finding_detection(self):
        finding_a = [{"id": "SEC-001", "file": "auth.py", "line": "L12"}]
        turns = [
            {"skill": "review", "evidence": {"findings": finding_a}},
            {"skill": "review", "evidence": {"findings": finding_a}},
        ]
        detected, msg = detect_same_finding(turns, max_same=2)
        self.assertTrue(detected)
        self.assertIn("Identical defect finding(s) persisted", msg)

    def test_same_patch_detection(self):
        turns = [
            {"skill": "tdd", "inputs": {"tree_fingerprint": "hash-abc-123"}},
            {"skill": "tdd", "inputs": {"tree_fingerprint": "hash-abc-123"}},
        ]
        detected, msg = detect_same_patch(turns, max_same=2)
        self.assertTrue(detected)
        self.assertIn("Identical working tree diff", msg)

    def test_same_verifier_failure_detection(self):
        verif_fail = {
            "execution": {"verdict": "NOT_VERIFIED", "findings": ["exit code 1", "test_login failed"]}
        }
        turns = [
            {"skill": "verification", "evidence": verif_fail},
            {"skill": "verification", "evidence": verif_fail},
        ]
        detected, msg = detect_same_verifier_failure(turns, max_same=2)
        self.assertTrue(detected)
        self.assertIn("Independent verification failed with identical reason", msg)

    def test_oscillating_state_detection(self):
        # A -> B -> A -> B thrashing cycle
        turns = [
            {"skill": "tdd"},
            {"skill": "review"},
            {"skill": "tdd"},
            {"skill": "review"},
        ]
        detected, msg = detect_oscillating_state(turns)
        self.assertTrue(detected)
        self.assertIn("Oscillating state detected (tdd ⇆ review)", msg)

        # Progressive non-oscillating trajectory
        clean_turns = [
            {"skill": "design"},
            {"skill": "tdd"},
            {"skill": "review"},
            {"skill": "delivery"},
        ]
        detected, _ = detect_oscillating_state(clean_turns)
        self.assertFalse(detected)


class TestConvergenceBudgets(unittest.TestCase):
    def test_max_total_turns_budget(self):
        turns = [{"skill": "tdd", "evidence": {"step": i}} for i in range(26)]
        change = {"change_id": "feat-1", "turns": turns, "blockers": []}
        cfg = {"convergence": {"max_total_turns": 25}}
        status = evaluate_convergence(change, config=cfg)
        self.assertTrue(status.is_halted)
        self.assertEqual(status.stagnation_type, StagnationType.BUDGET_EXCEEDED.value)
        self.assertIn("Total turns limit exceeded", status.reason)

    def test_max_remediation_attempts_budget(self):
        turns = [
            {"skill": "tdd", "inputs": {"failed_tiers": ["execution"]}},
            {"skill": "tdd", "inputs": {"failed_tiers": ["execution"]}},
            {"skill": "tdd", "inputs": {"failed_tiers": ["execution"]}},
        ]
        change = {"change_id": "feat-2", "turns": turns, "blockers": []}
        cfg = {"convergence": {"max_remediation_attempts": 3}}
        status = evaluate_convergence(change, config=cfg)
        self.assertTrue(status.is_halted)
        self.assertIn("Maximum remediation attempts exceeded", status.reason)

    def test_cost_ceiling_budget(self):
        turns = [
            {"skill": "review", "evidence": {"cost_dollars": 6.50}},
            {"skill": "review", "evidence": {"cost_dollars": 4.25}},
        ]
        change = {"change_id": "feat-3", "turns": turns, "blockers": []}
        cfg = {"convergence": {"max_cost_dollars": 10.0}}
        status = evaluate_convergence(change, config=cfg)
        self.assertTrue(status.is_halted)
        self.assertIn("Maximum cost ceiling exceeded", status.reason)


class TestGateAndTurnIntegration(unittest.TestCase):
    def test_gate_halts_autonomy_when_stagnation_detected(self):
        # 2 identical verifier failures
        verif_fail = {
            "execution": {"verdict": "NOT_VERIFIED", "findings": ["test_payment failed"]}
        }
        turns = [
            {"skill": "verification", "evidence": verif_fail},
            {"skill": "verification", "evidence": verif_fail},
        ]
        change = {
            "change_id": "feat-halt",
            "turns": turns,
            "blockers": [],
            "evidence": {"delivery": {"status": "PENDING"}},
        }
        gate, state_key, reason = determine_lifecycle_state(
            git_info={"commit": "abc"},
            adrs=[],
            openspec_packages=[],
            spikes=[],
            review_report=None,
            active_change=change,
        )
        self.assertEqual(gate, "convergence")
        self.assertEqual(state_key, "AUTONOMY_HALTED")
        self.assertIn("NON_CONVERGING_REMEDIATION", reason)

    def test_turn_contract_routes_to_human_supervisor(self):
        active_change = {
            "change_id": "feat-halt",
            "turns": [{"skill": "tdd"}, {"skill": "tdd"}],
            "blockers": ["Halt: NON_CONVERGING_REMEDIATION: Identical patch submitted 2 times"],
        }
        eval_data = {
            "target_change": "feat-halt",
            "state_key": "AUTONOMY_HALTED",
            "next_action": "Autonomy halted: NON_CONVERGING_REMEDIATION: Identical patch submitted 2 times",
            "active_change": active_change,
            "git": {},
            "config": {},
        }
        contract = get_next_turn_contract(eval_data)
        self.assertEqual(contract.phase, "AUTONOMY_HALTED")
        self.assertEqual(contract.skill, "human")
        self.assertEqual(contract.role, "Human Systems Lead & Escalation Arbiter")
        self.assertIn("agentflow resume feat-halt", contract.suggested_command)


class TestConvergenceControllerClosedLoop(unittest.TestCase):
    def test_controller_certifies_clean_verification(self):
        from ship.lifecycle.convergence import ConvergenceController
        controller = ConvergenceController(config={"max_total_turns": 10})
        change = {
            "change_id": "c-ok",
            "turns": [{"skill": "tdd"}, {"skill": "review"}],
            "blockers": [],
            "verification": {"execution": {"verdict": "VERIFIED"}},
        }
        converged, msg = controller.certify_convergence(change)
        self.assertTrue(converged)
        self.assertIn("Convergence certified", msg)

    def test_controller_halts_delivery_if_budget_exceeded_despite_passing_verification(self):
        from ship.lifecycle.convergence import ConvergenceController
        controller = ConvergenceController(config={"max_total_turns": 3})
        # 4 turns exceeds max_total_turns=3
        change = {
            "change_id": "c-over",
            "turns": [{"skill": "tdd"}, {"skill": "review"}, {"skill": "tdd"}, {"skill": "review"}],
            "blockers": [],
            "verification": {"execution": {"verdict": "VERIFIED"}},
        }
        converged, msg = controller.certify_convergence(change)
        self.assertFalse(converged)
        self.assertIn("Total turns limit exceeded", msg)

    def test_delivery_gate_passes_through_convergence_controller(self):
        pkg = {"change": "c-gate", "total_tasks": 1, "completed_tasks": 1, "pending_tasks": 0, "has_tasks": True}
        change = {
            "change_id": "c-gate",
            "turns": [{"skill": "tdd"}],
            "blockers": [],
            "verification": {"execution": {"verdict": "VERIFIED", "metadata": {
                "tests_run": 1, "exit_code": 0, "failed_count": 0}}},
        }
        report = {
            "status": "complete",
            "reviewer": "judge",
            "is_judge": True,
            "change": "c-gate",
            "findings": [],
            "critical_or_high_count": 0,
            "test_evidence_passed": True,
            "verdict": "PASS",
            "judge_report_valid": True,
        }
        gate, state_key, reason = validate_delivery_readiness(
            review_report=report,
            active_pkg=pkg,
            git_info={"is_git": False},
            active_change=change,
        )
        self.assertEqual(gate, "delivery")
        self.assertEqual(state_key, "DELIVERY_READY")


class TestResumeHaltRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        FileLedgerStore.save(self.root, {
            "version": 1,
            "active_change_id": "feat-resume",
            "changes": {
                "feat-resume": {
                    "change_id": "feat-resume",
                    "phase": "review",
                    "blockers": ["Halt: NON_CONVERGING_REMEDIATION: max attempts exceeded"],
                    "turns": [],
                }
            }
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_resume_change_clears_halt_blocker(self):
        entry = FileLedgerStore.resume_change(self.root, "feat-resume")
        self.assertNotIn("Halt: NON_CONVERGING_REMEDIATION: max attempts exceeded", entry["blockers"])
        self.assertEqual(entry["turns"][-1]["skill"], "human")
        self.assertTrue(entry["turns"][-1]["evidence"]["resumed"])


if __name__ == "__main__":
    unittest.main()
