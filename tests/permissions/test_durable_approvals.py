"""Unit and adversarial tests for Durable Authorization Objects & Scope-Limited Approvals."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.approvals import ApprovalManager, compute_approval_signature
from ship.lifecycle.capabilities import CapabilityManager
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.models import CapabilityOperation, ExecutionRing
from ship.lifecycle.provenance import ProvenanceManager


class TestDurableApprovals(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "change-authz-1"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {
                self.change_id: {
                    "provenance": {
                        "identities": {
                            "agent-alice": {"agent_id": "agent-alice", "role": "MAKER"},
                            "agent-bob": {"agent_id": "agent-bob", "role": "CHECKER"},
                        }
                    }
                }
            },
        })
        self.appr_mgr = ApprovalManager(self.repo_root)
        self.cap_mgr = CapabilityManager(self.repo_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    # 1. Full 4-Step Lifecycle
    def test_full_request_approval_capability_action_lifecycle(self):
        # Step 1: Request
        req = self.appr_mgr.create_request(
            agent="agent-alice",
            action="SECRET_READ",
            scope="AWS_*",
            reason="Required to fetch S3 training dataset credentials",
            change=self.change_id,
        )
        self.assertEqual(req.status, "PENDING")
        self.assertTrue(req.request_id.startswith("req-"))

        # Step 2: Approval
        appr = self.appr_mgr.approve_request(
            request_id=req.request_id,
            human="sec_lead:carol",
            ttl_seconds=3600,
            change_id=self.change_id,
        )
        self.assertTrue(appr.approval_id.startswith("appr-"))
        self.assertEqual(appr.human, "sec_lead:carol")
        self.assertEqual(appr.agent, "agent-alice")
        self.assertEqual(appr.action, "SECRET_READ")
        self.assertEqual(appr.scope, "AWS_*")
        self.assertTrue(len(appr.signature) == 64)

        # Step 3: Capability Grant
        cap = self.cap_mgr.grant_from_approval(
            approval_id=appr.approval_id,
            change_id=self.change_id,
        )
        self.assertEqual(cap.agent_id, "agent-alice")
        self.assertEqual(cap.operation, "SECRET_READ")
        self.assertEqual(cap.target, "AWS_*")
        self.assertEqual(cap.approval_ref, appr.approval_id)

        # Step 4: Action (Evaluation)
        decision = self.cap_mgr.evaluate_access(
            agent_id="agent-alice",
            operation=CapabilityOperation.SECRET_READ,
            target="AWS_SECRET_ACCESS_KEY",
            change_id=self.change_id,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.ring, ExecutionRing.RING_1_GOVERNANCE.value)

    # 2. Non-Transferability: Agent Binding
    def test_approval_non_transferable_between_agents_blocked(self):
        # Human approves for agent-alice
        appr = self.appr_mgr.issue_direct_approval(
            human="sec_lead:carol",
            agent="agent-alice",
            action="SECRET_READ",
            scope="AWS_*",
            reason="Alice authorized for AWS",
            change=self.change_id,
        )

        # Attack 1: agent-bob attempts to claim capability using Alice's approval ID
        with self.assertRaises(PermissionError) as ctx:
            self.cap_mgr.grant_capability(
                agent_id="agent-bob",
                operation=CapabilityOperation.SECRET_READ,
                target="AWS_*",
                approval_ref=appr.approval_id,
                change_id=self.change_id,
            )
        self.assertIn("APPROVAL_AGENT_MISMATCH", str(ctx.exception))

        # Attack 2: agent-bob attempts grant_from_approval
        with self.assertRaises(PermissionError) as ctx:
            # Grant capability directly from approval returns capability for the authorized agent (alice),
            # but if bob specifies another agent, it fails
            self.cap_mgr.grant_capability(
                agent_id="agent-bob",
                operation=appr.action,
                target=appr.scope,
                approval_ref=appr.approval_id,
                change_id=self.change_id,
            )
        self.assertIn("APPROVAL_AGENT_MISMATCH", str(ctx.exception))

    # 3. Non-Transferability: Change Binding
    def test_approval_non_transferable_between_changes_blocked(self):
        # Approval granted in change-authz-1
        appr = self.appr_mgr.issue_direct_approval(
            human="sec_lead:carol",
            agent="agent-alice",
            action="SECRET_READ",
            scope="AWS_*",
            reason="Alice authorized for AWS in change 1",
            change=self.change_id,
        )

        # Setup change-2
        change_2 = "change-authz-2"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": change_2,
            "changes": {
                self.change_id: FileLedgerStore.load(self.repo_root)["changes"][self.change_id],
                change_2: {
                    "provenance": {
                        "identities": {
                            "agent-alice": {"agent_id": "agent-alice", "role": "MAKER"},
                        }
                    }
                }
            },
        })

        # Alice attempts to use approval from change 1 in change 2
        with self.assertRaises(PermissionError) as ctx:
            self.cap_mgr.grant_capability(
                agent_id="agent-alice",
                operation=CapabilityOperation.SECRET_READ,
                target="AWS_*",
                approval_ref=appr.approval_id,
                change_id=change_2,
            )
        self.assertTrue(
            "APPROVAL_CHANGE_MISMATCH" in str(ctx.exception) or "APPROVAL_NOT_FOUND" in str(ctx.exception)
        )

    # 4. Scope Limitation
    def test_approval_scope_escalation_blocked(self):
        # Scope is strictly restricted to src/auth/*
        appr = self.appr_mgr.issue_direct_approval(
            human="tech_lead:dave",
            agent="agent-alice",
            action="WRITE",
            scope="src/auth/*",
            reason="Auth refactoring",
            change=self.change_id,
        )

        # Attempt to grant capability covering all src/*
        with self.assertRaises(PermissionError) as ctx:
            self.cap_mgr.grant_capability(
                agent_id="agent-alice",
                operation="WRITE",
                target="src/*",
                approval_ref=appr.approval_id,
                change_id=self.change_id,
            )
        self.assertIn("APPROVAL_SCOPE_EXCEEDED", str(ctx.exception))

    # 5. Action Limitation
    def test_approval_action_escalation_blocked(self):
        # Action is strictly NETWORK_READ
        appr = self.appr_mgr.issue_direct_approval(
            human="sec_lead:carol",
            agent="agent-alice",
            action="NETWORK_READ",
            scope="https://api.github.com/*",
            reason="Read public GitHub PR metadata",
            change=self.change_id,
        )

        # Attempt to escalate to NETWORK_WRITE
        with self.assertRaises(PermissionError) as ctx:
            self.cap_mgr.grant_capability(
                agent_id="agent-alice",
                operation="NETWORK_WRITE",
                target="https://api.github.com/*",
                approval_ref=appr.approval_id,
                change_id=self.change_id,
            )
        self.assertIn("APPROVAL_ACTION_MISMATCH", str(ctx.exception))

    # 6. Expiration Enforcement
    def test_expired_approval_rejected(self):
        # Past timestamp
        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        appr = self.appr_mgr.issue_direct_approval(
            human="sec_lead:carol",
            agent="agent-alice",
            action="SECRET_READ",
            scope="AWS_*",
            reason="Expired authorization",
            change=self.change_id,
        )
        # Force expiration in past
        ledger = FileLedgerStore.load(self.repo_root)
        auth_data = ledger["changes"][self.change_id]["approvals"]["authorizations"][appr.approval_id]
        auth_data["expires_at"] = past_iso
        # re-sign
        auth_data["signature"] = compute_approval_signature(
            approval_id=appr.approval_id,
            human=auth_data["human"],
            agent=auth_data["agent"],
            change=auth_data["change"],
            action=auth_data["action"],
            scope=auth_data["scope"],
            issued_at=auth_data["issued_at"],
            expires_at=past_iso,
            reason=auth_data["reason"],
        )
        FileLedgerStore.save(self.repo_root, ledger)

        # Grant capability should fail
        with self.assertRaises(PermissionError) as ctx:
            self.cap_mgr.grant_capability(
                agent_id="agent-alice",
                operation="SECRET_READ",
                target="AWS_*",
                approval_ref=appr.approval_id,
                change_id=self.change_id,
            )
        self.assertIn("APPROVAL_EXPIRED", str(ctx.exception))

    # 7. Revocation Invalidates Derivative Capabilities at Runtime
    def test_revoked_approval_invalidates_active_capability(self):
        appr = self.appr_mgr.issue_direct_approval(
            human="sec_lead:carol",
            agent="agent-alice",
            action="SECRET_READ",
            scope="AWS_*",
            reason="Temporary token access",
            change=self.change_id,
        )

        cap = self.cap_mgr.grant_from_approval(
            approval_id=appr.approval_id,
            change_id=self.change_id,
        )

        # Initially valid and allowed
        dec1 = self.cap_mgr.evaluate_access(
            agent_id="agent-alice",
            operation=CapabilityOperation.SECRET_READ,
            target="AWS_ACCESS_KEY_ID",
            change_id=self.change_id,
        )
        self.assertTrue(dec1.allowed)

        # Human revokes the authorization
        self.appr_mgr.revoke_approval(
            approval_id=appr.approval_id,
            human="sec_lead:carol",
            reason="Security incident reported",
            change_id=self.change_id,
        )

        # Runtime evaluation is now blocked!
        dec2 = self.cap_mgr.evaluate_access(
            agent_id="agent-alice",
            operation=CapabilityOperation.SECRET_READ,
            target="AWS_ACCESS_KEY_ID",
            change_id=self.change_id,
        )
        self.assertFalse(dec2.allowed)
        self.assertEqual(dec2.violation_code, "APPROVAL_REVOKED")

    # 8. Cryptographic Tamper Detection
    def test_tampered_approval_detected(self):
        appr = self.appr_mgr.issue_direct_approval(
            human="sec_lead:carol",
            agent="agent-alice",
            action="SECRET_READ",
            scope="AWS_DEV_*",
            reason="Dev secret access",
            change=self.change_id,
        )

        # Malicious actor tampers with scope in ledger without re-signing
        ledger = FileLedgerStore.load(self.repo_root)
        ledger["changes"][self.change_id]["approvals"]["authorizations"][appr.approval_id]["scope"] = "*"
        FileLedgerStore.save(self.repo_root, ledger)

        valid, code, _ = self.appr_mgr.validate_approval(
            approval_id=appr.approval_id,
            agent_id="agent-alice",
            change_id=self.change_id,
            operation="SECRET_READ",
            target="AWS_DEV_KEY",
        )
        self.assertFalse(valid)
        self.assertEqual(code, "APPROVAL_TAMPERED")

    # 9. Request Rejection Flow
    def test_request_rejection(self):
        req = self.appr_mgr.create_request(
            agent="agent-alice",
            action="CLOUD_MUTATE",
            scope="aws:s3:::production-db/*",
            reason="Database backup deletion",
            change=self.change_id,
        )
        self.assertEqual(req.status, "PENDING")

        rejected = self.appr_mgr.reject_request(
            request_id=req.request_id,
            human="devops:lead",
            reason="Unapproved deletion policy",
            change_id=self.change_id,
        )
        self.assertEqual(rejected.status, "REJECTED")
        self.assertEqual(rejected.rejection_reason, "Unapproved deletion policy")

        # Approving a rejected request raises an error
        with self.assertRaises(ValueError):
            self.appr_mgr.approve_request(
                request_id=req.request_id,
                human="devops:lead",
                change_id=self.change_id,
            )

    # 10. CLI Approval & Capability Flow
    def test_cli_approval_and_capability_flow(self):
        from contextlib import redirect_stdout
        import io
        import json
        from ship.cli import main

        # 1. Request via CLI
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([
                "approval", "request",
                "--path", str(self.repo_root),
                "--agent", "agent-alice",
                "--action", "SECRET_READ",
                "--scope", "AWS_*",
                "--reason", "CLI test request",
                "--json",
            ])
        self.assertEqual(code, 0)
        req_data = json.loads(buf.getvalue())
        req_id = req_data["request_id"]

        # 2. Approve via CLI
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([
                "approval", "approve", req_id,
                "--path", str(self.repo_root),
                "--human", "sec_lead:carol",
                "--ttl", "1800",
                "--json",
            ])
        self.assertEqual(code, 0)
        appr_data = json.loads(buf.getvalue())
        appr_id = appr_data["approval_id"]

        # 3. Grant capability from approval via CLI
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([
                "capability", "grant",
                "--path", str(self.repo_root),
                "--from-approval", appr_id,
                "--json",
            ])
        self.assertEqual(code, 0)
        cap_data = json.loads(buf.getvalue())
        self.assertEqual(cap_data["approval_ref"], appr_id)

        # 4. Check capability evaluation via CLI
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([
                "capability", "check", "agent-alice",
                "--path", str(self.repo_root),
                "--op", "SECRET_READ",
                "--target", "AWS_ACCESS_KEY_ID",
                "--json",
            ])
        self.assertEqual(code, 0)
        dec_data = json.loads(buf.getvalue())
        self.assertTrue(dec_data["allowed"])

        # 5. Revoke approval via CLI
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([
                "approval", "revoke", appr_id,
                "--path", str(self.repo_root),
                "--human", "sec_lead:carol",
                "--reason", "Revoke CLI test",
                "--json",
            ])
        self.assertEqual(code, 0)

        # 6. Re-check: access should now be DENIED
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([
                "capability", "check", "agent-alice",
                "--path", str(self.repo_root),
                "--op", "SECRET_READ",
                "--target", "AWS_ACCESS_KEY_ID",
                "--json",
            ])
        self.assertEqual(code, 1)
        dec_revoked = json.loads(buf.getvalue())
        self.assertFalse(dec_revoked["allowed"])
        self.assertEqual(dec_revoked["violation_code"], "APPROVAL_REVOKED")


if __name__ == "__main__":
    unittest.main()
