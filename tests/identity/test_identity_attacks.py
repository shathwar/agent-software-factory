"""Adversarial identity attack tests: impersonation, session hijacking, rogue agents, Maker-Checker collision."""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.models import (
    ActionProvenance,
    AgentRole,
    TaskLease,
    VerificationRecord,
)
from ship.lifecycle.provenance import (
    ProvenanceManager,
)
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.capabilities import CapabilityManager


class TestIdentityAttacks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "attack-identity-change"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })
        self.prov_mgr = ProvenanceManager(self.repo_root)
        self.cap_mgr = CapabilityManager(self.repo_root)

        # Register legitimate Agent A and Agent B
        self.agent_a = self.prov_mgr.register_identity("agent-alice", role=AgentRole.MAKER, change_id=self.change_id)
        self.agent_b = self.prov_mgr.register_identity("agent-bob", role=AgentRole.CHECKER, change_id=self.change_id)
        self.session_a = self.prov_mgr.start_session("agent-alice", change_id=self.change_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_impersonate_agent_b_in_lease_claim(self):
        """Attack: Agent A attempts to claim a task lease under Agent B's identity."""
        from ship.lifecycle.coordination import CoordinationManager
        coord_mgr = CoordinationManager(self.repo_root, self.change_id)

        # Alice creates a session, but tries to claim using Bob's name with Alice's session
        claim = coord_mgr.claim_task(
            task_id="T1",
            owner_id="agent-bob",
            session_id=self.session_a.session_id,
            change_id=self.change_id,
        )
        self.assertTrue(claim.success)

        # Now evaluate action provenance binding chain: session owner is Alice, but lease is Bob
        prov = self.prov_mgr.build_action_provenance(
            action_name="write_code",
            agent_id="agent-alice",
            session_id=self.session_a.session_id,
            task_id="T1",
            lease_token=claim.lease.lease_token,
            change_id=self.change_id,
        )
        res = self.prov_mgr.verify_binding_chain(provenance=prov, task_lease=claim.lease)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Lease owner 'agent-bob' does not match action agent 'agent-alice'" in e for e in res["errors"]))

    def test_unregistered_rogue_agent_denied_access(self):
        """Attack: Unregistered rogue agent attempts to perform an operation."""
        dec = self.cap_mgr.evaluate_access(
            agent_id="rogue-attacker-666",
            operation="READ",
            target="src/main.py",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "UNKNOWN_PRINCIPAL")

    def test_maker_checker_identity_collision_rejected(self):
        """Attack: Agent Alice implements code and attempts to verify her own evidence."""
        prov = self.prov_mgr.build_action_provenance(
            action_name="implement_feature",
            agent_id="agent-alice",
            session_id=self.session_a.session_id,
            change_id=self.change_id,
        )

        # Forged verification where verifier is Alice
        forged_verif = VerificationRecord(
            claim="tests_pass",
            gate="implementation",
            tier="execution",
            verdict="VERIFIED",
            method="self_attest",
            verifier_id="agent-alice",
            provenance={"agent_id": "agent-alice", "role": "VERIFIER"},
        )

        res = self.prov_mgr.verify_binding_chain(provenance=prov, verification_record=forged_verif)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Maker-Checker violation" in e for e in res["errors"]))

        # Also direct enforce_maker_checker_separation check
        valid, msg = ProvenanceManager.enforce_maker_checker_separation(
            {"agent_id": "agent-alice"},
            {"agent_id": "agent-alice"},
        )
        self.assertFalse(valid)
        self.assertIn("Maker != Checker violation", msg)


if __name__ == "__main__":
    unittest.main()
