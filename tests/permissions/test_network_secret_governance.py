"""Unit and adversarial tests for Network & Secret Governance capabilities and policy gates."""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.capabilities import CapabilityManager, _target_matches
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.models import CapabilityOperation, ExecutionRing
from ship.lifecycle.provenance import ProvenanceManager


class TestNetworkSecretGovernance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "gov-change-1"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })
        self.prov_mgr = ProvenanceManager(self.repo_root)
        self.cap_mgr = CapabilityManager(self.repo_root)

        self.prov_mgr.register_identity("agent-worker", role="MAKER", change_id=self.change_id)
        self.prov_mgr.register_identity("agent-rogue", role="MAKER", change_id=self.change_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    # 1. Target matching tests
    def test_target_matches_url_and_hostname(self):
        # Exact host
        self.assertTrue(_target_matches("api.github.com", "https://api.github.com/repos/org/repo"))
        self.assertFalse(_target_matches("api.github.com", "https://evil.github.com/repos/org/repo"))

        # Wildcard host
        self.assertTrue(_target_matches("*.npmjs.org", "https://registry.npmjs.org/express"))
        self.assertFalse(_target_matches("*.npmjs.org", "https://evil-npmjs.org/express"))

        # URL prefix
        self.assertTrue(_target_matches("https://pypi.org/*", "https://pypi.org/simple/requests/"))
        self.assertFalse(_target_matches("https://pypi.org/*", "https://evil-pypi.org/simple/requests/"))

    def test_target_matches_secret_case_insensitive(self):
        self.assertTrue(_target_matches("AWS_*", "aws_secret_access_key"))
        self.assertTrue(_target_matches("OPENAI_API_KEY", "openai_api_key"))
        self.assertTrue(_target_matches("secret:stripe_*", "secret:stripe_live_key"))

    def test_target_matches_namespace_prefix(self):
        self.assertTrue(_target_matches("aws:s3", "aws:s3:::my-bucket/data"))
        self.assertTrue(_target_matches("github:pr", "github:pr:merge"))
        self.assertFalse(_target_matches("github:pr", "github:release:publish"))

    # 2. Ring Classification
    def test_ring_classification(self):
        # Network read/write -> Ring 3 Workspace
        self.assertEqual(
            self.cap_mgr.classify_target_ring("https://example.com/api", CapabilityOperation.NETWORK_READ),
            ExecutionRing.RING_3_WORKSPACE
        )
        self.assertEqual(
            self.cap_mgr.classify_target_ring("https://example.com/api", CapabilityOperation.NETWORK_WRITE),
            ExecutionRing.RING_3_WORKSPACE
        )

        # Secret Read, Cloud Mutate, GitHub Write -> Ring 1 Governance
        self.assertEqual(
            self.cap_mgr.classify_target_ring("secret:vault_token", CapabilityOperation.SECRET_READ),
            ExecutionRing.RING_1_GOVERNANCE
        )
        self.assertEqual(
            self.cap_mgr.classify_target_ring("aws:s3:::prod-bucket", CapabilityOperation.CLOUD_MUTATE),
            ExecutionRing.RING_1_GOVERNANCE
        )
        self.assertEqual(
            self.cap_mgr.classify_target_ring("github:pr:create", CapabilityOperation.GITHUB_WRITE),
            ExecutionRing.RING_1_GOVERNANCE
        )
        self.assertEqual(
            self.cap_mgr.classify_target_ring(".env", CapabilityOperation.READ),
            ExecutionRing.RING_1_GOVERNANCE
        )

    # 3. Network Read Governance
    def test_network_read_authorized_vs_unauthorized(self):
        # Grant scoped network read
        self.cap_mgr.grant_capability(
            agent_id="agent-worker",
            operation=CapabilityOperation.NETWORK_READ,
            target="https://registry.npmjs.org/*",
            change_id=self.change_id,
        )

        # Scoped target ALLOWED
        dec_allow = self.cap_mgr.evaluate_access(
            agent_id="agent-worker",
            operation=CapabilityOperation.NETWORK_READ,
            target="https://registry.npmjs.org/lodash",
            change_id=self.change_id,
        )
        self.assertTrue(dec_allow.allowed)
        self.assertEqual(dec_allow.ring, ExecutionRing.RING_3_WORKSPACE.value)

        # Out-of-scope target DENIED
        dec_deny = self.cap_mgr.evaluate_access(
            agent_id="agent-worker",
            operation=CapabilityOperation.NETWORK_READ,
            target="https://attacker-c2.com/payload",
            change_id=self.change_id,
        )
        self.assertFalse(dec_deny.allowed)
        self.assertEqual(dec_deny.violation_code, "NO_CAPABILITY")

    # 4. Network Write Governance & Policy Gate 6
    def test_network_write_requires_security_or_tech_lead_approval(self):
        # Rogue agent grants itself network write with invalid approval
        self.cap_mgr.grant_capability(
            agent_id="agent-rogue",
            operation=CapabilityOperation.NETWORK_WRITE,
            target="https://api.telegram.org/*",
            change_id=self.change_id,
            approval_ref="self-approved",
        )

        dec_unauth = self.cap_mgr.evaluate_access(
            agent_id="agent-rogue",
            operation=CapabilityOperation.NETWORK_WRITE,
            target="https://api.telegram.org/bot123/send",
            change_id=self.change_id,
        )
        self.assertFalse(dec_unauth.allowed)
        self.assertEqual(dec_unauth.violation_code, "NETWORK_WRITE_UNAUTHORIZED")

        # Worker agent has valid approval from sec_lead
        self.cap_mgr.grant_capability(
            agent_id="agent-worker",
            operation=CapabilityOperation.NETWORK_WRITE,
            target="https://api.slack.com/*",
            change_id=self.change_id,
            approval_ref="sec_lead:incident-webhook",
        )

        dec_auth = self.cap_mgr.evaluate_access(
            agent_id="agent-worker",
            operation=CapabilityOperation.NETWORK_WRITE,
            target="https://api.slack.com/webhook",
            change_id=self.change_id,
        )
        self.assertTrue(dec_auth.allowed)

    # 5. Secret Read Governance & Policy Gate 7
    def test_secret_read_requires_sec_lead_or_system_approval(self):
        # Worker has tech_lead approval, but SECRET_READ strictly requires sec_lead, security, human, or system
        self.cap_mgr.grant_capability(
            agent_id="agent-worker",
            operation=CapabilityOperation.SECRET_READ,
            target="AWS_SECRET_ACCESS_KEY",
            change_id=self.change_id,
            approval_ref="tech_lead:general-dev",
        )

        dec_unauth = self.cap_mgr.evaluate_access(
            agent_id="agent-worker",
            operation=CapabilityOperation.SECRET_READ,
            target="AWS_SECRET_ACCESS_KEY",
            change_id=self.change_id,
        )
        self.assertFalse(dec_unauth.allowed)
        self.assertEqual(dec_unauth.violation_code, "SECRET_ACCESS_UNAUTHORIZED")

        # Now grant with sec_lead approval
        self.cap_mgr.grant_capability(
            agent_id="agent-worker",
            operation=CapabilityOperation.SECRET_READ,
            target="AWS_SECRET_ACCESS_KEY",
            change_id=self.change_id,
            approval_ref="sec_lead:audit-123",
        )

        dec_auth = self.cap_mgr.evaluate_access(
            agent_id="agent-worker",
            operation=CapabilityOperation.SECRET_READ,
            target="AWS_SECRET_ACCESS_KEY",
            change_id=self.change_id,
        )
        self.assertTrue(dec_auth.allowed)
        self.assertEqual(dec_auth.ring, ExecutionRing.RING_1_GOVERNANCE.value)

    # 6. Cloud Mutate Governance & Policy Gate 8
    def test_cloud_mutate_requires_devops_or_tech_lead_approval(self):
        self.cap_mgr.grant_capability(
            agent_id="agent-rogue",
            operation=CapabilityOperation.CLOUD_MUTATE,
            target="aws:s3:::prod-bucket/*",
            change_id=self.change_id,
            approval_ref="maker:deploy",
        )

        dec_unauth = self.cap_mgr.evaluate_access(
            agent_id="agent-rogue",
            operation=CapabilityOperation.CLOUD_MUTATE,
            target="aws:s3:::prod-bucket/database.dump",
            change_id=self.change_id,
        )
        self.assertFalse(dec_unauth.allowed)
        self.assertEqual(dec_unauth.violation_code, "CLOUD_MUTATE_UNAUTHORIZED")

        # Valid devops approval
        self.cap_mgr.grant_capability(
            agent_id="agent-worker",
            operation=CapabilityOperation.CLOUD_MUTATE,
            target="aws:s3:::prod-bucket/*",
            change_id=self.change_id,
            approval_ref="devops:terraform-pipeline",
        )

        dec_auth = self.cap_mgr.evaluate_access(
            agent_id="agent-worker",
            operation=CapabilityOperation.CLOUD_MUTATE,
            target="aws:s3:::prod-bucket/database.dump",
            change_id=self.change_id,
        )
        self.assertTrue(dec_auth.allowed)

    # 7. GitHub Write Governance & Policy Gate 9
    def test_github_write_requires_maintainer_approval(self):
        self.cap_mgr.grant_capability(
            agent_id="agent-rogue",
            operation=CapabilityOperation.GITHUB_WRITE,
            target="github:pr:merge",
            change_id=self.change_id,
            approval_ref="developer:quick-merge",
        )

        dec_unauth = self.cap_mgr.evaluate_access(
            agent_id="agent-rogue",
            operation=CapabilityOperation.GITHUB_WRITE,
            target="github:pr:merge",
            change_id=self.change_id,
        )
        self.assertFalse(dec_unauth.allowed)
        self.assertEqual(dec_unauth.violation_code, "GITHUB_WRITE_UNAUTHORIZED")

        # Valid maintainer approval
        self.cap_mgr.grant_capability(
            agent_id="agent-worker",
            operation=CapabilityOperation.GITHUB_WRITE,
            target="github:pr:*",
            change_id=self.change_id,
            approval_ref="maintainer:release-lead",
        )

        dec_auth = self.cap_mgr.evaluate_access(
            agent_id="agent-worker",
            operation=CapabilityOperation.GITHUB_WRITE,
            target="github:pr:create",
            change_id=self.change_id,
        )
        self.assertTrue(dec_auth.allowed)

    # 8. Security Audit Ledger Trails
    def test_decisions_recorded_in_audit_ledger(self):
        self.cap_mgr.grant_capability(
            agent_id="agent-rogue",
            operation=CapabilityOperation.SECRET_READ,
            target="secret:db_password",
            change_id=self.change_id,
            approval_ref="untrusted",
        )

        self.cap_mgr.evaluate_access(
            agent_id="agent-rogue",
            operation=CapabilityOperation.SECRET_READ,
            target="secret:db_password",
            change_id=self.change_id,
        )

        ledger = FileLedgerStore.load(self.repo_root)
        records = ledger.get("changes", {}).get(self.change_id, {}).get("security_audit", [])
        self.assertTrue(len(records) >= 1)
        latest = records[-1]
        self.assertFalse(latest["allowed"])
        self.assertEqual(latest["agent_id"], "agent-rogue")
        self.assertEqual(latest["operation"], "SECRET_READ")
        self.assertEqual(latest["violation_code"], "SECRET_ACCESS_UNAUTHORIZED")


if __name__ == "__main__":
    unittest.main()
