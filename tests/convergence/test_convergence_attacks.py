"""Adversarial convergence tests: oscillation loops, identical evidence submission, budget breaches, autonomy halting."""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.convergence import (
    ConvergenceConfig,
    ConvergenceController,
    detect_oscillating_state,
    detect_same_evidence,
    detect_same_patch,
    evaluate_convergence,
)
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.models import StagnationType


class TestConvergenceAttacks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "attack-conv-change"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {"turns": [], "blockers": []}},
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_oscillating_remediation_attack_detected(self):
        """Attack: Agent oscillates between conflicting fixes (A -> B -> A -> B) to evade loop detection."""
        # Consecutive turns alternating state
        turns = [
            {"turn_id": "turn-001", "skill": "fix_jwt", "state_delta": {"auth_mode": "jwt"}},
            {"turn_id": "turn-002", "skill": "fix_session", "state_delta": {"auth_mode": "session"}},
            {"turn_id": "turn-003", "skill": "fix_jwt", "state_delta": {"auth_mode": "jwt"}},
            {"turn_id": "turn-004", "skill": "fix_session", "state_delta": {"auth_mode": "session"}},
        ]
        detected, msg = detect_oscillating_state(turns)
        self.assertTrue(detected)
        self.assertIn("Oscillating state detected", msg)

    def test_same_evidence_loop_attack_detected(self):
        """Attack: Agent repeatedly submits identical failing evidence without fixing code."""
        evidence_payload = {"failed_tests": ["test_auth_token"], "exit_code": 1}
        turns = [
            {"turn_id": "turn-001", "skill": "tdd", "evidence": evidence_payload},
            {"turn_id": "turn-002", "skill": "tdd", "evidence": evidence_payload},
        ]
        detected, msg = detect_same_evidence(turns, max_same=2)
        self.assertTrue(detected)
        self.assertIn("Identical evidence payload submitted", msg)

    def test_same_patch_loop_attack_detected(self):
        """Attack: Agent produces zero-delta or identical diffs consecutively."""
        patch_info = {"tree_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
        turns = [
            {"turn_id": "turn-001", "skill": "tdd", "state_delta": patch_info},
            {"turn_id": "turn-002", "skill": "tdd", "state_delta": patch_info},
        ]
        detected, msg = detect_same_patch(turns, max_same=2)
        self.assertTrue(detected)
        self.assertIn("Identical working tree diff", msg)

    def test_budget_exhaustion_halts_autonomy(self):
        """Attack: Agent tries to spin indefinitely by staying below individual stagnation triggers."""
        # Turns exceeding max_total_turns limit of 4
        turns = []
        for i in range(5):
            turns.append({
                "turn_id": f"turn-{i:03d}",
                "skill": "remediation",
                "state_delta": {"attempt": i},
            })

        change = {"turns": turns, "blockers": []}
        status = evaluate_convergence(change, config={"max_total_turns": 4})
        self.assertTrue(status.is_halted)
        self.assertEqual(status.stagnation_type, StagnationType.BUDGET_EXCEEDED.value)
        self.assertIn("Total turns limit exceeded", status.reason)


if __name__ == "__main__":
    unittest.main()
