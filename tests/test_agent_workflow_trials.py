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
            report_path = root / ".agentflow/reviews/alpha/review_report.json"
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
            report_path = root / ".agentflow/reviews/alpha/review_report.json"
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
            state = json.loads((root / ".agentflow/state.json").read_text())
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
            journal = root / ".agentflow/archive-transaction.json"
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
            report_path = root / ".agentflow/reviews/alpha/review_report.json"
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
            review_file = project_dir / ".agentflow/reviews/billing/review_report.json"
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

    def test_trial_7_harness_independence_and_turn_provenance(self):
        """Trial 7: SDLC executes as independent turns across distinct harnesses with full provenance reconstruction."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            # Initialize git repository
            for args in [("init", "-b", "main"), ("config", "user.name", "Developer"),
                         ("config", "user.email", "dev@example.com"), ("config", "commit.gpgsign", "false")]:
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            (root / "README.md").write_text("# Project\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)

            change_id = "inventory"

            # ------------------------------------------------------------------
            # Turn 1: Claude Code Harness - Design Turn
            # ------------------------------------------------------------------
            turn1_contract = lifecycle.get_next_turn_contract(lifecycle.evaluate_repository(root))
            self.assertEqual(turn1_contract.skill, "design")
            self.assertEqual(turn1_contract.role, "Senior Principal Systems Architect")

            # Specialist executes design activity and compiles OpenSpec package
            change_dir = root / f"openspec/changes/{change_id}"
            (change_dir / "specs").mkdir(parents=True)
            (change_dir / "proposal.md").write_text("# Proposal: Inventory Tracking\n")
            (change_dir / "tasks.md").write_text("- [x] Task 1: Deduct stock on checkout\n")
            (change_dir / "specs/stock.md").write_text("### Requirement: Stock Deduction\nEnsure atomic stock decrement\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "docs: design inventory spec"], cwd=root, check=True, capture_output=True)

            dfp = design_fingerprint(root, change_id)
            self.assertTrue(bool(dfp))

            # Record Turn 1 provenance
            lifecycle.record_turn_to_ledger(root, {
                "skill": "design",
                "harness": "claude-code",
                "execution_mode": "sequential",
                "inputs": {"proposal": "Inventory Tracking", "commit": "initial"},
                "evidence": {"design_fingerprint": dfp, "specs": ["stock.md"]},
                "state_delta": {"phase": "SPEC_CONFIRMED"},
            }, change_id=change_id)

            # ------------------------------------------------------------------
            # Turn 2: Cursor Harness - Design Approval Turn
            # ------------------------------------------------------------------
            turn2_contract = lifecycle.get_next_turn_contract(lifecycle.evaluate_repository(root, target_change=change_id))
            self.assertEqual(turn2_contract.skill, "design")
            self.assertEqual(turn2_contract.phase, "DESIGN_APPROVAL_REQUIRED")

            # Developer confirms design in Cursor composer
            FileLedgerStore.approve_design(root, change_id, dfp, "lead-architect")
            lifecycle.set_active_change(root, change_id)

            # ------------------------------------------------------------------
            # Turn 3: OpenCode Harness - TDD Implementation Turn
            # ------------------------------------------------------------------
            # Implement domain code and test
            src_file = root / "inventory.py"
            src_file.write_text("def deduct_stock(qty, item): return qty - item\n")
            test_file = root / "test_inventory.py"
            test_file.write_text("from inventory import deduct_stock\ndef test_deduct(): assert deduct_stock(10, 2) == 8\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "feat: implement stock deduction with tests"], cwd=root, check=True, capture_output=True)

            # Record passing test run with OpenCode harness
            lifecycle.record_test_run_to_ledger(
                root,
                {"passed": True, "tests_run": 1, "failed_count": 0, "command": "pytest test_inventory.py"},
                change_id=change_id,
            )

            # ------------------------------------------------------------------
            # Turn 4: CI/CD Headless Harness - Adversarial Review Turn
            # ------------------------------------------------------------------
            turn4_contract = lifecycle.get_next_turn_contract(lifecycle.evaluate_repository(root, target_change=change_id))
            self.assertEqual(turn4_contract.skill, "review")
            self.assertEqual(turn4_contract.phase, "REVIEW_ACTIVE")

            # Review Judge executes and generates delivery evidence envelope
            tree_fp = compute_working_tree_fingerprint(root)
            review_file = root / f".agentflow/reviews/{change_id}/review_report.json"
            review_file.parent.mkdir(parents=True, exist_ok=True)
            review_file.write_text(json.dumps({
                "change": change_id, "reviewer": "judge", "status": "complete", "verdict": "PASS",
                "findings": [], "coverage": ["stock.md", "inventory.py"], "questions": [], "routing_notes": [],
                "test_evidence": True, "working_tree_fingerprint": tree_fp,
            }))
            lifecycle.record_review_to_ledger(root, str(review_file), change_id=change_id)

            # ------------------------------------------------------------------
            # Turn 5: Release Orchestrator - Delivery & Archive Turn
            # ------------------------------------------------------------------
            turn5_contract = lifecycle.get_next_turn_contract(lifecycle.evaluate_repository(root, target_change=change_id))
            self.assertEqual(turn5_contract.skill, "delivery")
            self.assertEqual(turn5_contract.phase, "DELIVERY_READY")

            self.assertEqual(lifecycle.main(["--path", str(root), "--status-check", "--change", change_id]), 0)
            archive_res = lifecycle.apply_and_archive_openspec(root, change_id)
            self.assertEqual(archive_res["change"], change_id)
            self.assertTrue((root / "openspec/specs/stock.md").exists())
            self.assertFalse(change_dir.exists())

            # ------------------------------------------------------------------
            # Provenance Reconstruction Verification
            # ------------------------------------------------------------------
            state = json.loads((root / ".agentflow/state.json").read_text())
            turns = state["changes"][change_id].get("turns", [])
            self.assertGreaterEqual(len(turns), 4)

            # Reconstruct: which skill ran, against what inputs, what evidence it produced, and state effects
            skills_executed = [t["skill"] for t in turns]
            self.assertIn("design", skills_executed)
            self.assertIn("tdd", skills_executed)
            self.assertIn("review", skills_executed)

            # Reconstruct harnesses involved
            harnesses = [t.get("harness") for t in turns]
            self.assertIn("claude-code", harnesses)

            # Verify inputs and evidence preserved
            design_turn = next(t for t in turns if t["skill"] == "design" and t.get("harness") == "claude-code")
            self.assertEqual(design_turn["inputs"]["proposal"], "Inventory Tracking")
            self.assertEqual(design_turn["evidence"]["design_fingerprint"], dfp)

            tdd_turn = next(t for t in turns if t["skill"] == "tdd")
            self.assertTrue(tdd_turn["evidence"]["tests_passed"])

            review_turn = next(t for t in turns if t["skill"] == "review")
            self.assertEqual(review_turn["evidence"]["verdict"], "PASS")

            # Final trailers check
            trailers = lifecycle.generate_gate_trailers(root, change_id=change_id)
            self.assertIn("Ship-Delivery: ARCHIVED", trailers)
