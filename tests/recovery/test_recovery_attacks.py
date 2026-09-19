"""Adversarial recovery tests: bypassing convergence halts, verifying required human escalation trails, state corruption resistance."""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.convergence import ConvergenceController
from ship.lifecycle.gates import validate_delivery_readiness
from ship.lifecycle.ledger import FileLedgerStore


class TestRecoveryAttacks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "attack-rec-change"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {
                self.change_id: {
                    "turns": [],
                    "blockers": ["Halt: NON_CONVERGING_REMEDIATION: Repeated verification failures"],
                }
            },
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bypass_convergence_halt_fails(self):
        """Attack: Autonomous agent attempts to pass delivery gate while halt blocker is active."""
        ledger = FileLedgerStore.load(self.repo_root)
        change = ledger["changes"][self.change_id]

        # Check delivery readiness: presence of Halt: blocker forces state to 'halted'
        pkg = {"has_tasks": True, "total_tasks": 1, "completed_tasks": 1, "pending_tasks": 0}
        state, reason_code, message = validate_delivery_readiness(
            review_report={"status": "pass"},
            active_pkg=pkg,
            git_info={},
            active_change=change,
        )
        self.assertEqual(state, "convergence")
        self.assertEqual(reason_code, "AUTONOMY_HALTED")
        self.assertIn("NON_CONVERGING_REMEDIATION", message)

        # Check convergence controller certification
        ctrl = ConvergenceController()
        converged, cert_msg = ctrl.certify_convergence(change)
        self.assertFalse(converged)
        self.assertIn("NON_CONVERGING_REMEDIATION", cert_msg)

    def test_resume_requires_human_escalation_trail(self):
        """Recovery: Clearing halt blocker via resume_change records human intervention turn."""
        updated_change = FileLedgerStore.resume_change(
            self.repo_root,
            change_id=self.change_id,
        )
        # Verify blocker cleared
        self.assertEqual(len(updated_change.get("blockers", [])), 0)

        # Check ledger: blocker cleared and human intervention turn recorded
        ledger = FileLedgerStore.load(self.repo_root)
        change = ledger["changes"][self.change_id]
        self.assertEqual(len(change.get("blockers", [])), 0)

        turns = change.get("turns", [])
        self.assertTrue(len(turns) > 0)
        latest = turns[-1]
        self.assertEqual(latest["harness"], "human-supervisor")
        self.assertEqual(latest["skill"], "human")
        self.assertTrue(latest["state_delta"]["halt_cleared"])

    def test_tampered_corrupt_ledger_handled_safely(self):
        """Attack: Ledger is corrupted with invalid JSON or malformed schema."""
        ledger_path = FileLedgerStore.get_ledger_path(self.repo_root)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text("{ THIS_IS_NOT_VALID_JSON !!!")

        # Loading damaged ledger must raise clear error and never silently overwrite
        with self.assertRaises(ValueError) as ctx:
            FileLedgerStore.load(self.repo_root)
        self.assertIn("Cannot read ledger", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
