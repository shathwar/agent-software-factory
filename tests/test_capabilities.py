"""Unit and integration tests for Capability-Based Permissions & Execution Ring Lattice.

Covers:
- Models: CapabilityOperation, ExecutionRing, Capability, AccessDecision
- Classification: 4-Ring Lattice mapping
- Grants: grant, revoke, list, TTL expiration
- Enforcement Pipeline:
  Agent -> Identity -> Capability -> Ring policy -> Lease -> Action -> ALLOW / DENY
- CLI: grant, list, check, revoke
"""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.models import (
    AccessDecision,
    Capability,
    CapabilityOperation,
    ExecutionRing,
    AgentRole,
)
from ship.lifecycle.capabilities import (
    CapabilityManager,
)
from ship.lifecycle.provenance import ProvenanceManager
from ship.lifecycle.coordination import CoordinationManager
from ship.lifecycle.ledger import FileLedgerStore
from ship.cli import main as cli_main


class TestCapabilityModels(unittest.TestCase):
    def test_capability_operation_enums(self):
        self.assertEqual(CapabilityOperation.READ.value, "READ")
        self.assertEqual(CapabilityOperation.WRITE.value, "WRITE")
        self.assertEqual(CapabilityOperation.DELETE.value, "DELETE")
        self.assertEqual(CapabilityOperation.EXECUTE.value, "EXECUTE")
        self.assertEqual(CapabilityOperation.GIT.value, "GIT")
        self.assertEqual(CapabilityOperation.NETWORK.value, "NETWORK")
        self.assertEqual(CapabilityOperation.SECRET_READ.value, "SECRET_READ")

    def test_execution_ring_enums(self):
        self.assertEqual(ExecutionRing.RING_0_HYPERVISOR.value, "RING_0_HYPERVISOR")
        self.assertEqual(ExecutionRing.RING_1_GOVERNANCE.value, "RING_1_GOVERNANCE")
        self.assertEqual(ExecutionRing.RING_2_PRODUCTION.value, "RING_2_PRODUCTION")
        self.assertEqual(ExecutionRing.RING_3_WORKSPACE.value, "RING_3_WORKSPACE")

    def test_capability_serialization_roundtrip(self):
        cap = Capability(
            capability_id="cap-test-123",
            agent_id="worker-tdd",
            change_id="feature-auth",
            operation=CapabilityOperation.WRITE,
            target="src/auth/*.py",
            task_id="1.1",
            session_id="sess-001",
            granted_at="2026-09-19T12:00:00Z",
            expires_at="2026-09-19T12:15:00Z",
            approval_ref="lease:tok-987",
            revoked=False,
            metadata={"priority": "high"},
        )
        d = cap.to_dict()
        self.assertEqual(d["capability_id"], "cap-test-123")
        self.assertEqual(d["operation"], "WRITE")

        restored = Capability.from_dict(d)
        self.assertEqual(restored.capability_id, "cap-test-123")
        self.assertEqual(restored.target, "src/auth/*.py")
        self.assertEqual(restored.metadata["priority"], "high")

    def test_access_decision_serialization_roundtrip(self):
        dec = AccessDecision(
            allowed=False,
            reason="Ring 0 mutation restricted",
            ring=ExecutionRing.RING_0_HYPERVISOR.value,
            agent_id="worker-tdd",
            operation="WRITE",
            target=".agentflow/ledger.json",
            violation_code="RING_0_RESTRICTED",
            timestamp="2026-09-19T12:00:00Z",
        )
        d = dec.to_dict()
        self.assertFalse(d["allowed"])
        self.assertEqual(d["violation_code"], "RING_0_RESTRICTED")

        restored = AccessDecision.from_dict(d)
        self.assertFalse(restored.allowed)
        self.assertEqual(restored.ring, ExecutionRing.RING_0_HYPERVISOR.value)


