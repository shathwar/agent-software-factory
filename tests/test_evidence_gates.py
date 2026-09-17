"""Approval and test evidence contracts exercised through public workflow operations."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import test_archive_recovery as recovery
lifecycle = recovery.lifecycle
from lifecycle.evidence import design_fingerprint, is_test_evidence_passing
from lifecycle.ledger import FileLedgerStore


class EvidenceGateTests(unittest.TestCase):
    def test_contradictory_results_block_every_delivery_surface(self):
        summaries = [
            {"passed": "false", "failed_count": 3},
            {"passed": True, "failed_count": 3, "exit_code": 1},
            {"passed": True, "failures": "0"},
            {"passed": True, "failed_count": -1},
            {"passed": True, "exit_code": False},
            {"passed": True, "tests_run": True},
            {"passed": True, "test_evidence": {"passed": False}},
        ]
        for summary in summaries:
            with self.subTest(summary=summary), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                recovery.ArchiveRecoveryTests().workspace(root)
                self.assertFalse(is_test_evidence_passing(summary))
                entry = lifecycle.record_test_run_to_ledger(root, summary, change_id="alpha")
                self.assertIs(entry["evidence"]["implementation"]["tests_passed"], False)
                self.assertEqual(lifecycle.evaluate_repository(root, target_change="alpha")["state_key"], "TDD_ACTIVE")
                self.assertIn("Ship-Delivery: BLOCKED", lifecycle.generate_gate_trailers(root, change_id="alpha"))
                with self.assertRaises(RuntimeError):
                    lifecycle.apply_and_archive_openspec(root, "alpha")
                lifecycle.record_test_run_to_ledger(root, {"passed": True, "tests_run": 4, "failed_count": 0, "exit_code": 0}, change_id="alpha")
                self.assertEqual(lifecycle.evaluate_repository(root, target_change="alpha")["state_key"], "DELIVERY_READY")

    def test_design_approval_and_reapproval_use_reviewed_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recovery.ArchiveRecoveryTests().workspace(root)
            FileLedgerStore.mutate_change(root, "alpha", lambda e: e["evidence"]["design"].pop("approval"))
            self.assertEqual(lifecycle.evaluate_repository(root, target_change="alpha")["state_key"], "DESIGN_APPROVAL_REQUIRED")
            self.assertIn("Ship-Design: BLOCKED", lifecycle.generate_gate_trailers(root, change_id="alpha"))
            with self.assertRaisesRegex(RuntimeError, "Design approval"):
                lifecycle.apply_and_archive_openspec(root, "alpha")
            digest = design_fingerprint(root, "alpha")
            before = (root / ".ship/state.json").read_bytes()
            for approver in (None, "", " "):
                with self.assertRaises(ValueError):
                    FileLedgerStore.approve_design(root, "alpha", digest, approver)
            self.assertEqual((root / ".ship/state.json").read_bytes(), before)
            args = ["--path", str(root), "--change", "alpha", "--approve-design", digest, "--approved-by", "reviewer@example.org"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(lifecycle.main(args), 0)
            self.assertEqual(lifecycle.evaluate_repository(root, target_change="alpha")["state_key"], "DELIVERY_READY")
            tasks = root / "openspec/changes/alpha/tasks.md"
            tasks.write_text("- [ ] Done\n")
            self.assertEqual(design_fingerprint(root, "alpha"), digest)
            self.assertEqual(lifecycle.evaluate_repository(root, target_change="alpha")["state_key"], "TDD_ACTIVE")
            tasks.write_text("- [x] Different scope\n")
            self.assertEqual(lifecycle.evaluate_repository(root, target_change="alpha")["state_key"], "DESIGN_APPROVAL_REQUIRED")
            before = (root / ".ship/state.json").read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(lifecycle.main(args), 1)
            self.assertEqual((root / ".ship/state.json").read_bytes(), before)
            report_path = root / ".scratch/alpha/review_report.json"
            report = json.loads(report_path.read_text())
            report["working_tree_fingerprint"] = lifecycle.compute_working_tree_fingerprint(root)
            report_path.write_text(json.dumps(report))
            with self.assertRaisesRegex(RuntimeError, "Design changed"):
                lifecycle.apply_and_archive_openspec(root, "alpha")
            FileLedgerStore.approve_design(root, "alpha", design_fingerprint(root, "alpha"), "reviewer@example.org")
            self.assertEqual(lifecycle.evaluate_repository(root, target_change="alpha")["state_key"], "DELIVERY_READY")

    def test_design_files_and_adrs_invalidate_but_source_changes_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recovery.ArchiveRecoveryTests().workspace(root)
            original = design_fingerprint(root, "alpha")
            (root / "source.py").write_text("x = 1\n")
            self.assertEqual(design_fingerprint(root, "alpha"), original)
            adr = root / "docs/adr/decision.md"
            adr.parent.mkdir(parents=True)
            adr.write_text("Decision\n")
            self.assertNotEqual(design_fingerprint(root, "alpha"), original)
            adr.unlink()
            self.assertEqual(design_fingerprint(root, "alpha"), original)
            spec = root / "openspec/changes/alpha/specs/new.md"
            spec.unlink()
            self.assertNotEqual(design_fingerprint(root, "alpha"), original)

    def test_sync_cannot_recreate_approval_or_accept_legacy_malformed_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recovery.ArchiveRecoveryTests().workspace(root)
            FileLedgerStore.mutate_change(root, "alpha", lambda e: e["evidence"]["implementation"].update(status="PASSED", tests_passed="false", failed_count=3))
            lifecycle.sync_ledger_from_workspace(root)
            self.assertEqual(lifecycle.evaluate_repository(root, target_change="alpha")["state_key"], "TDD_ACTIVE")
            (root / ".ship/state.json").unlink()
            lifecycle.sync_ledger_from_workspace(root)
            self.assertEqual(lifecycle.evaluate_repository(root, target_change="alpha")["state_key"], "DESIGN_APPROVAL_REQUIRED")
