"""Adversarial permission tests: Ring 0 tampering, Ring 1 ADR bypass, path escapes, secret/network operations."""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.capabilities import CapabilityManager
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.models import CapabilityOperation, ExecutionRing
from ship.lifecycle.provenance import ProvenanceManager


class TestRingAttacks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "attack-ring-change"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })
        self.prov_mgr = ProvenanceManager(self.repo_root)
        self.cap_mgr = CapabilityManager(self.repo_root)

        self.prov_mgr.register_identity("agent-attacker", role="MAKER", change_id=self.change_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_ring_0_ledger_directly_blocked(self):
        """Attack: Agent attempts to write to .agentflow/ledger.json without hypervisor approval."""
        self.cap_mgr.grant_capability(
            agent_id="agent-attacker",
            operation=CapabilityOperation.WRITE,
            target=".agentflow/ledger.json",
            change_id=self.change_id,
            approval_ref="self-approved",
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="agent-attacker",
            operation=CapabilityOperation.WRITE,
            target=".agentflow/ledger.json",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.ring, ExecutionRing.RING_0_HYPERVISOR.value)
        self.assertEqual(dec.violation_code, "RING_0_RESTRICTED")

    def test_synthesize_ring_0_git_notes_ref_blocked(self):
        """Attack: Agent attempts to forge private Git notes (refs/ship/*)."""
        self.cap_mgr.grant_capability(
            agent_id="agent-attacker",
            operation=CapabilityOperation.GIT,
            target="refs/ship/checkpoints/v1",
            change_id=self.change_id,
            approval_ref="forged-ref",
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="agent-attacker",
            operation=CapabilityOperation.GIT,
            target="refs/ship/checkpoints/v1",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.ring, ExecutionRing.RING_0_HYPERVISOR.value)
        self.assertEqual(dec.violation_code, "RING_0_RESTRICTED")

    def test_modify_ring_1_without_adr_blocked(self):
        """Attack: Agent attempts to modify ARCHITECTURAL_INVARIANTS.md without an approved ADR."""
        self.cap_mgr.grant_capability(
            agent_id="agent-attacker",
            operation=CapabilityOperation.WRITE,
            target="ARCHITECTURAL_INVARIANTS.md",
            change_id=self.change_id,
            approval_ref="feature-request",
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="agent-attacker",
            operation=CapabilityOperation.WRITE,
            target="ARCHITECTURAL_INVARIANTS.md",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.ring, ExecutionRing.RING_1_GOVERNANCE.value)
        self.assertEqual(dec.violation_code, "RING_1_UNAUTHORIZED")

    def test_modify_ring_1_agentflow_json_without_adr_blocked(self):
        """Attack: Agent attempts to modify root .agentflow.json without ADR."""
        self.cap_mgr.grant_capability(
            agent_id="agent-attacker",
            operation=CapabilityOperation.WRITE,
            target=".agentflow.json",
            change_id=self.change_id,
            approval_ref="quick-fix",
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="agent-attacker",
            operation=CapabilityOperation.WRITE,
            target=".agentflow.json",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.ring, ExecutionRing.RING_1_GOVERNANCE.value)
        self.assertEqual(dec.violation_code, "RING_1_UNAUTHORIZED")

    def test_unauthorized_secret_read_blocked(self):
        """Attack: Agent attempts to read credentials without SECRET_READ capability."""
        dec = self.cap_mgr.evaluate_access(
            agent_id="agent-attacker",
            operation=CapabilityOperation.SECRET_READ,
            target="env:API_KEY",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "NO_CAPABILITY")

    def test_unauthorized_network_access_blocked(self):
        """Attack: Agent attempts out-of-band network communication without NETWORK capability."""
        dec = self.cap_mgr.evaluate_access(
            agent_id="agent-attacker",
            operation=CapabilityOperation.NETWORK,
            target="net:https://evil-server.com",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "NO_CAPABILITY")


if __name__ == "__main__":
    unittest.main()
