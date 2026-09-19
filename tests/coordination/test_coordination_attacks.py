"""Adversarial coordination tests: expired lease reuse, token replay after handoff, checker modifying maker files, race conditions."""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.capabilities import CapabilityManager
from ship.lifecycle.coordination import CoordinationManager
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.models import CapabilityOperation, CoordinationConflictType
from ship.lifecycle.provenance import ProvenanceManager


class TestCoordinationAttacks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "attack-coord-change"
        self.change_dir = self.repo_root / ".ship" / "changes" / self.change_id
        self.change_dir.mkdir(parents=True, exist_ok=True)
        (self.change_dir / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 Auth\n- [ ] 1.2 Database\n")

        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })

        self.prov_mgr = ProvenanceManager(self.repo_root)
        self.coord_mgr = CoordinationManager(self.repo_root, self.change_id)
        self.cap_mgr = CapabilityManager(self.repo_root)

        self.maker = self.prov_mgr.register_identity("agent-maker", role="MAKER", change_id=self.change_id)
        self.checker = self.prov_mgr.register_identity("agent-checker", role="CHECKER", change_id=self.change_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_reuse_expired_lease_rejected(self):
        """Attack: Agent attempts to write Ring 2 code using an expired lease."""
        # Grant lease with 1 second TTL
        claim = self.coord_mgr.claim_task(
            task_id="1.1",
            owner_id="agent-maker",
            target_files=["src/auth.py"],
            ttl_seconds=-10,  # Pre-expired
        )
        self.cap_mgr.grant_capability(
            agent_id="agent-maker",
            operation=CapabilityOperation.WRITE,
            target="src/auth.py",
            task_id="1.1",
            change_id=self.change_id,
        )

        dec = self.cap_mgr.evaluate_access(
            agent_id="agent-maker",
            operation=CapabilityOperation.WRITE,
            target="src/auth.py",
            task_id="1.1",
            change_id=self.change_id,
            lease_token=claim.lease.lease_token,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "LEASE_EXPIRED")

    def test_reuse_maker_token_after_handoff_rejected(self):
        """Attack: Maker hands off task to Checker, then Maker attempts to reuse the invalidated token."""
        # 1. Maker acquires lease
        claim = self.coord_mgr.claim_task(
            task_id="1.1",
            owner_id="agent-maker",
            target_files=["src/auth.py"],
        )
        maker_token = claim.lease.lease_token

        # 2. Maker hands off to Checker (generates new token and transitions status to HANDED_OFF / ACTIVE)
        handoff = self.coord_mgr.handoff_task(
            task_id="1.1",
            from_owner="agent-maker",
            to_owner="agent-checker",
            lease_token=maker_token,
            reason="Ready for code review",
        )
        self.assertTrue(handoff.success)
        checker_token = handoff.lease.lease_token
        self.assertNotEqual(maker_token, checker_token)

        # 3. Maker tries to release or execute using old maker_token
        rel = self.coord_mgr.release_task(
            task_id="1.1",
            lease_token=maker_token,
            completed=True,
        )
        self.assertFalse(rel.success)
        self.assertIn("Invalid lease token", rel.error)

        # 4. Capability check using old maker_token fails
        self.cap_mgr.grant_capability(
            agent_id="agent-maker",
            operation=CapabilityOperation.WRITE,
            target="src/auth.py",
            task_id="1.1",
            change_id=self.change_id,
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="agent-maker",
            operation=CapabilityOperation.WRITE,
            target="src/auth.py",
            task_id="1.1",
            change_id=self.change_id,
            lease_token=maker_token,
        )
        self.assertFalse(dec.allowed)
        self.assertIn(dec.violation_code, ("LEASE_OWNER_MISMATCH", "LEASE_TOKEN_INVALID"))

    def test_checker_modifies_maker_files_rejected(self):
        """Attack: Checker holding a review task attempts to edit Maker's source code outside leased files."""
        # Checker claims task for review with target_files=["tests/test_audit.py"]
        claim = self.coord_mgr.claim_task(
            task_id="1.2",
            owner_id="agent-checker",
            target_files=["tests/test_audit.py"],
        )
        self.cap_mgr.grant_capability(
            agent_id="agent-checker",
            operation=CapabilityOperation.WRITE,
            target="tests/test_audit.py",
            task_id="1.2",
            change_id=self.change_id,
        )

        # Checker attempts to write to Maker's src/auth.py
        dec = self.cap_mgr.evaluate_access(
            agent_id="agent-checker",
            operation=CapabilityOperation.WRITE,
            target="src/auth.py",
            task_id="1.2",
            change_id=self.change_id,
            lease_token=claim.lease.lease_token,
        )
        self.assertFalse(dec.allowed)
        # Should be blocked by capability matching or file mismatch
        self.assertIn(dec.violation_code, ("NO_CAPABILITY", "LEASE_FILE_MISMATCH"))

    def test_race_two_agents_same_task(self):
        """Attack: Two agents race to claim the same task simultaneously."""
        claim1 = self.coord_mgr.claim_task(
            task_id="1.1",
            owner_id="agent-maker",
            target_files=["src/auth.py"],
        )
        self.assertTrue(claim1.success)

        # Second agent attempts to claim the same active task
        claim2 = self.coord_mgr.claim_task(
            task_id="1.1",
            owner_id="agent-checker",
            target_files=["src/auth.py"],
        )
        self.assertFalse(claim2.success)
        self.assertEqual(claim2.conflict_type, CoordinationConflictType.CONCURRENT_LEASE.value)
        self.assertIn("already leased by 'agent-maker'", claim2.error)

    def test_race_two_agents_overlapping_files(self):
        """Attack: Two agents claim different tasks but with overlapping target files."""
        claim1 = self.coord_mgr.claim_task(
            task_id="1.1",
            owner_id="agent-maker",
            target_files=["src/shared.py", "src/auth.py"],
        )
        self.assertTrue(claim1.success)

        # Second agent claims a different task (1.2) targeting src/shared.py
        claim2 = self.coord_mgr.claim_task(
            task_id="1.2",
            owner_id="agent-checker",
            target_files=["src/shared.py", "src/db.py"],
        )
        self.assertFalse(claim2.success)
        self.assertEqual(claim2.conflict_type, CoordinationConflictType.FILE_OVERLAP.value)
        self.assertIn("Resource file conflict", claim2.error)


if __name__ == "__main__":
    unittest.main()