class TestTargetRingClassification(unittest.TestCase):
    def test_ring_0_classification(self):
        self.assertEqual(
            CapabilityManager.classify_target_ring(".agentflow/ledger.json"),
            ExecutionRing.RING_0_HYPERVISOR,
        )
        self.assertEqual(
            CapabilityManager.classify_target_ring(".agentflow/state.json"),
            ExecutionRing.RING_0_HYPERVISOR,
        )
        self.assertEqual(
            CapabilityManager.classify_target_ring("refs/ship/checkpoints/v1"),
            ExecutionRing.RING_0_HYPERVISOR,
        )

    def test_ring_1_classification(self):
        self.assertEqual(
            CapabilityManager.classify_target_ring(".agentflow.json"),
            ExecutionRing.RING_1_GOVERNANCE,
        )
        self.assertEqual(
            CapabilityManager.classify_target_ring("ARCHITECTURAL_INVARIANTS.md"),
            ExecutionRing.RING_1_GOVERNANCE,
        )
        self.assertEqual(
            CapabilityManager.classify_target_ring("docs/adr/0002-cap.md"),
            ExecutionRing.RING_1_GOVERNANCE,
        )
        self.assertEqual(
            CapabilityManager.classify_target_ring("openspec/specs/auth.md"),
            ExecutionRing.RING_1_GOVERNANCE,
        )

    def test_ring_2_classification(self):
        self.assertEqual(
            CapabilityManager.classify_target_ring("src/auth/login.py"),
            ExecutionRing.RING_2_PRODUCTION,
        )
        self.assertEqual(
            CapabilityManager.classify_target_ring("tests/test_auth.py"),
            ExecutionRing.RING_2_PRODUCTION,
        )
        self.assertEqual(
            CapabilityManager.classify_target_ring("pyproject.toml"),
            ExecutionRing.RING_2_PRODUCTION,
        )

    def test_ring_3_classification(self):
        self.assertEqual(
            CapabilityManager.classify_target_ring("scratch/temp.py"),
            ExecutionRing.RING_3_WORKSPACE,
        )
        self.assertEqual(
            CapabilityManager.classify_target_ring(".agentflow/spikes/bench.py"),
            ExecutionRing.RING_3_WORKSPACE,
        )
        self.assertEqual(
            CapabilityManager.classify_target_ring("build/output.log"),
            ExecutionRing.RING_3_WORKSPACE,
        )


