"""Unit and integration tests for Agent Identity & Provenance Layer.

Covers:
- Models: AgentRole, AgentIdentity, AgentSession, ActionProvenance
- Cryptographic Digesting: compute_payload_digest canonical SHA-256
- ProvenanceManager: identity, session, action provenance, binding chain verification
- Maker != Checker mechanical separation enforcement
- Multi-agent coordination integration with session & provenance tracking
- CLI subcommands: session start/end/list, identity register/list, lease claim --session
"""

import json
from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.models import (
    AgentRole,
    AgentIdentity,
    AgentSession,
    ActionProvenance,
    TaskLease,
    VerificationRecord,
)
from ship.lifecycle.provenance import (
    ProvenanceManager,
    compute_payload_digest,
)
from ship.lifecycle.coordination import CoordinationManager
from ship.lifecycle.ledger import FileLedgerStore
from ship.cli import main as cli_main


class TestProvenanceModels(unittest.TestCase):
    def test_agent_role_enum(self):
        self.assertEqual(AgentRole.ARCHITECT.value, "ARCHITECT")
        self.assertEqual(AgentRole.MAKER.value, "MAKER")
        self.assertEqual(AgentRole.CHECKER.value, "CHECKER")
        self.assertEqual(AgentRole.VERIFIER.value, "VERIFIER")
        self.assertEqual(AgentRole.COORDINATOR.value, "COORDINATOR")

    def test_identity_serialization(self):
        ident = AgentIdentity(
            agent_id="agent-007",
            role="MAKER",
            runtime="antigravity",
            model="gemini-1.5-pro",
            parent_agent_id="agent-lead-1",
            created_at="2026-09-19T12:00:00Z",
            metadata={"specialization": "python"},
        )
        d = ident.to_dict()
        self.assertEqual(d["agent_id"], "agent-007")
        self.assertEqual(d["parent_agent_id"], "agent-lead-1")

        restored = AgentIdentity.from_dict(d)
        self.assertEqual(restored.agent_id, "agent-007")
        self.assertEqual(restored.role, "MAKER")
        self.assertEqual(restored.metadata["specialization"], "python")

    def test_session_serialization(self):
        sess = AgentSession(
            session_id="sess-test-123",
            agent_id="agent-007",
            change_id="change-feature-auth",
            role="MAKER",
            started_at="2026-09-19T12:00:00Z",
            ended_at=None,
            status="ACTIVE",
            agentflow_version="1.0.0",
            skill="tdd",
            skill_version="1.0.0",
            runtime="antigravity",
            model="gemini-1.5-pro",
            parent_session_id=None,
            metadata={},
        )
        d = sess.to_dict()
        self.assertEqual(d["session_id"], "sess-test-123")
        self.assertEqual(d["status"], "ACTIVE")

        restored = AgentSession.from_dict(d)
        self.assertEqual(restored.session_id, "sess-test-123")
        self.assertEqual(restored.agent_id, "agent-007")
        self.assertIsNone(restored.ended_at)

    def test_action_provenance_serialization(self):
        prov = ActionProvenance(
            action_id="act-9876",
            action_name="run_tests",
            agent_id="agent-007",
            session_id="sess-test-123",
            change_id="change-feature-auth",
            role="MAKER",
            task_id="1.1",
            lease_token="tok-abc",
            timestamp="2026-09-19T12:05:00Z",
            runtime="antigravity",
            model="gemini-1.5-pro",
            skill="tdd",
            skill_version="1.0.0",
            agentflow_version="1.0.0",
            parent_agent_id="agent-lead-1",
            inputs_digest="sha256:1111",
            evidence_digest="sha256:2222",
            metadata={},
        )
        d = prov.to_dict()
        self.assertEqual(d["action_id"], "act-9876")
        self.assertEqual(d["inputs_digest"], "sha256:1111")

        restored = ActionProvenance.from_dict(d)
        self.assertEqual(restored.action_name, "run_tests")
        self.assertEqual(restored.lease_token, "tok-abc")

    def test_compute_payload_digest_canonical(self):
        # Key order should not change the digest
        payload1 = {"b": 2, "a": 1, "c": [1, 2, 3]}
        payload2 = {"a": 1, "c": [1, 2, 3], "b": 2}
        d1 = compute_payload_digest(payload1)
        d2 = compute_payload_digest(payload2)
        self.assertTrue(d1.startswith("sha256:"))
        self.assertEqual(d1, d2)

        # None payload returns empty string
        self.assertEqual(compute_payload_digest(None), "")


class TestProvenanceManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "feature-test"
        self.change_dir = self.repo_root / ".ship" / "changes" / self.change_id
        self.change_dir.mkdir(parents=True, exist_ok=True)
        (self.change_dir / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 Auth\n")
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })
        self.mgr = ProvenanceManager(self.repo_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_register_and_list_identities(self):
        ident = self.mgr.register_identity(
            agent_id="worker-tdd",
            role=AgentRole.MAKER,
            runtime="antigravity",
            model="gemini-1.5-pro",
            change_id=self.change_id,
        )
        self.assertEqual(ident.agent_id, "worker-tdd")
        self.assertEqual(ident.role, "MAKER")

        # Retrieve
        fetched = self.mgr.get_identity("worker-tdd", self.change_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.agent_id, "worker-tdd")

        # List
        all_idents = self.mgr.list_identities(self.change_id)
        self.assertEqual(len(all_idents), 1)
        self.assertEqual(all_idents[0].agent_id, "worker-tdd")

    def test_start_and_end_session(self):
        sess = self.mgr.start_session(
            agent_id="worker-tdd",
            role=AgentRole.MAKER,
            change_id=self.change_id,
            skill="tdd",
            model="gemini-1.5-pro",
        )
        self.assertTrue(sess.session_id.startswith("sess-"))
        self.assertEqual(sess.status, "ACTIVE")
        self.assertIsNone(sess.ended_at)

        # Retrieve session
        fetched = self.mgr.get_session(sess.session_id, self.change_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.session_id, sess.session_id)

        # List active sessions
        active = self.mgr.list_sessions(self.change_id, active_only=True)
        self.assertEqual(len(active), 1)

        # End session
        ended = self.mgr.end_session(sess.session_id, self.change_id, status="COMPLETED")
        self.assertIsNotNone(ended)
        self.assertEqual(ended.status, "COMPLETED")
        self.assertIsNotNone(ended.ended_at)

        # Now active_only should be empty
        active_after = self.mgr.list_sessions(self.change_id, active_only=True)
        self.assertEqual(len(active_after), 0)

    def test_build_action_provenance(self):
        sess = self.mgr.start_session(
            agent_id="worker-tdd",
            role=AgentRole.MAKER,
            change_id=self.change_id,
            model="gemini-1.5-pro",
        )
        prov = self.mgr.build_action_provenance(
            action_name="execute_unit_tests",
            agent_id="worker-tdd",
            session_id=sess.session_id,
            change_id=self.change_id,
            task_id="1.1",
            lease_token="lease-tok-001",
            inputs={"test_filter": "test_auth*"},
            evidence={"passed": 5, "failed": 0},
        )
        self.assertTrue(prov.action_id.startswith("act-"))
        self.assertEqual(prov.agent_id, "worker-tdd")
        self.assertEqual(prov.session_id, sess.session_id)
        self.assertTrue(prov.inputs_digest.startswith("sha256:"))
        self.assertTrue(prov.evidence_digest.startswith("sha256:"))

    def test_verify_binding_chain_success(self):
        sess = self.mgr.start_session(
            agent_id="worker-tdd",
            role=AgentRole.MAKER,
            change_id=self.change_id,
        )
        prov = self.mgr.build_action_provenance(
            action_name="implement_component",
            agent_id="worker-tdd",
            session_id=sess.session_id,
            change_id=self.change_id,
            task_id="1.1",
            lease_token="lease-tok-xyz",
            inputs={"prompt": "build auth"},
            evidence={"diff_stat": "+50 lines"},
        )
        lease = TaskLease(
            task_id="1.1",
            change_id=self.change_id,
            owner_id="worker-tdd",
            lease_token="lease-tok-xyz",
            acquired_at="2026-09-19T10:00:00Z",
            expires_at="2026-09-19T10:15:00Z",
        )
        verification = VerificationRecord(
            claim="tests_pass",
            gate="implementation",
            tier="execution",
            verdict="VERIFIED",
            method="pytest_runner",
            verifier_id="agent-independent-verifier",
            provenance={"agent_id": "agent-independent-verifier", "role": "VERIFIER"},
        )

        res = self.mgr.verify_binding_chain(
            provenance=prov,
            task_lease=lease,
            verification_record=verification,
        )
        self.assertTrue(res["valid"])
        self.assertEqual(len(res["errors"]), 0)
        self.assertIn("agent:worker-tdd", res["chain_str"])
        self.assertIn("verification:VERIFIED by agent-independent-verifier", res["chain_str"])

    def test_verify_binding_chain_maker_checker_violation(self):
        sess = self.mgr.start_session(
            agent_id="worker-tdd",
            role=AgentRole.MAKER,
            change_id=self.change_id,
        )
        prov = self.mgr.build_action_provenance(
            action_name="implement_component",
            agent_id="worker-tdd",
            session_id=sess.session_id,
            change_id=self.change_id,
            task_id="1.1",
            lease_token="lease-tok-xyz",
        )
        # Violating verification: verifier has the SAME agent_id as the maker
        violating_verification = VerificationRecord(
            claim="tests_pass",
            gate="implementation",
            tier="execution",
            verdict="VERIFIED",
            method="pytest_runner",
            verifier_id="worker-tdd",
            provenance={"agent_id": "worker-tdd", "role": "VERIFIER"},
        )

        res = self.mgr.verify_binding_chain(
            provenance=prov,
            verification_record=violating_verification,
        )
        self.assertFalse(res["valid"])
        self.assertTrue(any("Maker-Checker violation" in err for err in res["errors"]))

    def test_enforce_maker_checker_separation(self):
        maker_prov = {"agent_id": "worker-agent", "role": "MAKER"}
        checker_prov = {"agent_id": "auditor-agent", "role": "CHECKER"}
        valid, msg = ProvenanceManager.enforce_maker_checker_separation(maker_prov, checker_prov)
        self.assertTrue(valid)

        # Same agent should fail
        violating_prov = {"agent_id": "worker-agent", "role": "CHECKER"}
        invalid, err = ProvenanceManager.enforce_maker_checker_separation(maker_prov, violating_prov)
        self.assertFalse(invalid)
        self.assertIn("Maker != Checker violation", err)


class TestCoordinationWithProvenance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "feature-coord"
        self.change_dir = self.repo_root / ".ship" / "changes" / self.change_id
        self.change_dir.mkdir(parents=True, exist_ok=True)
        (self.change_dir / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 Auth\n- [ ] 2.1 Test\n")
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })
        self.coord_mgr = CoordinationManager(self.repo_root, self.change_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_claim_lease_stamps_session_and_provenance(self):
        res = self.coord_mgr.claim_task(
            task_id="1.1",
            owner_id="worker-agent",
            change_id=self.change_id,
            session_id="sess-abc-123",
            runtime="antigravity",
            model="gemini-1.5-pro",
            role=AgentRole.MAKER,
        )
        self.assertTrue(res.success)
        self.assertIsNotNone(res.lease)
        self.assertEqual(res.lease.session_id, "sess-abc-123")
        self.assertIsNotNone(res.lease.provenance)
        self.assertEqual(res.lease.provenance.get("agent_id"), "worker-agent")
        self.assertEqual(res.lease.provenance.get("action_name"), "claim_task")

        # Verify ledger turn has session and provenance
        ledger = FileLedgerStore.load(self.repo_root)
        turns = ledger["changes"][self.change_id]["turns"]
        self.assertTrue(len(turns) > 0)
        latest = turns[-1]
        self.assertEqual(latest.get("session_id"), "sess-abc-123")
        self.assertIn("provenance", latest)
        self.assertEqual(latest["provenance"]["agent_id"], "worker-agent")

    def test_handoff_stamps_from_and_to_provenance(self):
        claim_res = self.coord_mgr.claim_task(
            task_id="2.1",
            owner_id="worker-maker",
            change_id=self.change_id,
            session_id="sess-maker",
        )
        token = claim_res.lease.lease_token

        handoff_res = self.coord_mgr.handoff_task(
            task_id="2.1",
            from_owner="worker-maker",
            to_owner="worker-checker",
            lease_token=token,
            change_id=self.change_id,
            reason="Ready for review",
            session_id="sess-maker",
            runtime="antigravity",
            model="claude-3-5-sonnet",
        )
        self.assertTrue(handoff_res.success)
        self.assertIsNotNone(handoff_res.lease)
        self.assertEqual(handoff_res.lease.owner_id, "worker-checker")

        # Check handoffs list in ledger
        ledger = FileLedgerStore.load(self.repo_root)
        coord = ledger["changes"][self.change_id].get("coordination", {})
        handoffs = coord.get("handoffs", [])
        self.assertEqual(len(handoffs), 1)
        h = handoffs[0]
        self.assertEqual(h["from_owner"], "worker-maker")
        self.assertEqual(h["to_owner"], "worker-checker")
        self.assertEqual(h["session_id"], "sess-maker")
        self.assertIsNotNone(h["from_provenance"])
        self.assertIsNotNone(h["to_provenance"])


class TestProvenanceCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "feature-cli"
        self.change_dir = self.repo_root / ".ship" / "changes" / self.change_id
        self.change_dir.mkdir(parents=True, exist_ok=True)
        (self.change_dir / "tasks.md").write_text("# Tasks\n\n- [ ] T1 Fix\n")
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_identity_register_and_list_cli(self):
        # Register identity
        rc = cli_main([
            "identity", "register", "agent-x",
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--role", "maker",
            "--model", "gemini-1.5-pro",
        ])
        self.assertEqual(rc, 0)

        # List identities
        rc = cli_main([
            "identity", "list",
            "--path", str(self.repo_root),
            "--change", self.change_id,
        ])
        self.assertEqual(rc, 0)

    def test_session_lifecycle_cli(self):
        # Start session
        rc = cli_main([
            "session", "start", "agent-x",
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--role", "maker",
            "--skill", "tdd",
        ])
        self.assertEqual(rc, 0)

        # List sessions
        rc = cli_main([
            "session", "list",
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--active",
        ])
        self.assertEqual(rc, 0)

        # Find session ID from ledger
        mgr = ProvenanceManager(self.repo_root)
        sessions = mgr.list_sessions(self.change_id)
        self.assertEqual(len(sessions), 1)
        sess_id = sessions[0].session_id

        # End session
        rc = cli_main([
            "session", "end", sess_id,
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--status", "COMPLETED",
        ])
        self.assertEqual(rc, 0)

    def test_lease_claim_with_session_cli(self):
        rc = cli_main([
            "lease", "claim", "T1",
            "--owner", "agent-x",
            "--session", "sess-xyz",
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--role", "MAKER",
            "--model", "gemini-1.5-pro",
        ])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
