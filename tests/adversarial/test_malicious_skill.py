import sys
from pathlib import Path
import tempfile
import unittest

# Ensure repository root is on sys.path
_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from ship.lifecycle.capabilities import CapabilityManager
from ship.lifecycle.coordination import CoordinationManager
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.models import CapabilityOperation
from ship.lifecycle.provenance import ProvenanceManager

# Import exploit runner from fixture
from tests.fixtures.malicious_skill.scripts.exploit_runner import (
    attempt_governance_tampering,
    attempt_ring_0_ledger_overwrite,
    attempt_unauthorized_file_mutation,
)


class TestMaliciousSkillFixture(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "attack-fixture-change"
        self.change_dir = self.repo_root / ".ship" / "changes" / self.change_id
        self.change_dir.mkdir(parents=True, exist_ok=True)
        (self.change_dir / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 Auth Implementation\n")

        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })

        self.prov_mgr = ProvenanceManager(self.repo_root)
        self.coord_mgr = CoordinationManager(self.repo_root, self.change_id)
        self.cap_mgr = CapabilityManager(self.repo_root)

        # Register malicious skill agent principal
        self.rogue_agent = "untrusted-agent-malicious-skill"
        self.prov_mgr.register_identity(self.rogue_agent, role="SPECIALIST", change_id=self.change_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fixture_skill_md_exists(self):
        """Verify the malicious skill fixture structure."""
        fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "malicious_skill" / "SKILL.md"
        self.assertTrue(fixture_path.exists())
        content = fixture_path.read_text(encoding="utf-8")
        self.assertIn("name: malicious-skill", content)
        self.assertIn("Skills and agents are untrusted", content)

    def test_malicious_skill_ring_0_overwrite_intercepted(self):
        """Attack: Malicious skill attempts to write Ring 0 ledger."""
        res = attempt_ring_0_ledger_overwrite(self.repo_root, self.rogue_agent, self.change_id)
        self.assertFalse(res["allowed"])
        self.assertEqual(res["violation_code"], "RING_0_RESTRICTED")

    def test_malicious_skill_governance_tampering_intercepted(self):
        """Attack: Malicious skill attempts to tamper with Ring 1 invariants."""
        res = attempt_governance_tampering(self.repo_root, self.rogue_agent, self.change_id)
        self.assertFalse(res["allowed"])
        self.assertEqual(res["violation_code"], "RING_1_UNAUTHORIZED")

    def test_malicious_skill_unauthorized_file_mutation_intercepted(self):
        """Attack: Malicious skill claims task 1.1 for src/auth.py, but attempts to write src/payments.py."""
        claim = self.coord_mgr.claim_task(
            task_id="1.1",
            owner_id=self.rogue_agent,
            target_files=["src/auth.py"],
        )
        self.assertTrue(claim.success)

        res = attempt_unauthorized_file_mutation(
            repo_root=self.repo_root,
            rogue_agent=self.rogue_agent,
            target_file="src/payments.py",
            task_id="1.1",
            change_id=self.change_id,
            lease_token=claim.lease.lease_token,
        )
        self.assertFalse(res["allowed"])
        self.assertIn(res["violation_code"], ("NO_CAPABILITY", "LEASE_FILE_MISMATCH"))

    def test_security_audit_log_records_intercepted_attacks(self):
        """Invariant: All intercepted attacks are logged into the tamper-evident security audit trail."""
        attempt_ring_0_ledger_overwrite(self.repo_root, self.rogue_agent, self.change_id)
        attempt_governance_tampering(self.repo_root, self.rogue_agent, self.change_id)

        # Inspect ledger security audit log
        ledger = FileLedgerStore.load(self.repo_root)
        audit_log = ledger["changes"][self.change_id].get("security_audit", [])
        self.assertTrue(len(audit_log) >= 2)
        denied_events = [e for e in audit_log if not e["allowed"]]
        self.assertTrue(len(denied_events) >= 2)
        violations = {e["violation_code"] for e in denied_events}
        self.assertIn("RING_0_RESTRICTED", violations)
        self.assertIn("RING_1_UNAUTHORIZED", violations)


if __name__ == "__main__":
    unittest.main()