class TestCapabilityManagerGrants(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "change-cap-test"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })
        self.mgr = CapabilityManager(self.repo_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_grant_and_retrieve_capability(self):
        cap = self.mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/*.py",
            change_id=self.change_id,
            task_id="1.1",
            ttl_seconds=300,
            approval_ref="lease:tok-123",
        )
        self.assertTrue(cap.capability_id.startswith("cap-"))
        self.assertEqual(cap.operation, "WRITE")
        self.assertEqual(cap.target, "src/auth/*.py")
        self.assertIsNotNone(cap.expires_at)

        # Retrieve
        fetched = self.mgr.get_capability(cap.capability_id, self.change_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.capability_id, cap.capability_id)

    def test_revoke_capability(self):
        cap = self.mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/*.py",
            change_id=self.change_id,
        )
        revoked = self.mgr.revoke_capability(cap.capability_id, self.change_id, reason="Task complete")
        self.assertIsNotNone(revoked)
        self.assertTrue(revoked.revoked)
        self.assertEqual(revoked.metadata["revocation_reason"], "Task complete")

        # Check list active_only excludes revoked
        active_caps = self.mgr.list_capabilities(self.change_id, active_only=True)
        self.assertEqual(len(active_caps), 0)


class TestAccessEvaluationPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "change-sec-eval"
        self.change_dir = self.repo_root / ".ship" / "changes" / self.change_id
        self.change_dir.mkdir(parents=True, exist_ok=True)
        (self.change_dir / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 Auth\n- [ ] 1.2 DB\n")

        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })

        self.prov_mgr = ProvenanceManager(self.repo_root)
        self.coord_mgr = CoordinationManager(self.repo_root, self.change_id)
        self.cap_mgr = CapabilityManager(self.repo_root)

        # Register known principal
        self.prov_mgr.register_identity(
            agent_id="worker-tdd",
            role=AgentRole.MAKER,
            change_id=self.change_id,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_unknown_principal_denied(self):
        dec = self.cap_mgr.evaluate_access(
            agent_id="unregistered-rogue-agent",
            operation=CapabilityOperation.READ,
            target="src/auth/login.py",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "UNKNOWN_PRINCIPAL")

    def test_no_capability_denied(self):
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/login.py",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "NO_CAPABILITY")

    def test_target_mismatch_denied(self):
        self.cap_mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/*.py",
            change_id=self.change_id,
        )
        # Attempt to modify a different module
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/database/schema.py",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "NO_CAPABILITY")

    def test_capability_expired_denied(self):
        self.cap_mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/*.py",
            change_id=self.change_id,
            ttl_seconds=-10,  # Pre-expired
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/login.py",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "CAPABILITY_EXPIRED")

    def test_ring_0_direct_write_restricted(self):
        self.cap_mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target=".agentflow/ledger.json",
            change_id=self.change_id,
            approval_ref="self-claimed",
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target=".agentflow/ledger.json",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "RING_0_RESTRICTED")

    def test_ring_0_allowed_with_hypervisor_approval(self):
        self.cap_mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target=".agentflow/ledger.json",
            change_id=self.change_id,
            approval_ref="hypervisor:system-sync",
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target=".agentflow/ledger.json",
            change_id=self.change_id,
        )
        self.assertTrue(dec.allowed)

    def test_ring_1_governance_unauthorized_denied(self):
        self.cap_mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="ARCHITECTURAL_INVARIANTS.md",
            change_id=self.change_id,
            approval_ref="dev-edit",
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="ARCHITECTURAL_INVARIANTS.md",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "RING_1_UNAUTHORIZED")

    def test_ring_1_governance_allowed_with_approved_adr(self):
        self.cap_mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="ARCHITECTURAL_INVARIANTS.md",
            change_id=self.change_id,
            approval_ref="adr:0002-cap-governance",
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="ARCHITECTURAL_INVARIANTS.md",
            change_id=self.change_id,
        )
        self.assertTrue(dec.allowed)

    def test_ring_2_production_write_requires_lease(self):
        self.cap_mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/login.py",
            change_id=self.change_id,
        )
        # Attempt write with no task_id or lease
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/login.py",
            change_id=self.change_id,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "LEASE_REQUIRED")

    def test_ring_2_production_write_file_mismatch_denied(self):
        # Claim task 1.1 for src/auth/login.py only
        claim = self.coord_mgr.claim_task(
            task_id="1.1",
            owner_id="worker-tdd",
            change_id=self.change_id,
            target_files=["src/auth/login.py"],
        )
        self.cap_mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/*.py",
            task_id="1.1",
            change_id=self.change_id,
        )
        # Attempt to edit src/auth/token.py which is outside the leased file list
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/token.py",
            task_id="1.1",
            change_id=self.change_id,
            lease_token=claim.lease.lease_token,
        )
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "LEASE_FILE_MISMATCH")

    def test_ring_2_production_write_full_chain_allowed(self):
        # Claim task 1.1 with target files
        claim = self.coord_mgr.claim_task(
            task_id="1.1",
            owner_id="worker-tdd",
            change_id=self.change_id,
            target_files=["src/auth/login.py"],
        )
        self.cap_mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/login.py",
            task_id="1.1",
            change_id=self.change_id,
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="src/auth/login.py",
            task_id="1.1",
            change_id=self.change_id,
            lease_token=claim.lease.lease_token,
        )
        self.assertTrue(dec.allowed)
        self.assertIn("authorizes WRITE", dec.reason)

    def test_ring_3_workspace_scratch_allowed(self):
        self.cap_mgr.grant_capability(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="scratch/*",
            change_id=self.change_id,
        )
        dec = self.cap_mgr.evaluate_access(
            agent_id="worker-tdd",
            operation=CapabilityOperation.WRITE,
            target="scratch/trial.py",
            change_id=self.change_id,
        )
        self.assertTrue(dec.allowed)


class TestCapabilityCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "change-cli-caps"
        self.change_dir = self.repo_root / ".ship" / "changes" / self.change_id
        self.change_dir.mkdir(parents=True, exist_ok=True)
        (self.change_dir / "tasks.md").write_text("# Tasks\n\n- [ ] T1 Auth\n")
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })

        # Register agent principal
        prov_mgr = ProvenanceManager(self.repo_root)
        prov_mgr.register_identity("agent-cli", role=AgentRole.MAKER, change_id=self.change_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_grant_list_check_revoke_flow(self):
        # 1. Grant capability
        rc = cli_main([
            "capability", "grant", "agent-cli",
            "--op", "WRITE",
            "--target", "scratch/*",
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--ttl", "600",
        ])
        self.assertEqual(rc, 0)

        # 2. List capabilities
        rc = cli_main([
            "capability", "list",
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--active",
        ])
        self.assertEqual(rc, 0)

        # 3. Check access (should ALLOW -> rc=0)
        rc = cli_main([
            "capability", "check", "agent-cli",
            "--op", "WRITE",
            "--target", "scratch/test.py",
            "--path", str(self.repo_root),
            "--change", self.change_id,
        ])
        self.assertEqual(rc, 0)

        # 4. Check unauthorized access (should DENY -> rc=1)
        rc = cli_main([
            "capability", "check", "agent-cli",
            "--op", "WRITE",
            "--target", "src/unauthorized.py",
            "--path", str(self.repo_root),
            "--change", self.change_id,
        ])
        self.assertEqual(rc, 1)

        # 5. Revoke capability
        mgr = CapabilityManager(self.repo_root)
        caps = mgr.list_capabilities(self.change_id)
        self.assertEqual(len(caps), 1)
        cap_id = caps[0].capability_id

        rc = cli_main([
            "capability", "revoke", cap_id,
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--reason", "Revocation test",
        ])
        self.assertEqual(rc, 0)

        # 6. Check after revocation (should DENY -> rc=1)
        rc = cli_main([
            "capability", "check", "agent-cli",
            "--op", "WRITE",
            "--target", "scratch/test.py",
            "--path", str(self.repo_root),
            "--change", self.change_id,
        ])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
