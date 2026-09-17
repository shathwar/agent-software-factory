"""End-to-end workflow trials verifying real agent behavior across operational boundaries."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

import test_archive_recovery as fixtures
lifecycle = fixtures.lifecycle
from lifecycle.evidence import design_fingerprint
from lifecycle.ledger import FileLedgerStore
from lifecycle.transactions import begin_archive
compute_working_tree_fingerprint = lifecycle.compute_working_tree_fingerprint

ROOT = Path(__file__).resolve().parents[1]


class AgentWorkflowTrialTests(unittest.TestCase):
    """Realistic trials testing agent workflow adherence, state guards, and error boundaries."""

    def test_trial_1_existing_uncommitted_work(self):
        """Trial 1: Uncommitted work must block delivery until reviewed; subsequent edits invalidate review."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures.ArchiveRecoveryTests().workspace(root)

            # Initially clean and ready
            self.assertEqual(lifecycle.main(["--path", str(root), "--status-check", "--change", "alpha"]), 0)

            # Introduce uncommitted source modifications and untracked file
            src_dir = root / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            app_file = src_dir / "app.py"
            app_file.write_text("def run(): return 42\n")
            util_file = src_dir / "util.py"
            util_file.write_text("def util(): pass\n")

            # Inspector detects dirty state and unreviewed files
            res = lifecycle.evaluate_repository(root, target_change="alpha")
            self.assertFalse(res["git"]["is_clean"])
            self.assertTrue(any("src" in f for f in res["git"]["modified_source_files"]))

            # Premature delivery/archive is blocked
            self.assertEqual(lifecycle.main(["--path", str(root), "--status-check", "--change", "alpha"]), 1)
            trailers = lifecycle.generate_gate_trailers(root, change_id="alpha")
            self.assertIn("Ship-Delivery: BLOCKED", trailers)
            with self.assertRaisesRegex(RuntimeError, "Cannot archive 'alpha'"):
                lifecycle.apply_and_archive_openspec(root, "alpha")

            # Adversarial review conducted against current dirty working tree snapshot
            report_path = root / ".scratch/alpha/review_report.json"
            report = json.loads(report_path.read_text())
            report["working_tree_fingerprint"] = compute_working_tree_fingerprint(root)
            report_path.write_text(json.dumps(report))
            lifecycle.record_review_to_ledger(root, report_path, change_id="alpha")

            # Now delivery is ready
            res = lifecycle.evaluate_repository(root, target_change="alpha")
            self.assertEqual(res["state_key"], "DELIVERY_READY")
            self.assertEqual(lifecycle.main(["--path", str(root), "--status-check", "--change", "alpha"]), 0)
            self.assertIn("Ship-Delivery: READY", lifecycle.generate_gate_trailers(root, change_id="alpha"))

            # Code modified after review makes the review immediately STALE
            app_file.write_text("def run(): return 99  # post-review modification\n")
            res = lifecycle.evaluate_repository(root, target_change="alpha")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertIn("modified since review", res["next_action"])
            stale_trailers = lifecycle.generate_gate_trailers(root, change_id="alpha")
            self.assertIn("Ship-Review: STALE (modified since review by judge)", stale_trailers)
            self.assertIn("Ship-Delivery: BLOCKED", stale_trailers)
            with self.assertRaisesRegex(RuntimeError, "Cannot archive 'alpha'"):
                lifecycle.apply_and_archive_openspec(root, "alpha")

            # Re-reviewing the updated working tree restores delivery readiness
            report["working_tree_fingerprint"] = compute_working_tree_fingerprint(root)
            report_path.write_text(json.dumps(report))
            lifecycle.record_review_to_ledger(root, report_path, change_id="alpha")
            archive_res = lifecycle.apply_and_archive_openspec(root, "alpha")
            self.assertEqual(archive_res["change"], "alpha")

    def test_trial_2_two_concurrent_changes(self):
        """Trial 2: Working on change B must not overwrite change A's evidence or steal active selection."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures.ArchiveRecoveryTests().workspace(root)

            # Change alpha is ready for delivery; setup concurrent change beta
            beta_pkg = root / "openspec/changes/beta"
            (beta_pkg / "specs").mkdir(parents=True)
            (beta_pkg / "tasks.md").write_text("- [x] Task 1\n- [ ] Task 2\n")
            (beta_pkg / "specs/beta.md").write_text("### Requirement: Beta\nBeta spec\n")
            FileLedgerStore.approve_design(root, "beta", design_fingerprint(root, "beta"), "beta-reviewer")

            # Explicitly select alpha as active
            lifecycle.set_active_change(root, "alpha")
            self.assertEqual(lifecycle.get_active_change(root), "alpha")

            # Bind alpha's review report to current workspace including the new package
            report_path = root / ".scratch/alpha/review_report.json"
            report = json.loads(report_path.read_text())
            report["working_tree_fingerprint"] = compute_working_tree_fingerprint(root)
            report_path.write_text(json.dumps(report))
            lifecycle.record_review_to_ledger(root, report_path, change_id="alpha")

            # Simulate concurrent work on beta: record failing tests, inspect beta
            lifecycle.record_test_run_to_ledger(root, {"passed": False, "failed_count": 1, "exit_code": 1}, change_id="beta")
            beta_eval = lifecycle.evaluate_repository(root, target_change="beta")
            self.assertEqual(beta_eval["state_key"], "TDD_ACTIVE")

            # Alpha must remain active and delivery-ready without pollution
            self.assertEqual(lifecycle.get_active_change(root), "alpha")
            state = json.loads((root / ".ship/state.json").read_text())
            self.assertEqual(state["active_change_id"], "alpha")

            alpha_eval = lifecycle.evaluate_repository(root, target_change="alpha")
            self.assertEqual(alpha_eval["state_key"], "DELIVERY_READY")
            self.assertIn("Ship-Delivery: READY", lifecycle.generate_gate_trailers(root, change_id="alpha"))

            # Default evaluation targets active change alpha
            default_eval = lifecycle.evaluate_repository(root)
            self.assertEqual(default_eval["target_change"], "alpha")
            self.assertEqual(default_eval["state_key"], "DELIVERY_READY")

            # Archive alpha: archives only alpha, leaves beta intact
            archive_res = lifecycle.apply_and_archive_openspec(root, "alpha")
            self.assertEqual(archive_res["change"], "alpha")
            self.assertFalse((root / "openspec/changes/alpha").exists())
            self.assertTrue(beta_pkg.exists())
            self.assertTrue((beta_pkg / "tasks.md").exists())

            # Active pointer cleared on archive; default evaluation cleanly falls back to beta
            self.assertIsNone(lifecycle.get_active_change(root))
            next_eval = lifecycle.evaluate_repository(root)
            self.assertEqual(next_eval["target_change"], "beta")
            self.assertEqual(next_eval["state_key"], "TDD_ACTIVE")

    def test_trial_3_interrupted_sessions_resumption(self):
        """Trial 3: Interrupted sessions resume at the exact next task; crashed transactions self-heal."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "openspec/changes/checkout"
            (pkg / "specs").mkdir(parents=True)
            (pkg / "tasks.md").write_text(
                "- [x] Task 1: Setup schema\n"
                "- [x] Task 2: Implement domain logic\n"
                "- [ ] Task 3: Add discount calculator\n"
                "- [ ] Task 4: Add payment gateway\n"
            )
            (pkg / "specs/checkout.md").write_text("### Requirement: Checkout\nCheckout flow\n")

            for args in [("init", "-b", "main"), ("config", "user.name", "Test"),
                         ("config", "user.email", "test@example.com"), ("config", "commit.gpgsign", "false"),
                         ("add", "."), ("commit", "-m", "initial")]:
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

            FileLedgerStore.approve_design(root, "checkout", design_fingerprint(root, "checkout"), "lead-architect")
            lifecycle.record_test_run_to_ledger(root, {"passed": True, "tests_run": 5, "failed_count": 0, "exit_code": 0}, change_id="checkout")
            lifecycle.sync_ledger_from_workspace(root)

            # Cold resume in new session: evaluates directly to TDD_ACTIVE pointing to Task 3
            res = lifecycle.evaluate_repository(root, target_change="checkout")
            self.assertEqual(res["gate"], "implementation")
            self.assertEqual(res["state_key"], "TDD_ACTIVE")
            self.assertIn("Task 3: Add discount calculator", res["next_action"])
            self.assertIn("Run Red-Green-Refactor", res["next_action"])
            self.assertEqual(res["active_change"]["task_status"]["completed"], 2)
            self.assertEqual(res["active_change"]["task_status"]["total"], 4)

            # Simulate mid-archive crash leaving transaction journal via begin_archive
            op_id = uuid.uuid4().hex
            begin_archive(root, op_id, "checkout", root / "openspec/archive/2026-09-17-checkout", {})
            journal = root / ".ship/archive-transaction.json"
            self.assertTrue(journal.exists())

            # Next CLI / inspection invocation triggers crash recovery automatically
            recovered_eval = lifecycle.evaluate_repository(root, target_change="checkout")
            self.assertFalse(journal.exists())
            self.assertEqual(recovered_eval["state_key"], "TDD_ACTIVE")

    def test_trial_4_rejected_and_amended_design(self):
        """Trial 4: Scope changes invalidate design approval; rejected design blocks advancement until re-approved."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures.ArchiveRecoveryTests().workspace(root)

            # Initially approved and ready
            self.assertEqual(lifecycle.evaluate_repository(root, target_change="alpha")["state_key"], "DELIVERY_READY")

            # User or reviewer amends spec requirement (scope change)
            spec_file = root / "openspec/changes/alpha/specs/new.md"
            spec_file.write_text("### Requirement: Revised\nRevised amended requirement\n")

            # Approval invalidated: gate drops to DESIGN_APPROVAL_REQUIRED
            res = lifecycle.evaluate_repository(root, target_change="alpha")
            self.assertEqual(res["gate"], "design")
            self.assertEqual(res["state_key"], "DESIGN_APPROVAL_REQUIRED")
            self.assertIn("Design changed since approval", res["next_action"])

            # Delivery surfaces reject
            self.assertEqual(lifecycle.main(["--path", str(root), "--status-check", "--change", "alpha"]), 1)
            trailers = lifecycle.generate_gate_trailers(root, change_id="alpha")
            self.assertIn("Ship-Design: BLOCKED", trailers)
            self.assertIn("Ship-Delivery: BLOCKED", trailers)
            with self.assertRaisesRegex(RuntimeError, "Design changed"):
                lifecycle.apply_and_archive_openspec(root, "alpha")

            # Approval using stale digest is rejected
            with self.assertRaisesRegex(ValueError, "Design changed"):
                FileLedgerStore.approve_design(root, "alpha", "0" * 64, "reviewer")

            # Re-approval with exact new digest clears the blocker
            new_digest = design_fingerprint(root, "alpha")
            FileLedgerStore.approve_design(root, "alpha", new_digest, "team-lead")

            # Re-bind review report to current fingerprint and verify readiness
            report_path = root / ".scratch/alpha/review_report.json"
            report = json.loads(report_path.read_text())
            report["working_tree_fingerprint"] = compute_working_tree_fingerprint(root)
            report_path.write_text(json.dumps(report))
            lifecycle.record_review_to_ledger(root, report_path, change_id="alpha")

            res = lifecycle.evaluate_repository(root, target_change="alpha")
            self.assertEqual(res["state_key"], "DELIVERY_READY")
            self.assertIn("Ship-Design: PASSED", lifecycle.generate_gate_trailers(root, change_id="alpha"))

    def test_trial_5_failed_tests_block_advancement(self):
        """Trial 5: Checking task boxes does not bypass failing tests; delivery is blocked until tests pass."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures.ArchiveRecoveryTests().workspace(root)

            # All tasks in tasks.md are checked [x]
            tasks = root / "openspec/changes/alpha/tasks.md"
            self.assertIn("- [x]", tasks.read_text())

            # Record failing test run
            lifecycle.record_test_run_to_ledger(
                root,
                {"passed": False, "failed_count": 2, "exit_code": 1, "command": "pytest"},
                change_id="alpha",
            )

            # State remains strictly in TDD_ACTIVE
            res = lifecycle.evaluate_repository(root, target_change="alpha")
            self.assertEqual(res["gate"], "implementation")
            self.assertEqual(res["state_key"], "TDD_ACTIVE")
            self.assertIn("Blocked by test failure in ledger", res["next_action"])

            # Delivery surfaces blocked
            self.assertEqual(lifecycle.main(["--path", str(root), "--status-check", "--change", "alpha"]), 1)
            trailers = lifecycle.generate_gate_trailers(root, change_id="alpha")
            self.assertIn("Ship-Implementation: FAILED (1/1 tasks)", trailers)
            self.assertIn("Ship-Delivery: BLOCKED", trailers)
            with self.assertRaisesRegex(RuntimeError, "Blocked by test failure in ledger"):
                lifecycle.apply_and_archive_openspec(root, "alpha")

            # Fixing tests and recording green evidence unblocks workflow
            lifecycle.record_test_run_to_ledger(
                root,
                {"passed": True, "tests_run": 12, "failed_count": 0, "exit_code": 0, "command": "pytest"},
                change_id="alpha",
            )

            res = lifecycle.evaluate_repository(root, target_change="alpha")
            self.assertEqual(res["state_key"], "DELIVERY_READY")
            self.assertEqual(lifecycle.main(["--path", str(root), "--status-check", "--change", "alpha"]), 0)
            clean_trailers = lifecycle.generate_gate_trailers(root, change_id="alpha")
            self.assertIn("Ship-Implementation: PASSED (1/1 tasks)", clean_trailers)
            self.assertIn("Ship-Delivery: READY", clean_trailers)

    def test_trial_6_external_installation_and_consumer_project(self):
        """Trial 6: Skills installed outside repository execute cleanly in independent consumer projects."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            install_dir = base / "installed_skills"
            project_dir = base / "consumer_project"
            project_dir.mkdir()

            # Install via install.sh in copy mode
            subprocess.run(
                ["bash", str(ROOT / "scripts/install.sh"), "--target", str(install_dir), "--mode", "copy"],
                check=True,
                capture_output=True,
            )

            script = install_dir / "ship/scripts/inspect_lifecycle.py"

            def cli(*args, code=0):
                result = subprocess.run([sys.executable, str(script), *args], cwd=project_dir, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, f"CLI error: {result.stderr}")
                return result

            # Doctor passes on consumer workspace
            doc = cli("--doctor")
            self.assertIn("OK", doc.stdout)

            # Initialize consumer git repo
            for args in [("init", "-b", "main"), ("config", "user.name", "Consumer"),
                         ("config", "user.email", "consumer@example.com"), ("config", "commit.gpgsign", "false")]:
                subprocess.run(["git", *args], cwd=project_dir, check=True, capture_output=True)
            (project_dir / "README.md").write_text("# Consumer Project\n")
            subprocess.run(["git", "add", "."], cwd=project_dir, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial commit"], cwd=project_dir, check=True, capture_output=True)

            # Scaffold feature 'billing' in consumer project
            change_dir = project_dir / "openspec/changes/billing"
            (change_dir / "specs").mkdir(parents=True)
            (change_dir / "tasks.md").write_text("- [x] 1. Calculate tax rates\n")
            (change_dir / "specs/tax.md").write_text("### Requirement: Tax\nTax calculation spec\n")

            # 1. Design fingerprint & approval
            fp = cli("--change", "billing", "--design-fingerprint").stdout.strip()
            self.assertTrue(bool(fp))
            cli("--change", "billing", "--approve-design", fp, "--approved-by", "lead-engineer")

            # 2. Record passing tests
            cli("--change", "billing", "--record-tests", "pass")

            # 3. Record Judge review report
            review_file = project_dir / ".scratch/billing/review_report.json"
            review_file.parent.mkdir(parents=True, exist_ok=True)
            tree_fp = cli("--fingerprint").stdout.strip()
            review_file.write_text(json.dumps({
                "change": "billing", "reviewer": "judge", "status": "complete", "verdict": "PASS",
                "findings": [], "coverage": ["checked"], "questions": [], "routing_notes": [],
                "test_evidence": True, "working_tree_fingerprint": tree_fp,
            }))
            cli("--change", "billing", "--record-review", str(review_file))

            # 4. Verify delivery readiness via status check
            cli("--status-check")

            # 5. Archive change package
            archive_res = json.loads(cli("--archive", "billing", "--format", "json").stdout)
            self.assertIn("Ship-Delivery: ARCHIVED", archive_res["trailers"])
            self.assertTrue((project_dir / "openspec/specs/tax.md").exists())
            self.assertFalse(change_dir.exists())
            self.assertEqual(len(list((project_dir / "openspec/archive").glob("*-billing*"))), 1)
