"""Adversarial verification tests: fabricated verification, evidence tampering post-verification, contradictory claims, hallucinated findings."""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.models import ActionProvenance, VerificationRecord
from ship.lifecycle.provenance import ProvenanceManager, compute_payload_digest
from ship.lifecycle.verification import (
    execute_and_verify_tests,
    verify_finding_grounding,
)


class TestVerificationAttacks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "attack-verif-change"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {self.change_id: {}},
        })
        self.prov_mgr = ProvenanceManager(self.repo_root)

        self.maker = self.prov_mgr.register_identity("agent-maker", role="MAKER", change_id=self.change_id)
        self.verifier = self.prov_mgr.register_identity("agent-verifier", role="VERIFIER", change_id=self.change_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fabricated_self_verification_rejected(self):
        """Attack: Maker agent attempts to generate a self-signed verification record."""
        prov = self.prov_mgr.build_action_provenance(
            action_name="code_change",
            agent_id="agent-maker",
            change_id=self.change_id,
        )

        forged_verif = VerificationRecord(
            claim="tests_pass",
            gate="implementation",
            tier="execution",
            verdict="VERIFIED",
            method="fake_runner",
            verifier_id="agent-maker",
            provenance={"agent_id": "agent-maker", "role": "VERIFIER"},
        )

        res = self.prov_mgr.verify_binding_chain(provenance=prov, verification_record=forged_verif)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Maker-Checker violation" in e for e in res["errors"]))

    def test_modify_evidence_after_verification_detected(self):
        """Attack: Evidence payload is tampered with post-verification."""
        original_evidence = {"tests_passed": 42, "checksum": "abc123xyz"}
        original_digest = compute_payload_digest(original_evidence)

        prov = self.prov_mgr.build_action_provenance(
            action_name="run_tests",
            agent_id="agent-maker",
            change_id=self.change_id,
            evidence=original_evidence,
        )
        self.assertEqual(prov.evidence_digest, original_digest)

        # Tampered evidence (e.g. agent edits test report to hide failures)
        tampered_evidence = {"tests_passed": 42, "checksum": "abc123xyz", "hidden_failures": 1}
        tampered_digest = compute_payload_digest(tampered_evidence)

        # Verify that digest mismatch breaks the cryptographic attribution
        self.assertNotEqual(original_digest, tampered_digest)
        self.assertNotEqual(prov.evidence_digest, tampered_digest)

    def test_contradictory_test_evidence_caught(self):
        """Attack: Agent claims tests passed, but independent subprocess execution fails."""
        # Using a failing shell command: exit 1
        record = execute_and_verify_tests(
            repo_root=self.repo_root,
            test_command="exit 1",
            claimed_evidence={"tests_passed": True, "exit_code": 0},
        )
        self.assertEqual(record.verdict, "NOT_VERIFIED")
        self.assertTrue(any("CONTRADICTION DETECTED" in f for f in record.findings))

    def test_hallucinated_review_finding_rejected_by_grounding(self):
        """Attack: Reviewer invents a finding on a non-existent file or out-of-range lines."""
        # Non-existent file
        finding_fake_file = {
            "id": "FINDING-001",
            "file": "src/does_not_exist.py",
            "line": "L10-L20",
            "evidence": "def fake(): pass",
        }
        ok1, reason1 = verify_finding_grounding(finding_fake_file, self.repo_root)
        self.assertFalse(ok1)
        self.assertIn("does not exist", reason1)

        # Real file, but line out of range
        real_file = self.repo_root / "src" / "real.py"
        real_file.parent.mkdir(parents=True, exist_ok=True)
        real_file.write_text("print('hello')\n")  # 1 line

        finding_out_of_bounds = {
            "id": "FINDING-002",
            "file": "src/real.py",
            "line": "L100-L110",
            "evidence": "def non_existent_code(): pass",
        }
        ok2, reason2 = verify_finding_grounding(finding_out_of_bounds, self.repo_root)
        self.assertFalse(ok2)
        self.assertIn("beyond file length", reason2)


if __name__ == "__main__":
    unittest.main()
