"""Unit tests for ship lifecycle inspector (inspect_lifecycle.py)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
INSPECT_LIFECYCLE = ROOT / "skills" / "ship" / "scripts" / "inspect_lifecycle.py"

sys.path.insert(0, str(INSPECT_LIFECYCLE.parent))
import inspect_lifecycle
from verification_fixture import verify_fixture


class TestInspectLifecycle(unittest.TestCase):
    def _approve_design(self, root):
        from lifecycle.evidence import design_fingerprint
        from lifecycle.ledger import FileLedgerStore
        for package in (root / "openspec/changes").glob("*"):
            if package.is_dir():
                FileLedgerStore.approve_design(root, package.name, design_fingerprint(root, package.name), "test-reviewer")
        verify_fixture(root)

    def _init_git_repo(self, tmppath: Path, branch: str = "main") -> None:
        subprocess.run(["git", "init", "-b", branch], cwd=tmppath, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmppath, check=True)

    def test_gate1_empty_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            res = inspect_lifecycle.evaluate_repository(Path(tmpdir))
            self.assertEqual(res["gate"], "design")
            self.assertEqual(res["state_key"], "INITIAL_PROPOSAL")
            self.assertIn("Run '/design'", res["next_action"])

    def test_gate1b_active_spike(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            spike_dir = tmppath / ".scratch" / "spike_redis_perf"
            spike_dir.mkdir(parents=True)

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "spike")
            self.assertEqual(res["state_key"], "SPIKE_ACTIVE")
            self.assertIn("spike_redis_perf", res["next_action"])

    def test_gate1_adr_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            adr_dir = tmppath / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "ADR-0001-events.md").write_text("# ADR\n**Status**: ACCEPTED\n")

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "design")
            self.assertEqual(res["state_key"], "ADR_ACCEPTED")
            self.assertEqual(len(res["adrs"]), 1)
            self.assertEqual(res["adrs"][0]["status"], "ACCEPTED")

    def test_gate1_adr_proposed_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            adr_dir = tmppath / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "ADR-0001-events.md").write_text("# ADR\n**Status**: PROPOSED\n")

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "design")
            self.assertEqual(res["state_key"], "ADR_PROPOSED")
            self.assertIn("seek user acceptance", res["next_action"])

    def test_normalize_req_title_strips_brackets_and_formatting(self):
        self.assertEqual(inspect_lifecycle.normalize_req_title("[User Authentication]"), "user authentication")
        self.assertEqual(inspect_lifecycle.normalize_req_title("**User Authentication**"), "user authentication")
        self.assertEqual(inspect_lifecycle.normalize_req_title("User Authentication (STATUS: REMOVED)"), "user authentication")

    def test_gate2_tdd_active_with_pending_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "webhooks"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "proposal.md").write_text("# Webhooks\n")
            (pkg_dir / "tasks.md").write_text(
                "# Tasks\n"
                "- [x] 1. Setup endpoint\n"
                "- [ ] 2. Handle retries with jitter\n"
                "- [ ] 3. Verify signature\n"
            )

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "implementation")
            self.assertEqual(res["state_key"], "TDD_ACTIVE")
            self.assertIn("1/3 tasks complete", res["next_action"])
            self.assertIn("2. Handle retries with jitter", res["next_action"])

    def test_gate3_review_active_when_tasks_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "webhooks"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text(
                "# Tasks\n"
                "- [x] 1. Setup endpoint\n"
                "- [x] 2. Handle retries with jitter\n"
            )

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertIn("review-loop mode", res["next_action"])

    def test_gate4_ready_to_ship_with_passed_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "webhooks"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text(
                "# Tasks\n"
                "- [x] 1. All done\n"
            )
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            (scratch_dir / "review_report.json").write_text(
                json.dumps({
                    "change": "webhooks",
                    "reviewer": "judge",
                    "status": "complete",
                    "verdict": "PASS",
                    "findings": [],
                    "coverage": ["Reviewed webhooks."],
                    "questions": [],
                    "routing_notes": [],
                    "test_evidence": True,
                })
            )

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "delivery")
            self.assertEqual(res["state_key"], "DELIVERY_READY")
            self.assertIn("Delivery Walkthrough", res["next_action"])

    def test_gate3_critical_findings_prevent_ship(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "webhooks"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            (scratch_dir / "review_report.json").write_text(
                json.dumps({
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [{"id": "FINDING-001", "severity": "CRITICAL"}],
                    "test_evidence": True,
                })
            )

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertIn("unresolved CRITICAL/HIGH finding(s)", res["next_action"])

    def test_gate3_specialist_report_prevents_ship(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "webhooks"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            (scratch_dir / "review_report.json").write_text(
                json.dumps({
                    "reviewer": "correctness",
                    "status": "complete",
                    "findings": [],
                    "test_evidence": True,
                })
            )

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertIn("Requires explicit Judge adjudication", res["next_action"])

    def test_gate3_missing_test_evidence_prevents_ship(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "webhooks"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            (scratch_dir / "review_report.json").write_text(
                json.dumps({
                    "reviewer": "judge",
                    "status": "complete",
                    "verdict": "PASS",
                    "findings": [],
                })
            )

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertIn("lacks verified test evidence", res["next_action"])

    def test_cli_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [sys.executable, str(INSPECT_LIFECYCLE), "--path", str(tmpdir), "--format", "json"]
            run = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0)
            data = json.loads(run.stdout)
            self.assertEqual(data["gate"], "design")
            self.assertEqual(data["state_key"], "INITIAL_PROPOSAL")

    def test_apply_and_archive_openspec(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "billing"
            specs_dir = pkg_dir / "specs"
            specs_dir.mkdir(parents=True)
            (pkg_dir / "proposal.md").write_text("# Proposal\n")
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")
            (specs_dir / "invoices.md").write_text("# Invoice Spec\n")

            # With force=True to bypass review requirement in unit test
            res = inspect_lifecycle.apply_and_archive_openspec(tmppath, "billing", force=True)
            self.assertEqual(res["change"], "billing")
            self.assertIn("invoices.md", res["synced_specs"])

            # Verify living spec was synced
            living_spec = tmppath / "openspec" / "specs" / "invoices.md"
            self.assertTrue(living_spec.exists())
            self.assertIn("# Invoice Spec", living_spec.read_text())

            # Verify original change was archived
            self.assertFalse(pkg_dir.exists())
            archive_dir = tmppath / "openspec" / "archive"
            self.assertTrue(archive_dir.exists())
            archived_items = list(archive_dir.iterdir())
            self.assertEqual(len(archived_items), 1)
            self.assertIn("billing", archived_items[0].name)
            self.assertTrue((archived_items[0] / "proposal.md").exists())

            # Verify lifecycle state reset to design gate
            eval_data = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(eval_data["gate"], "design")
            self.assertEqual(eval_data["state_key"], "INITIAL_PROPOSAL")
            self.assertEqual(len(eval_data["openspec_archived"]), 1)
            self.assertEqual(len(eval_data["openspec_living_specs"]), 1)

    def test_cli_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "auth"
            specs_dir = pkg_dir / "specs"
            specs_dir.mkdir(parents=True)
            (specs_dir / "tokens.md").write_text("# Tokens\n")

            cmd = [sys.executable, str(INSPECT_LIFECYCLE), "--path", str(tmpdir), "--archive", "auth", "--force"]
            run = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0)
            self.assertIn("OPENSPEC APPLIED & ARCHIVED", run.stdout)
            self.assertTrue((tmppath / "openspec" / "specs" / "tokens.md").exists())

    def test_apply_preserves_existing_requirements_and_merges_deltas(self):
        """Reproduction for Issue 1: applying a delta must preserve existing requirements."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            living_specs_dir = tmppath / "openspec" / "specs"
            living_specs_dir.mkdir(parents=True)
            living_auth = living_specs_dir / "auth.md"
            living_auth.write_text(
                "# Authentication Specification\n\n"
                "## Overview\nLiving spec.\n\n"
                "### Requirement: Login\n"
                "The system SHALL authenticate user credentials.\n\n"
                "### Requirement: PasswordReset\n"
                "The system SHALL allow password reset via email.\n"
            )

            pkg_dir = tmppath / "openspec" / "changes" / "auth-v2"
            specs_dir = pkg_dir / "specs"
            specs_dir.mkdir(parents=True)
            (pkg_dir / "proposal.md").write_text("# Proposal\n")
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            # Delta adds Logout, updates Login, and removes PasswordReset
            (specs_dir / "auth.md").write_text(
                "# Auth Delta\n\n"
                "### Requirement: Logout\n"
                "The system SHALL invalidate user sessions.\n\n"
                "### Requirement: Login\n"
                "The system SHALL authenticate user credentials with Argon2 and MFA.\n\n"
                "### Requirement: PasswordReset [REMOVED]\n"
            )

            res = inspect_lifecycle.apply_and_archive_openspec(tmppath, "auth-v2", force=True)
            self.assertIn("auth.md", res["synced_specs"])

            merged_text = living_auth.read_text()
            # 1. Untouched requirement / updated requirement Login must exist with new body
            self.assertIn("Requirement: Login", merged_text)
            self.assertIn("Argon2 and MFA", merged_text)
            # 2. Added requirement Logout must exist
            self.assertIn("Requirement: Logout", merged_text)
            self.assertIn("invalidate user sessions", merged_text)
            # 3. Removed requirement PasswordReset must be gone
            self.assertNotIn("PasswordReset", merged_text)

    def test_delivery_rejects_failed_verdict_or_failing_test_evidence(self):
        """Reproduction for Issue 2: delivery readiness must reject failed verdicts and test failures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. All tasks completed\n")
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            report_file = scratch_dir / "review_report.json"

            # Case A: verdict: FAIL with status: complete, empty findings, exit_code: 1
            report_file.write_text(
                json.dumps({
                    "reviewer": "judge",
                    "status": "complete",
                    "verdict": "FAIL",
                    "findings": [],
                    "test_evidence": {"exit_code": 1},
                })
            )
            self._approve_design(tmppath)
            res_fail = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_fail["gate"], "review")
            self.assertEqual(res_fail["state_key"], "REVIEW_ACTIVE")
            self.assertIn("rejected", res_fail["next_action"])

            # Case B: verdict: PASS, but test evidence has exit_code: 1
            report_file.write_text(
                json.dumps({
                    "reviewer": "judge",
                    "status": "complete",
                    "verdict": "PASS",
                    "findings": [],
                    "test_evidence": {"exit_code": 1},
                })
            )
            res_bad_tests = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_bad_tests["gate"], "review")
            self.assertEqual(res_bad_tests["state_key"], "REVIEW_ACTIVE")
            self.assertIn("lacks verified test evidence", res_bad_tests["next_action"])

    def test_archive_blocked_when_tasks_pending_or_review_missing(self):
        """Reproduction for Issue 3: archiving must validate package completion before mutating."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "unfinished"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [ ] 1. Pending task\n")

            self._approve_design(tmppath)
            # 1. Unchecked tasks must block archiving
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, "unfinished")
            self.assertIn("pending tasks in tasks.md", str(ctx.exception))

            # 2. Completed tasks without passing review must block archiving
            (pkg_dir / "tasks.md").write_text("- [x] 1. Finished task\n")
            self._approve_design(tmppath)
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, "unfinished")
            self.assertIn("no passing review report found", str(ctx.exception))

    def test_resume_selects_active_change_and_ignores_completed_spikes(self):
        """Reproduction for Issue 4: prioritize in-progress packages and ignore completed spikes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            changes_dir = tmppath / "openspec" / "changes"

            # Setup older completed package 'a-old'
            old_pkg = changes_dir / "a-old"
            old_pkg.mkdir(parents=True)
            (old_pkg / "tasks.md").write_text("- [x] 1. Task complete\n")

            # Setup newer in-progress package 'z-current'
            curr_pkg = changes_dir / "z-current"
            curr_pkg.mkdir(parents=True)
            (curr_pkg / "tasks.md").write_text("- [ ] 1. Task in progress\n")

            # evaluate_repository must select 'z-current' in TDD_ACTIVE, NOT 'a-old' in REVIEW_ACTIVE
            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "implementation")
            self.assertEqual(res["state_key"], "TDD_ACTIVE")
            self.assertEqual(res["openspec_packages"][0]["change"], "z-current")

            # Explicit active change persistence in .agentflow/state.json
            inspect_lifecycle.set_active_change(tmppath, "a-old")
            res_explicit = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_explicit["openspec_packages"][0]["change"], "a-old")

            # Completed spike (.scratch/spike-redis/verdict.json) must not force SPIKE_ACTIVE
            spike_dir = tmppath / ".scratch" / "spike-redis"
            spike_dir.mkdir(parents=True)
            (spike_dir / "verdict.json").write_text(json.dumps({"verdict": "CONFIRMED", "status": "complete"}))

            res_spike = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertNotEqual(res_spike["state_key"], "SPIKE_ACTIVE")
            self.assertEqual(len(res_spike["active_spikes"]), 0)

    def test_unreviewed_source_changes_block_delivery(self):
        """Reproduction for Issue 1: unreviewed source modifications must revoke DELIVERY_READY."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Initialize git repository
            self._init_git_repo(tmppath)

            # Setup feature
            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            src_file = tmppath / "service.py"
            src_file.write_text("def run(): return 42\n")

            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmppath, check=True)
            head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmppath, capture_output=True, text=True).stdout.strip()

            # Create delivery envelope matching HEAD commit
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps({
                "change": "feature",
                "verdict": "PASS",
                "snapshot": {"commit": head_commit},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 5},
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
                    "coverage": ["Reviewed service.py."],
                    "questions": [],
                    "routing_notes": [],
                },
            }))

            # Initially clean: DELIVERY_READY
            self._approve_design(tmppath)
            res_clean = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_clean["gate"], "delivery")
            self.assertEqual(res_clean["state_key"], "DELIVERY_READY")

            # Now modify implementation to raise an exception
            src_file.write_text("def run(): raise RuntimeError('unreviewed crash')\n")

            # Must revoke DELIVERY_READY and demand re-review
            res_dirty = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_dirty["gate"], "review")
            self.assertEqual(res_dirty["state_key"], "REVIEW_ACTIVE")
            self.assertIn("unreviewed source modifications", res_dirty["next_action"])

    def test_delivery_evidence_envelope_clears_gate_while_judge_report_passes_schema(self):
        """Reproduction for Issue 2: separate envelope satisfies both validate_report and lifecycle checker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "payments"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Payments implemented\n")

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            # 1. Canonical Judge report adheres strictly to the 6 required fields
            canonical_judge_report = {
                "reviewer": "judge",
                "status": "complete",
                "findings": [],
                "coverage": ["Inspected payments gateway."],
                "questions": [],
                "routing_notes": [],
            }
            # Verify validate_report.py accepts this report
            validate_script = ROOT / "skills" / "review" / "scripts" / "validate_report.py"
            val_proc = subprocess.run(
                [sys.executable, str(validate_script), "-"],
                input=json.dumps(canonical_judge_report),
                text=True,
                capture_output=True,
            )
            self.assertEqual(val_proc.returncode, 0, f"Judge report rejected by validator: {val_proc.stderr}")

            # 2. Package into Delivery Evidence Envelope in .scratch/delivery_evidence.json
            envelope = {
                "schema_version": "1.0",
                "change": "payments",
                "verdict": "PASS",
                "snapshot": {"commit": "HEAD"},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 10},
                "judge_report": canonical_judge_report,
            }
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "delivery")
            self.assertEqual(res["state_key"], "DELIVERY_READY")
            self.assertTrue(res["review_report"]["is_envelope"])

    def test_strict_test_evidence_classification(self):
        """Reproduction for Issue 3: test evidence parsing must reject 'not passed' and 0 tests, and accept 0 failures."""
        # 1. "not passed" must be rejected
        self.assertFalse(inspect_lifecycle.is_test_evidence_passing("not passed"))

        # 2. {"tests_run": 0} must be rejected
        self.assertFalse(inspect_lifecycle.is_test_evidence_passing({"tests_run": 0}))
        self.assertFalse(inspect_lifecycle.is_test_evidence_passing({"exit_code": 0, "tests_run": 0}))

        # 3. "0 failures, 12 passed" must be accepted
        self.assertTrue(inspect_lifecycle.is_test_evidence_passing("0 failures, 12 passed"))
        self.assertTrue(inspect_lifecycle.is_test_evidence_passing("12 passed, 0 failures"))

        # 4. Structured dict with passing indicators
        self.assertTrue(inspect_lifecycle.is_test_evidence_passing({"exit_code": 0, "passed": True, "tests_run": 12}))
        self.assertFalse(inspect_lifecycle.is_test_evidence_passing({"exit_code": 1, "passed": False}))

    def test_corrupt_spike_report_remains_incomplete(self):
        """Reproduction for Issue 4: corrupt or template-only spike reports must not count as complete."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            spike_dir = tmppath / ".scratch" / "corrupt-spike"
            spike_dir.mkdir(parents=True)

            # Corrupt JSON containing only '{'
            (spike_dir / "report.json").write_text("{\n")
            self.assertFalse(inspect_lifecycle.is_spike_completed(spike_dir))

            # Markdown with only headings, no verdict
            (spike_dir / "report.json").unlink()
            (spike_dir / "report.md").write_text(
                "## 🧪 Spike Report: Corrupt\n\n### ⚖️ Architectural Verdict\n"
            )
            self.assertFalse(inspect_lifecycle.is_spike_completed(spike_dir))

            # Markdown with explicit confirmed verdict and details
            (spike_dir / "report.md").write_text(
                "## 🧪 Spike Report: Valid\n\n"
                "### ⚖️ Architectural Verdict\n"
                "- **Verdict**: **CONFIRMED**\n"
                "- **Recommendation**: Use memory-mapped I/O\n"
                "- Latency p99: 1.2ms\n"
            )
            self.assertTrue(inspect_lifecycle.is_spike_completed(spike_dir))

    def test_explicit_invalid_change_fails_visibly(self):
        """Reproduction for Issue 5: requesting an invalid change must error, not silently fall back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "auth"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Auth done\n")

            # Direct inspect_openspec call with invalid change
            with self.assertRaises(ValueError) as ctx:
                inspect_lifecycle.inspect_openspec(tmppath, target_change="auth-typo")
            self.assertIn("auth-typo", str(ctx.exception))
            self.assertIn("Available: auth", str(ctx.exception))

            # CLI call with --change auth-typo
            cmd = [sys.executable, str(INSPECT_LIFECYCLE), "--path", str(tmpdir), "--change", "auth-typo"]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("auth-typo", proc.stderr)

    def test_all_requirement_removal_notations(self):
        """Reproduction for Issue 6: all supported removal notations must reliably remove requirements."""
        living = (
            "# Spec\n\n"
            "### Requirement: KeepMe\n"
            "Keep this intact.\n\n"
            "### Requirement: BodyBracket\n"
            "Old body.\n\n"
            "### Requirement: BodyStatus\n"
            "Old body.\n\n"
            "### Requirement: HeaderBracket\n"
            "Old body.\n\n"
            "### Requirement: HeaderParen\n"
            "Old body.\n"
        )

        delta = (
            "# Delta\n\n"
            "### Requirement: BodyBracket\n"
            "[REMOVED]\n\n"
            "### Requirement: BodyStatus\n"
            "STATUS: REMOVED\n\n"
            "### Requirement: HeaderBracket [DELETED]\n\n"
            "### Requirement: HeaderParen (REMOVED)\n\n"
            "### Requirement: NewReq\n"
            "Brand new requirement.\n"
        )

        merged = inspect_lifecycle.merge_spec_requirements(living, delta)

        # Untouched requirement must remain
        self.assertIn("Requirement: KeepMe", merged)
        self.assertIn("Keep this intact.", merged)

        # New requirement must be added
        self.assertIn("Requirement: NewReq", merged)
        self.assertIn("Brand new requirement.", merged)

        # All 4 removed requirements must be purged
        self.assertNotIn("BodyBracket", merged)
        self.assertNotIn("BodyStatus", merged)
        self.assertNotIn("HeaderBracket", merged)
        self.assertNotIn("HeaderParen", merged)

    def test_envelope_change_mismatch_blocks_delivery_and_archive(self):
        """Reproduction for Issue 1: approval envelope for change 'auth' cannot authorise package 'billing'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "billing"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Billing implemented\n")

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            # Envelope approves change 'auth'
            envelope = {
                "schema_version": "1.0",
                "change": "auth",
                "verdict": "PASS",
                "snapshot": {"commit": "HEAD"},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 5},
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
                    "coverage": ["Inspected auth."],
                    "questions": [],
                    "routing_notes": [],
                },
            }
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))

            # Delivery check must reject because envelope change is 'auth', but active package is 'billing'
            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertIn("Review approval is for change 'auth'", res["next_action"])
            self.assertIn("billing", res["next_action"])

            # Archive must raise RuntimeError
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, change="billing")
            self.assertIn("review approval is for change 'auth'", str(ctx.exception).lower())

            # Matching change 'billing' clears gate
            envelope["change"] = "billing"
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))
            res_ok = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_ok["gate"], "delivery")
            self.assertEqual(res_ok["state_key"], "DELIVERY_READY")

    def test_reviewed_working_tree_fingerprint_clears_delivery_and_detects_subsequent_changes(self):
        """Reproduction for Issue 2: reviewed working tree modifications clear delivery via fingerprint; post-review edits are blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Feature done\n")

            # Working tree implementation file (uncommitted / dirty)
            service_file = tmppath / "service.py"
            service_file.write_text("def run(): return 42\n")

            # Compute fingerprint of this exact uncommitted working tree
            fingerprint = inspect_lifecycle.compute_working_tree_fingerprint(tmppath)
            self.assertTrue(fingerprint and len(fingerprint) == 64)

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            envelope = {
                "schema_version": "1.0",
                "change": "feature",
                "verdict": "PASS",
                "snapshot": {
                    "working_tree_fingerprint": fingerprint,
                },
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 8},
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
                    "coverage": ["Reviewed uncommitted working tree changes."],
                    "questions": [],
                    "routing_notes": [],
                },
            }
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))

            # The reviewed working tree changes must clear delivery!
            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "delivery")
            self.assertEqual(res["state_key"], "DELIVERY_READY")

            # Post-review modification: change service.py
            service_file.write_text("def run(): return 999\n")

            # Fingerprint mismatch must revoke DELIVERY_READY
            res_modified = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_modified["gate"], "review")
            self.assertEqual(res_modified["state_key"], "REVIEW_ACTIVE")
            self.assertIn("fingerprint mismatch", res_modified["next_action"])

            # Archive must also be blocked by fingerprint mismatch
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, change="feature")
            self.assertIn("fingerprint mismatch", str(ctx.exception))

    def test_ordinary_requirement_title_with_word_deleted_is_preserved_not_removed(self):
        """Reproduction for Issue 4: updating 'Restore deleted accounts' must preserve and update the requirement."""
        living = (
            "# Living Spec\n\n"
            "### Requirement: Restore deleted accounts\n"
            "Original logic for restoring deleted user accounts.\n\n"
            "### Requirement: OtherFeature\n"
            "Keep untouched.\n"
        )

        # Delta spec updating 'Restore deleted accounts'
        delta = (
            "# Delta Spec\n\n"
            "### Requirement: Restore deleted accounts\n"
            "Updated logic with 30-day grace period for restored accounts.\n"
        )

        merged = inspect_lifecycle.merge_spec_requirements(living, delta)

        # The requirement MUST NOT be deleted
        self.assertIn("Requirement: Restore deleted accounts", merged)
        self.assertIn("Updated logic with 30-day grace period for restored accounts.", merged)
        self.assertIn("Requirement: OtherFeature", merged)
        self.assertNotIn("Original logic for restoring deleted user accounts.", merged)

        # Now test an explicit deletion marker on that same requirement
        delta_delete = (
            "# Delta Spec\n\n"
            "### Requirement: Restore deleted accounts [DELETED]\n"
        )
        merged_deleted = inspect_lifecycle.merge_spec_requirements(living, delta_delete)
        self.assertNotIn("Restore deleted accounts", merged_deleted)
        self.assertIn("Requirement: OtherFeature", merged_deleted)

    def test_symbolic_head_snapshot_blocks_stale_approval_across_commits(self):
        """Reproduction for Issue 1: symbolic/non-hex snapshot commit (like 'HEAD') without fingerprint blocks delivery."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            src_file = tmppath / "service.py"
            src_file.write_text("def run(): return 42\n")

            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmppath, check=True)

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            # Envelope saved with symbolic HEAD commit and NO working_tree_fingerprint
            envelope = {
                "schema_version": "1.0",
                "change": "feature",
                "verdict": "PASS",
                "snapshot": {"commit": "HEAD"},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 5},
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
                    "coverage": ["Reviewed service.py."],
                    "questions": [],
                    "routing_notes": [],
                },
            }
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))

            # Symbolic HEAD without fingerprint MUST NOT produce DELIVERY_READY
            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertIn("symbolic or unresolved", res["next_action"])

            # Archive must also reject symbolic commit
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, change="feature")
            self.assertIn("symbolic or unresolved", str(ctx.exception))

            # Resolving to immutable commit SHA clears delivery
            head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmppath, capture_output=True, text=True).stdout.strip()
            envelope["snapshot"]["commit"] = head_commit
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))
            res_resolved = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_resolved["gate"], "delivery")
            self.assertEqual(res_resolved["state_key"], "DELIVERY_READY")

            # Subsequent commit (regression) invalidates the immutable SHA approval
            src_file.write_text("def run(): raise RuntimeError('broken')\n")
            subprocess.run(["git", "add", "service.py"], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Regression"], cwd=tmppath, check=True)

            res_regression = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_regression["gate"], "review")
            self.assertEqual(res_regression["state_key"], "REVIEW_ACTIVE")
            self.assertIn("does not match current commit", res_regression["next_action"])

    def test_malformed_nested_judge_report_blocks_delivery(self):
        """Reproduction for Issue 2: delivery gate strictly validates nested Judge report contract."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmppath, check=True)
            head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmppath, capture_output=True, text=True).stdout.strip()

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            # Malformed envelope: only {"reviewer": "judge"}, missing required 5 fields
            malformed_envelope = {
                "schema_version": "1.0",
                "change": "feature",
                "verdict": "PASS",
                "snapshot": {"commit": head_commit},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 5},
                "judge_report": {"reviewer": "judge"},
            }
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(malformed_envelope))

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertIn("Judge report in delivery envelope is malformed", res["next_action"])

            # Archive must also reject malformed judge report
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, change="feature")
            self.assertIn("Judge report in delivery envelope is malformed", str(ctx.exception))

            # Canonical 6-field report passes validation
            malformed_envelope["judge_report"] = {
                "reviewer": "judge",
                "status": "complete",
                "findings": [],
                "coverage": ["Reviewed feature."],
                "questions": [],
                "routing_notes": [],
            }
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(malformed_envelope))
            res_valid = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_valid["gate"], "delivery")
            self.assertEqual(res_valid["state_key"], "DELIVERY_READY")

    def test_archive_failure_rolls_back_specs_and_allows_resumable_recovery(self):
        """Reproduction for Issue 3: archive failure rolls back spec changes, and retry recovers without blocking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            # Living spec: openspec/specs/auth.md
            living_dir = tmppath / "openspec" / "specs"
            living_dir.mkdir(parents=True)
            living_spec = living_dir / "auth.md"
            living_content = "# Auth\n\n### Requirement: Login\nUser logs in.\n"
            living_spec.write_text(living_content)

            # Change package: openspec/changes/auth/specs/auth.md
            pkg_dir = tmppath / "openspec" / "changes" / "auth"
            delta_dir = pkg_dir / "specs"
            delta_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Auth done\n")
            (delta_dir / "auth.md").write_text("# Auth\n\n### Requirement: Logout\nUser logs out.\n")

            # Commit living spec and change package
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmppath, check=True)
            head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmppath, capture_output=True, text=True).stdout.strip()

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            envelope = {
                "schema_version": "1.0",
                "change": "auth",
                "verdict": "PASS",
                "snapshot": {"commit": head_commit},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 5},
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
                    "coverage": ["All auth tests pass."],
                    "questions": [],
                    "routing_notes": [],
                },
            }
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))

            self._approve_design(tmppath)
            # Simulate failure during directory move
            import unittest.mock as mock
            with mock.patch("shutil.move", side_effect=OSError("Simulated move failure")):
                with self.assertRaises(RuntimeError) as ctx:
                    inspect_lifecycle.apply_and_archive_openspec(tmppath, change="auth")
                self.assertIn("Simulated move failure", str(ctx.exception))

            # Spec modification must be rolled back!
            self.assertEqual(living_spec.read_text(), living_content)
            self.assertTrue(pkg_dir.exists())

            # Now retry with normal shutil.move - archive must succeed cleanly
            inspect_lifecycle.apply_and_archive_openspec(tmppath, change="auth")
            # Living spec should now contain both Login and Logout
            merged_text = living_spec.read_text()
            self.assertIn("Requirement: Login", merged_text)
            self.assertIn("Requirement: Logout", merged_text)
            self.assertFalse(pkg_dir.exists())

    def test_active_change_persistence_does_not_revoke_delivery_or_block_archive(self):
        """Active change written to .agentflow/state.json must not count as an unreviewed source modification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            pkg = tmppath / "openspec" / "changes" / "feat"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] 1. Done\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmppath, check=True)
            commit_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmppath, capture_output=True, text=True).stdout.strip()

            (tmppath / ".agentflow").mkdir()
            (tmppath / ".agentflow" / "delivery_evidence.json").write_text(json.dumps({
                "change": "feat",
                "verdict": "PASS",
                "snapshot": {"commit": commit_sha},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 1},
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
                    "coverage": ["Reviewed feat."],
                    "questions": [],
                    "routing_notes": [],
                },
            }))

            # Set active change via .agentflow/state.json
            self._approve_design(tmppath)
            inspect_lifecycle.set_active_change(tmppath, "feat")
            self.assertEqual(inspect_lifecycle.get_active_change(tmppath), "feat")

            # Must remain DELIVERY_READY
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "delivery")
            self.assertEqual(res["state_key"], "DELIVERY_READY")

            # Must archive cleanly, clearing active change in .agentflow/state.json
            arch_res = inspect_lifecycle.apply_and_archive_openspec(tmppath, change="feat")
            self.assertEqual(arch_res["change"], "feat")
            self.assertIsNone(inspect_lifecycle.get_active_change(tmppath))

    def test_judge_report_unhashable_status_and_nan_confidence(self):
        """validate_judge_report_contract handles unhashable status and invalid confidence/paths without crashing."""
        base_report = {
            "reviewer": "judge",
            "status": "complete",
            "findings": [{
                "id": "FINDING-001",
                "severity": "CRITICAL",
                "category": "Correctness",
                "file": "service.py",
                "line": "L10-L20",
                "title": "Bug",
                "problem": "Crash",
                "evidence": "val = 1 / 0",
                "impact": "Fails",
                "recommendation": "Fix",
                "confidence": 0.95,
                "fixability": "autonomous",
            }],
            "coverage": [],
            "questions": [],
            "routing_notes": [],
        }

        # 1. Unhashable status list should produce error, not crash with TypeError
        rep_unhashable = dict(base_report, status=["complete"])
        errs = inspect_lifecycle.validate_judge_report_contract(rep_unhashable)
        self.assertTrue(any("status" in e for e in errs))

        # 2. NaN confidence should produce error
        rep_nan = json.loads(json.dumps(base_report))
        rep_nan["findings"][0]["confidence"] = float("nan")
        errs_nan = inspect_lifecycle.validate_judge_report_contract(rep_nan)
        self.assertTrue(any("confidence" in e for e in errs_nan))

        # 3. Non-relative path
        rep_path = json.loads(json.dumps(base_report))
        rep_path["findings"][0]["file"] = "/etc/passwd"
        errs_path = inspect_lifecycle.validate_judge_report_contract(rep_path)
        self.assertTrue(any("repository-relative" in e for e in errs_path))

        # 4. Inverted line range
        rep_line = json.loads(json.dumps(base_report))
        rep_line["findings"][0]["line"] = "L20-L10"
        errs_line = inspect_lifecycle.validate_judge_report_contract(rep_line)
        self.assertTrue(any("line range ends before it starts" in e for e in errs_line))

    def test_task_parsing_supports_uppercase_asterisk_checkbox(self):
        """* [X] must be counted as a completed task."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "asterisk-task"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text(
                "# Tasks\n"
                "* [X] 1. First task\n"
                "- [x] 2. Second task\n"
                "- [ ] 3. Third task\n"
            )
            pkgs = inspect_lifecycle.inspect_openspec(tmppath)
            self.assertEqual(len(pkgs), 1)
            self.assertEqual(pkgs[0]["total_tasks"], 3)
            self.assertEqual(pkgs[0]["completed_tasks"], 2)
            self.assertEqual(pkgs[0]["pending_tasks"], 1)

    def test_enhanced_test_evidence_phrases(self):
        """is_test_evidence_passing accepts common test summary phrases and status words."""
        self.assertTrue(inspect_lifecycle.is_test_evidence_passing("All 10 tests passed successfully!"))
        self.assertTrue(inspect_lifecycle.is_test_evidence_passing("All tests passed"))
        self.assertTrue(inspect_lifecycle.is_test_evidence_passing("10 tests passed"))
        self.assertTrue(inspect_lifecycle.is_test_evidence_passing("PASS"))
        self.assertTrue(inspect_lifecycle.is_test_evidence_passing("SUCCESS"))
        self.assertFalse(inspect_lifecycle.is_test_evidence_passing("FAILED"))
        self.assertFalse(inspect_lifecycle.is_test_evidence_passing("not passed"))

    def test_non_spike_scratch_directories_ignored(self):
        """Directories like coverage, logs, or known package folders in .scratch are not flagged as spikes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "billing"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [ ] 1. Task\n")

            # Create non-spike dirs in .scratch
            scratch_dir = tmppath / ".scratch"
            (scratch_dir / "coverage").mkdir(parents=True)
            (scratch_dir / "logs").mkdir(parents=True)
            (scratch_dir / "billing").mkdir(parents=True)

            spikes = inspect_lifecycle.inspect_spikes(tmppath)
            self.assertEqual(len(spikes), 0)

    def test_fingerprint_detects_unstaged_changes_before_first_commit(self):
        """In a repo before first commit, modifying a staged file without staging must change fingerprint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Complete\n")
            (tmppath / "service.py").write_text("v1_clean = True\n")
            subprocess.run(["git", "add", "openspec", "service.py"], cwd=tmppath, check=True)

            fp_staged = inspect_lifecycle.compute_working_tree_fingerprint(tmppath)

            # Introduce unstaged modification
            (tmppath / "service.py").write_text("v1_clean = False # regression\n")

            fp_unstaged = inspect_lifecycle.compute_working_tree_fingerprint(tmppath)
            self.assertNotEqual(fp_staged, fp_unstaged)

    def test_legacy_flat_report_without_change_or_contract_blocks_delivery(self):
        """A flat report lacking change or standard contract fields (status, findings, coverage) must block delivery."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            # Flat legacy report missing change and required contract fields
            (scratch_dir / "review_report.json").write_text(json.dumps({
                "reviewer": "judge",
                "verdict": "PASS",
                "commit": "abc1234",
                "test_evidence": True,
            }))

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertTrue(
                "Review approval lacks 'change'" in res["next_action"]
                or "Judge report is malformed" in res["next_action"]
            )

    def test_malformed_change_evidence_blocks_delivery_without_fallback(self):
        """Malformed change evidence (judge_report: null) must block delivery and not fall back to global approval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            # Global passing report (older approval)
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps({
                "change": "feature",
                "verdict": "PASS",
                "test_evidence": True,
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
                    "coverage": ["All files clean."],
                    "questions": [],
                    "routing_notes": [],
                },
            }))

            # Change-specific envelope with judge_report: null
            change_scratch = scratch_dir / "feature"
            change_scratch.mkdir()
            (change_scratch / "delivery_evidence.json").write_text(json.dumps({
                "change": "feature",
                "verdict": "PASS",
                "judge_report": None,
                "test_evidence": True,
            }))

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertIn("Judge report in delivery envelope is malformed", res["next_action"])
            self.assertIn("Envelope is missing required 'judge_report' object", res["next_action"])

    def test_normalize_req_title_handles_bracketed_and_prefixed_ids(self):
        """normalize_req_title strips bracketed requirement tags and colon prefixes."""
        self.assertEqual(inspect_lifecycle.normalize_req_title("[REQ-001] User Authentication"), "user authentication")
        self.assertEqual(inspect_lifecycle.normalize_req_title("REQ-002: User Authentication"), "user authentication")
        self.assertEqual(inspect_lifecycle.normalize_req_title("**[REQ-003] User Authentication**"), "user authentication")

    def test_pre_commit_repo_requires_working_tree_fingerprint(self):
        """In a repo before first commit, a review report must provide matching snapshot fingerprint and not a fake commit SHA."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            # 1. Report without snapshot_fingerprint
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps({
                "change": "feature",
                "verdict": "PASS",
                "test_evidence": True,
                "snapshot_sha": "deadbeef1234567",
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
                    "coverage": ["Clean"],
                    "questions": [],
                    "routing_notes": [],
                },
            }))

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertTrue(
                "lacks working-tree fingerprint" in res["next_action"]
                or "does not exist (repository has no commits yet)" in res["next_action"]
            )

            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, "feature")
            self.assertTrue(
                "lacks working-tree fingerprint" in str(ctx.exception)
                or "does not exist (repository has no commits yet)" in str(ctx.exception)
            )

            # 2. Report with valid snapshot_fingerprint clears delivery
            current_fp = inspect_lifecycle.compute_working_tree_fingerprint(tmppath)
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps({
                "change": "feature",
                "verdict": "PASS",
                "test_evidence": True,
                "working_tree_fingerprint": current_fp,
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
                    "coverage": ["Clean"],
                    "questions": [],
                    "routing_notes": [],
                },
            }))

            res2 = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res2["gate"], "delivery")
            self.assertEqual(res2["state_key"], "DELIVERY_READY")

    def test_archiving_package_does_not_create_phantom_active_spike(self):
        """Retained delivery evidence in .scratch/<change> must not be flagged as an active spike after archiving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)
            pkg_dir = tmppath / "openspec" / "changes" / "auth"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Auth implementation\n")

            scratch_dir = tmppath / ".scratch" / "auth"
            scratch_dir.mkdir(parents=True)
            current_fp = inspect_lifecycle.compute_working_tree_fingerprint(tmppath)
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps({
                "change": "auth",
                "verdict": "PASS",
                "test_evidence": True,
                "working_tree_fingerprint": current_fp,
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
                    "coverage": ["Reviewed auth."],
                    "questions": [],
                    "routing_notes": [],
                },
            }))

            # Starts at DELIVERY_READY
            self._approve_design(tmppath)
            res_ready = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_ready["gate"], "delivery")
            self.assertEqual(res_ready["state_key"], "DELIVERY_READY")

            # Successfully archive auth
            inspect_lifecycle.apply_and_archive_openspec(tmppath, change="auth")

            # Next evaluation must NOT treat .scratch/auth as an active spike
            res_after = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertNotEqual(res_after["state_key"], "SPIKE_ACTIVE")
            self.assertEqual(len(res_after["active_spikes"]), 0)
            self.assertEqual(res_after["gate"], "design")

    def test_skipped_judge_review_blocks_delivery_and_archive(self):
        """A report with status: skipped must block delivery and archiving even if verdict is PASS."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            src_file = tmppath / "service.py"
            src_file.write_text("def run(): return 42\n")

            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmppath, check=True)
            head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmppath, capture_output=True, text=True).stdout.strip()

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            envelope = {
                "schema_version": "1.0",
                "change": "feature",
                "verdict": "PASS",
                "snapshot": {"commit": head_commit},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 5},
                "judge_report": {
                    "reviewer": "judge",
                    "status": "skipped",
                    "findings": [],
                    "coverage": [],
                    "questions": [],
                    "routing_notes": [],
                },
            }
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))

            # Delivery evaluation must reject skipped status
            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "review")
            self.assertEqual(res["state_key"], "REVIEW_ACTIVE")
            self.assertIn("not complete", res["next_action"])

            # Archive must also reject skipped status
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, change="feature")
            self.assertIn("requires 'complete'", str(ctx.exception))

    def test_ship_json_config_loading(self):
        """Verify .agentflow.json config loading and overriding in inspect_lifecycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            config_data = {
                "project": {"name": "billing", "scope": "services/billing"},
                "gates": {
                    "implementation": {"test": "pnpm test"},
                    "simplify": {"max_debt": 2},
                    "review": {"max_iterations": 5},
                },
            }
            (tmppath / ".agentflow.json").write_text(json.dumps(config_data))

            cfg = inspect_lifecycle.load_ship_config(tmppath)
            self.assertEqual(cfg["config_source"], ".agentflow.json")
            self.assertEqual(cfg["project"]["name"], "billing")
            self.assertEqual(cfg["project"]["scope"], "services/billing")
            self.assertEqual(cfg["gates"]["implementation"]["test"], "pnpm test")
            self.assertEqual(cfg["gates"]["simplify"]["max_debt"], 2)
            self.assertEqual(cfg["gates"]["review"]["max_iterations"], 5)

            # Check format_summary displays config
            eval_data = inspect_lifecycle.evaluate_repository(tmppath)
            summary = inspect_lifecycle.format_summary(eval_data)
            self.assertIn(".agentflow.json", summary)
            self.assertIn("pnpm test", summary)

    def test_ship_json_config_loading_custom_path(self):
        """Verify .agentflow.json parsing from explicit custom path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            json_content = json.dumps({
                "project": {"name": "auth-service"},
                "gates": {
                    "implementation": {"test": "pytest -q"},
                    "review": {"max_iterations": 4},
                },
            })
            custom_file = tmppath / "custom.agentflow.json"
            custom_file.write_text(json_content)

            cfg = inspect_lifecycle.load_ship_config(tmppath, explicit_path=str(custom_file))
            self.assertEqual(cfg["config_source"], "custom.agentflow.json")
            self.assertEqual(cfg["project"]["name"], "auth-service")
            self.assertEqual(cfg["gates"]["implementation"]["test"], "pytest -q")
            self.assertEqual(cfg["gates"]["review"]["max_iterations"], 4)

    def test_create_checkpoint_and_rollback(self):
        """Verify checkpoint creation and safe rollback with backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            # Setup openspec package
            pkg_dir = tmppath / "openspec" / "changes" / "payment"
            pkg_dir.mkdir(parents=True)
            tasks_file = pkg_dir / "tasks.md"
            tasks_file.write_text("- [x] Task 1: Setup stripe\n- [ ] Task 2: Webhooks\n")

            service_file = tmppath / "service.py"
            service_file.write_text("def pay(): pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial spec commit"], cwd=tmppath, check=True)

            # Create checkpoint for design
            chk = inspect_lifecycle.create_checkpoint(tmppath, "design", change="payment")
            self.assertEqual(chk["gate"], "design")
            self.assertEqual(chk["change"], "payment")
            self.assertTrue(chk["ref_created"])
            chk_file = tmppath / ".agentflow" / "checkpoints" / "payment_design.json"
            self.assertTrue(chk_file.exists())

            # Now simulate partial dirty edits in implementation
            service_file.write_text("def pay(): return 'broken'\n")
            tasks_file.write_text("- [x] Task 1: Setup stripe\n- [x] Task 2: Webhooks\n")

            # Perform rollback to design
            rb = inspect_lifecycle.perform_rollback(tmppath, "design", change="payment", force=True)
            self.assertEqual(rb["status"], "success")
            self.assertEqual(rb["target_gate"], "design")
            self.assertEqual(rb["reset_tasks_count"], 2)

            # Verify tasks.md tasks were reset to unchecked
            reset_tasks = tasks_file.read_text()
            self.assertIn("- [ ] Task 1: Setup stripe", reset_tasks)
            self.assertIn("- [ ] Task 2: Webhooks", reset_tasks)

            # Verify dirty implementation file was restored to checkpoint version
            self.assertEqual(service_file.read_text(), "def pay(): pass\n")
            self.assertIn("service.py", rb["restored_files"])

            # Verify backup directory was created for dirty changes
            self.assertIsNotNone(rb["backup_directory"])
            backup_path = tmppath / rb["backup_directory"]
            self.assertTrue(backup_path.exists())
            self.assertTrue((backup_path / "service.py").exists())

    def test_rollback_restores_committed_broken_implementation(self):
        """Verify rollback restores committed modifications and deletes newly created files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            # Setup checkpoint at design
            pkg_dir = tmppath / "openspec" / "changes" / "payment"
            pkg_dir.mkdir(parents=True)
            tasks_file = pkg_dir / "tasks.md"
            tasks_file.write_text("- [x] Task 1: Setup stripe\n")
            service_file = tmppath / "service.py"
            service_file.write_text("def pay(): pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial checkpoint commit"], cwd=tmppath, check=True)

            inspect_lifecycle.create_checkpoint(tmppath, "design", change="payment")

            # Commit a broken implementation and an additional file in implementation
            service_file.write_text("def pay(): raise RuntimeError('broken')\n")
            extra_file = tmppath / "extra.py"
            extra_file.write_text("def extra(): pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Broken implementation"], cwd=tmppath, check=True)

            # Perform rollback to design
            rb = inspect_lifecycle.perform_rollback(tmppath, "design", change="payment", force=True)
            self.assertEqual(rb["status"], "success")
            self.assertIn("service.py", rb["restored_files"])
            self.assertIn("extra.py", rb["removed_files"])

            # Working tree verification
            self.assertEqual(service_file.read_text(), "def pay(): pass\n")
            self.assertFalse(extra_file.exists())

            # Verify backups contain the committed broken state
            backup_path = tmppath / rb["backup_directory"]
            self.assertTrue(backup_path.exists())
            self.assertTrue((backup_path / "committed_diff.patch").exists())
            self.assertTrue((backup_path / "service.py").exists())
            self.assertTrue((backup_path / "extra.py").exists())
            self.assertIn("raise RuntimeError", (backup_path / "service.py").read_text())

    def test_ship_json_deep_merge_and_defaults(self):
        """Verify JSON config loading deep-merges overrides while preserving default gate configs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            json_content = json.dumps({
                "project": {"name": "billing"},
                "gates": {
                    "review": {
                        "max_iterations": 3,
                        "critical_paths": ["services/billing/core", "services/billing/api"],
                    },
                    "implementation": {
                        "test": "pytest -q",
                    },
                },
            })
            (tmppath / ".agentflow.json").write_text(json_content)
            parsed = inspect_lifecycle.load_ship_config(tmppath)
            self.assertEqual(parsed["project"]["name"], "billing")
            self.assertEqual(parsed["gates"]["implementation"]["test"], "pytest -q")
            self.assertEqual(parsed["gates"]["review"]["max_iterations"], 3)
            self.assertEqual(
                parsed["gates"]["review"]["critical_paths"],
                ["services/billing/core", "services/billing/api"],
            )

    def test_checkpoint_in_precommit_repo(self):
        """Verify checkpoint gracefully handles repository before first commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)
            chk = inspect_lifecycle.create_checkpoint(tmppath, "design", change="new-feature")
            self.assertEqual(chk["gate"], "design")
            self.assertEqual(chk["commit"], "none")
            self.assertFalse(chk["ref_created"])
            self.assertTrue((tmppath / ".agentflow" / "checkpoints" / "new-feature_design.json").exists())

    def test_status_check_exit_codes(self):
        """Verify --status-check exit code returns: 0 for ready, 1 for in-progress, 2 for review rejection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Empty repo -> design -> status_check exit code 1 (in-progress)
            code = inspect_lifecycle.main(["--path", str(tmppath), "--status-check"])
            self.assertEqual(code, 1)

            # Add failing review report -> status_check exit code 2 (remediation/rollback)
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            report_data = {
                "reviewer": "judge",
                "status": "fail",
                "verdict": "FAIL",
                "critical_or_high_count": 1,
            }
            (scratch_dir / "review_report.json").write_text(json.dumps(report_data))
            code = inspect_lifecycle.main(["--path", str(tmppath), "--status-check"])
            self.assertEqual(code, 2)

    def test_rollback_preserves_precheckpoint_uncommitted_edits(self):
        """Verify rollback restores checkpoint state without reverting uncommitted edits made prior to checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            # 1. Initial committed state
            service_file = tmppath / "service.py"
            service_file.write_text("def pay(): pass\n")
            unrelated_file = tmppath / "unrelated.txt"
            unrelated_file.write_text("unrelated initial commit\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmppath, check=True)

            # 2. User edits unrelated file BEFORE creating checkpoint (uncommitted edit)
            unrelated_file.write_text("unrelated pre-checkpoint edit\n")

            # 3. Checkpoint created
            chk = inspect_lifecycle.create_checkpoint(tmppath, "design", change="payment")
            self.assertTrue(chk["ref_created"])
            self.assertIn("snapshot_commit", chk)

            # 4. User changes implementation in implementation gate and modifies unrelated file again
            service_file.write_text("def pay(): raise RuntimeError('broken')\n")
            unrelated_file.write_text("unrelated post-checkpoint modification\n")
            new_impl_file = tmppath / "impl_temp.py"
            new_impl_file.write_text("temp = 1\n")

            # 5. Perform rollback to design
            rb = inspect_lifecycle.perform_rollback(tmppath, "design", change="payment", force=True)
            self.assertEqual(rb["status"], "success")

            # 6. Verify unrelated file reverted to CHECKPOINT content (not initial commit content!)
            self.assertEqual(unrelated_file.read_text(), "unrelated pre-checkpoint edit\n")
            # Verify service.py reverted to its checkpoint state
            self.assertEqual(service_file.read_text(), "def pay(): pass\n")
            # Verify new file created after checkpoint was removed
            self.assertFalse(new_impl_file.exists())

    def test_rollback_preserves_tracked_files_matching_gitignore(self):
        """Verify rollback does not delete tracked files that happen to match .gitignore rules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            # 1. Commit tracked.cfg and .gitignore matching *.cfg
            (tmppath / ".gitignore").write_text("*.cfg\n")
            tracked_cfg = tmppath / "tracked.cfg"
            tracked_cfg.write_text("important = true\n")
            service_file = tmppath / "service.py"
            service_file.write_text("def pay(): pass\n")
            subprocess.run(["git", "add", ".gitignore"], cwd=tmppath, check=True)
            subprocess.run(["git", "add", "-f", "tracked.cfg"], cwd=tmppath, check=True)
            subprocess.run(["git", "add", "service.py"], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit with tracked.cfg"], cwd=tmppath, check=True)

            # 2. Create checkpoint
            chk = inspect_lifecycle.create_checkpoint(tmppath, "design", change="payment")
            self.assertTrue(chk["ref_created"])

            # 3. User modifies service.py in implementation gate
            service_file.write_text("def pay(): raise RuntimeError('broken')\n")

            # 4. Perform rollback
            rb = inspect_lifecycle.perform_rollback(tmppath, "design", change="payment", force=True)
            self.assertEqual(rb["status"], "success")

            # 5. Verify tracked.cfg is NOT deleted!
            self.assertTrue(tracked_cfg.exists(), "tracked.cfg was mistakenly deleted by rollback!")
            self.assertEqual(tracked_cfg.read_text(), "important = true\n")
            self.assertNotIn("tracked.cfg", rb["removed_files"])
            self.assertEqual(service_file.read_text(), "def pay(): pass\n")

    def test_checkpoint_and_rollback_directories_not_flagged_as_active_spikes(self):
        """Checkpoints and rollback backup directories must not be treated as active empirical spikes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [ ] 1. Do something\n")

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            # Create a checkpoint file under .scratch/checkpoints
            chk_dir = scratch_dir / "checkpoints"
            chk_dir.mkdir()
            (chk_dir / "feature_design.json").write_text(json.dumps({"change": "feature", "gate": "design"}))

            # Create a rollback backup directory
            rollback_dir = scratch_dir / "rollback_20260912_120000"
            rollback_dir.mkdir()
            (rollback_dir / "dummy.py").write_text("dummy = 1\n")

            # Create a review evidence dir with review_report.json
            evidence_dir = scratch_dir / "old-evidence"
            evidence_dir.mkdir()
            (evidence_dir / "review_report.json").write_text(json.dumps({"status": "complete"}))

            spikes = inspect_lifecycle.inspect_spikes(tmppath)
            self.assertEqual(spikes, [])

            self._approve_design(tmppath)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertNotEqual(res["state_key"], "SPIKE_ACTIVE")
            self.assertEqual(res["gate"], "implementation")

    def test_review_report_json_recognized_as_evidence_dir(self):
        """Directory with report.json containing reviewer or judge_report must not be treated as a spike."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            review_dir = scratch_dir / "adjudication"
            review_dir.mkdir()
            (review_dir / "report.json").write_text(json.dumps({
                "reviewer": "judge",
                "status": "complete",
                "findings": [],
                "coverage": [],
                "questions": [],
                "routing_notes": []
            }))

            self.assertTrue(inspect_lifecycle.is_evidence_dir(review_dir))
            spikes = inspect_lifecycle.inspect_spikes(tmppath)
            self.assertEqual(spikes, [])

    def test_change_suffixed_review_reports_discovered(self):
        """inspect_review_reports must discover .scratch/review_report_<change>.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            rev_file = scratch_dir / "review_report_billing.json"
            rev_file.write_text(json.dumps({
                "reviewer": "judge",
                "status": "complete",
                "verdict": "PASS",
                "change": "billing",
                "findings": [],
                "coverage": ["billing.py"],
                "questions": [],
                "routing_notes": [],
                "test_evidence": True,
            }))

            rep = inspect_lifecycle.inspect_review_reports(tmppath, change="billing")
            self.assertIsNotNone(rep)
            self.assertEqual(rep["change"], "billing")
            self.assertTrue(rep["test_evidence_passed"])

    def test_porcelain_quoted_filenames_stripped(self):
        """Filenames enclosed in double quotes by git status porcelain must have quotes stripped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            spaced_file = tmppath / "spaced file.py"
            spaced_file.write_text("x = 1\n")
            subprocess.run(["git", "add", "spaced file.py"], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmppath, check=True, capture_output=True)

            spaced_file.write_text("x = 2\n")
            git_info = inspect_lifecycle.get_git_info(tmppath)
            self.assertIn("spaced file.py", git_info["modified_source_files"])
            self.assertNotIn('"spaced file.py"', git_info["modified_source_files"])

    def test_rollback_handles_renamed_files(self):
        """Rollback must restore original file and remove destination when a file was renamed after checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Initial task\n")

            orig_file = tmppath / "original.py"
            orig_file.write_text("def orig(): pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmppath, check=True, capture_output=True)

            # Create checkpoint for Implementation
            chk = inspect_lifecycle.create_checkpoint(tmppath, gate_name="implementation", change="feature")
            self.assertEqual(chk["gate"], "implementation")

            # Rename file using git mv
            subprocess.run(["git", "mv", "original.py", "renamed.py"], cwd=tmppath, check=True)
            self.assertFalse((tmppath / "original.py").exists())
            self.assertTrue((tmppath / "renamed.py").exists())

            # Perform rollback
            rb = inspect_lifecycle.perform_rollback(tmppath, target_gate="implementation", change="feature", force=True)
            self.assertEqual(rb["status"], "success")
            self.assertIn("original.py", rb["restored_files"])
            self.assertIn("renamed.py", rb["removed_files"])
            self.assertTrue((tmppath / "original.py").exists())
            self.assertFalse((tmppath / "renamed.py").exists())
            self.assertEqual((tmppath / "original.py").read_text(), "def orig(): pass\n")

            # Check that backed up files recorded renamed.py
            self.assertIn("renamed.py", rb["backed_up_files"])

            # Working tree has no modified source files
            git_info = inspect_lifecycle.get_git_info(tmppath)
            self.assertEqual(git_info["modified_source_files"], [])

    def test_checkpoint_records_git_ref_and_skips_tag_by_default(self):
        """Checkpoints record refs/ship/... by default and omit refs/tags/ unless create_git_tag=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            (tmppath / "README.md").write_text("# Test\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Init"], cwd=tmppath, check=True, capture_output=True)

            # 1. Default: records to refs/ship/... but NOT to refs/tags/
            chk = inspect_lifecycle.create_checkpoint(tmppath, "design", change="auth")
            self.assertTrue(chk["ref_created"])
            self.assertFalse(chk["tag_created"])
            self.assertIsNone(chk["tag"])

            ref_check = subprocess.run(
                ["git", "rev-parse", "--verify", "refs/ship/auth/design"],
                cwd=tmppath, capture_output=True, text=True
            )
            self.assertEqual(ref_check.returncode, 0)

            tag_check = subprocess.run(
                ["git", "rev-parse", "--verify", "refs/tags/ship/auth/design"],
                cwd=tmppath, capture_output=True, text=True
            )
            self.assertNotEqual(tag_check.returncode, 0)

            # 2. With create_git_tag=True: explicitly permits git tag in refs/tags/
            chk_tagged = inspect_lifecycle.create_checkpoint(tmppath, "design", change="auth", create_git_tag=True)
            self.assertTrue(chk_tagged["tag_created"])
            self.assertIsNotNone(chk_tagged["tag"])

            tag_check2 = subprocess.run(
                ["git", "rev-parse", "--verify", "refs/tags/ship/auth/design"],
                cwd=tmppath, capture_output=True, text=True
            )
            self.assertEqual(tag_check2.returncode, 0)

    def test_rollback_preserves_untracked_directories_and_files(self):
        """Rollback must safely archive newly created untracked directories and files into untracked_removed/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)

            (tmppath / "main.py").write_text("def main(): pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Base"], cwd=tmppath, check=True, capture_output=True)

            # Checkpoint
            inspect_lifecycle.create_checkpoint(tmppath, "design", change="data-safety")

            # Create new untracked file and new untracked directory
            (tmppath / "new_file.py").write_text("# precious untracked content\n")
            new_dir = tmppath / "new_package"
            new_dir.mkdir()
            (new_dir / "module.py").write_text("def helper(): return 42\n")

            # Perform rollback
            rb = inspect_lifecycle.perform_rollback(tmppath, "design", change="data-safety", force=True)
            self.assertEqual(rb["status"], "success")

            # Verify working tree no longer has new files
            self.assertFalse((tmppath / "new_file.py").exists())
            self.assertFalse((tmppath / "new_package").exists())

            # Verify safety stash preserved the byte-for-byte content
            backup_dir = tmppath / rb["backup_directory"]
            safety_file = backup_dir / "untracked_removed" / "new_file.py"
            safety_dir_file = backup_dir / "untracked_removed" / "new_package" / "module.py"
            self.assertTrue(safety_file.exists())
            self.assertTrue(safety_dir_file.exists())
            self.assertEqual(safety_file.read_text(), "# precious untracked content\n")
            self.assertEqual(safety_dir_file.read_text(), "def helper(): return 42\n")

    def test_ship_schema_conformance(self):
        """Verify load_ship_config default_config aligns with agentflow.schema.json structure."""
        schema_file = Path(__file__).resolve().parent.parent / "skills" / "ship" / "references" / "agentflow.schema.json"
        self.assertTrue(schema_file.exists())
        self.assertIn("properties", json.loads(schema_file.read_text(encoding="utf-8")))

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = inspect_lifecycle.load_ship_config(Path(tmpdir))

            # Validate top-level keys
            expected_gates = {"design", "spike", "implementation", "simplify", "review", "delivery"}
            self.assertEqual(set(cfg["gates"].keys()), expected_gates)

            # Check implementation gate commands
            self.assertIn("test", cfg["gates"]["implementation"])
            self.assertIn("typecheck", cfg["gates"]["implementation"])
            self.assertIn("lint", cfg["gates"]["implementation"])

            # Check review gate properties
            self.assertIn("base_branch", cfg["gates"]["review"])
            self.assertIn("reviewers", cfg["gates"]["review"])
            self.assertIn("max_iterations", cfg["gates"]["review"])

            # Check delivery gate properties
            self.assertIn("clean_worktree", cfg["gates"]["delivery"])
            self.assertIn("sync_specs", cfg["gates"]["delivery"])
            self.assertIn("archive_packages", cfg["gates"]["delivery"])

    def test_ledger_multi_change_isolation(self):
        """State ledger supports multiple distinct changes without collision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # 1. Mutate change-alpha
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "change-alpha",
                lambda entry: entry.update({
                    "phase": "implementation",
                    "blockers": ["1 failing test in test_alpha.py"],
                })
            )
            # 2. Mutate change-beta
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "change-beta",
                lambda entry: entry.update({
                    "phase": "review",
                    "blockers": [],
                })
            )

            ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=False)
            self.assertIn("change-alpha", ledger["changes"])
            self.assertIn("change-beta", ledger["changes"])
            self.assertEqual(ledger["changes"]["change-alpha"]["phase"], "implementation")
            self.assertEqual(ledger["changes"]["change-alpha"]["blockers"], ["1 failing test in test_alpha.py"])
            self.assertEqual(ledger["changes"]["change-beta"]["phase"], "review")
            self.assertEqual(ledger["changes"]["change-beta"]["blockers"], [])
            self.assertEqual(ledger["active_change_id"], "change-beta")

    def test_ledger_monotonic_revision_counter(self):
        """Revision counter monotonically increments on each change mutation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            entry1 = inspect_lifecycle.mutate_change_state(
                tmppath, "change-a", lambda e: e.update({"phase": "design"})
            )
            self.assertEqual(entry1["revision_counter"], 1)

            entry2 = inspect_lifecycle.mutate_change_state(
                tmppath, "change-a", lambda e: e.update({"phase": "implementation"})
            )
            self.assertEqual(entry2["revision_counter"], 2)

            entry3 = inspect_lifecycle.mutate_change_state(
                tmppath, "change-a", lambda e: e["task_status"].update({"completed": 3})
            )
            self.assertEqual(entry3["revision_counter"], 3)

    def test_ledger_atomic_persistence(self):
        """save_ledger atomically creates .agentflow/state.json without temp file remnants."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            data = {"version": 1, "active_change_id": "test", "changes": {}}
            inspect_lifecycle.save_ledger(tmppath, data)

            state_file = tmppath / ".agentflow" / "state.json"
            self.assertTrue(state_file.exists())
            loaded = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(loaded["active_change_id"], "test")

            # Check no .tmp files remain
            tmp_files = list((tmppath / ".agentflow").glob("*.tmp"))
            self.assertEqual(len(tmp_files), 0)

    def test_ledger_self_healing_from_workspace(self):
        """Missing .agentflow/state.json is reconstructed deterministically from workspace artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create OpenSpec package
            pkg_dir = tmppath / "openspec" / "changes" / "billing"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Setup DB\n- [ ] 2. Handle invoice\n")
            # Create ADR
            adr_dir = tmppath / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "ADR-0001-billing.md").write_text("# ADR\n**Status**: ACCEPTED\n")

            # Ensure .agentflow does NOT exist
            self.assertFalse((tmppath / ".agentflow" / "state.json").exists())

            # Load ledger should trigger self-healing sync
            ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=True)
            self.assertTrue((tmppath / ".agentflow" / "state.json").exists())
            self.assertIn("billing", ledger["changes"])
            billing = ledger["changes"]["billing"]
            self.assertEqual(billing["phase"], "design")
            self.assertTrue(any(b.startswith("Design:") for b in billing["blockers"]))
            self.assertEqual(billing["task_status"]["total"], 2)
            self.assertEqual(billing["task_status"]["completed"], 1)
            self.assertEqual(billing["task_status"]["pending"], 1)
            self.assertEqual(billing["evidence"]["design"]["status"], "ACCEPTED")

    def test_git_notes_evidence_attachment_and_retrieval(self):
        """Structured validation evidence can be attached and retrieved via git notes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)
            (tmppath / "code.py").write_text("print('hello')\n")
            subprocess.run(["git", "add", "code.py"], cwd=tmppath, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"], cwd=tmppath, check=True, capture_output=True, text=True
            )
            head_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=tmppath, check=True, capture_output=True, text=True
            ).stdout.strip()

            # Attach review evidence
            review_data = {"verdict": "PASS", "reviewer": "judge", "findings_count": 0}
            oid = inspect_lifecycle.attach_git_note_evidence(tmppath, head_sha, "review", review_data)
            self.assertIsNotNone(oid)

            # Retrieve evidence
            notes = inspect_lifecycle.read_git_note_evidence(tmppath, head_sha)
            self.assertIn("review", notes)
            self.assertEqual(notes["review"]["verdict"], "PASS")

            # Attach additional test evidence to the same commit
            test_data = {"passed": True, "tests_run": 42}
            inspect_lifecycle.attach_git_note_evidence(tmppath, head_sha, "tests", test_data)

            # Both should coexist in the note
            updated_notes = inspect_lifecycle.read_git_note_evidence(tmppath, head_sha)
            self.assertIn("review", updated_notes)
            self.assertIn("tests", updated_notes)
            self.assertEqual(updated_notes["tests"]["tests_run"], 42)

    def test_gate_trailers_generation(self):
        """Commit trailers are generated matching ship.json gates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "auth-v2",
                lambda entry: entry.update({
                    "phase": "delivery",
                    "task_status": {"total": 3, "completed": 3, "pending": 0},
                    "evidence": {
                        "design": {"adr": "docs/adr/ADR-0002-auth.md", "status": "ACCEPTED"},
                        "spike": {"status": "PASSED", "verdict": "latency < 20ms"},
                        "implementation": {"status": "PASSED", "tests_passed": True},
                        "simplify": {"debt_count": 0},
                        "review": {"verdict": "PASS", "reviewer": "judge", "status": "complete",
                                   "change": "auth-v2", "is_judge": True, "judge_report_valid": True,
                                   "test_evidence_passed": True},
                        "delivery": {"status": "READY"},
                    }
                })
            )

            pkg = tmppath / "openspec/changes/auth-v2"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] Done\n")
            self._approve_design(tmppath)
            trailers = inspect_lifecycle.generate_gate_trailers(tmppath, change_id="auth-v2")
            trailer_text = "\n".join(trailers)

            self.assertIn("Ship-Change: auth-v2", trailer_text)
            self.assertIn("Ship-Design: PASSED", trailer_text)
            self.assertIn("Ship-Spike: PASSED (latency < 20ms)", trailer_text)
            self.assertIn("Ship-Implementation: PASSED (1/1 tasks)", trailer_text)
            self.assertIn("Ship-Simplify: DEBT-0", trailer_text)
            self.assertIn("Ship-Review: PASS (by judge)", trailer_text)
            self.assertIn("Ship-Delivery: READY", trailer_text)

    def test_cli_ledger_and_trailers(self):
        """CLI arguments for setting active change, sync state, and trailers execute properly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "orders"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Order models\n")

            # 1. Sync state CLI
            code = inspect_lifecycle.main(["--path", str(tmppath), "--sync-state"])
            self.assertEqual(code, 0)
            self.assertTrue((tmppath / ".agentflow" / "state.json").exists())

            # 2. Set active change CLI
            code = inspect_lifecycle.main(["--path", str(tmppath), "--set-active-change", "orders"])
            self.assertEqual(code, 0)
            ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=False)
            self.assertEqual(ledger["active_change_id"], "orders")

            # 3. Generate trailers CLI
            code = inspect_lifecycle.main(["--path", str(tmppath), "--generate-trailers"])
            self.assertEqual(code, 0)

    def test_change_terminology_and_cli_flag(self):
        """Verify get/set/clear active change functions and --change CLI flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "user-profile"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [ ] 1. Schema migration\n")

            inspect_lifecycle.set_active_change(tmppath, "user-profile")
            self.assertEqual(inspect_lifecycle.get_active_change(tmppath), "user-profile")

            res = inspect_lifecycle.evaluate_repository(tmppath, target_change="user-profile")
            self.assertEqual(res["target_change"], "user-profile")
            self.assertEqual(res["active_change"]["change_id"], "user-profile")

            # Test --change CLI flag
            code = inspect_lifecycle.main(["--path", str(tmppath), "--change", "user-profile", "--format", "json"])
            self.assertEqual(code, 0)

            inspect_lifecycle.clear_active_change(tmppath, "user-profile")
            self.assertIsNone(inspect_lifecycle.get_active_change(tmppath))

    def test_review_report_path_recorded_in_ledger(self):
        """Verify review report path is correctly recorded in state.json evidence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            scratch = tmppath / ".scratch"
            scratch.mkdir(parents=True)
            report_file = scratch / "review_report.json"
            report_file.write_text(json.dumps({
                "reviewer": "judge",
                "status": "complete",
                "verdict": "PASS",
                "change": "payments",
                "findings": [],
                "test_evidence": True,
            }))

            entry = inspect_lifecycle.record_review_to_ledger(tmppath, report_file, change_id="payments")
            self.assertEqual(entry["evidence"]["review"]["report_path"], ".scratch/review_report.json")
            self.assertEqual(entry["evidence"]["review"]["verdict"], "PASS")

            # Also verify self-healing sync populates report_path
            synced = inspect_lifecycle.sync_ledger_from_workspace(tmppath, target_change_id="payments")
            self.assertEqual(synced["changes"]["payments"]["evidence"]["review"]["report_path"], ".scratch/review_report.json")

    def test_concurrent_ledger_mutations_preserve_all_changes(self):
        """Concurrent mutations to distinct change IDs must not clobber each other (flock protection)."""
        import concurrent.futures
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            change_ids = [f"change-{i}" for i in range(10)]

            def worker(cid: str) -> None:
                def updater(entry: dict) -> None:
                    entry["phase"] = "implementation"
                    entry["task_status"]["total"] = 5
                inspect_lifecycle.mutate_change_state(tmppath, cid, updater)

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                list(executor.map(worker, change_ids))

            ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=False)
            for cid in change_ids:
                self.assertIn(cid, ledger["changes"], f"Change {cid} was clobbered by concurrent writes!")
                self.assertEqual(ledger["changes"][cid]["phase"], "implementation")

    def test_ledger_blockers_and_failed_tests_prevent_delivery_ready(self):
        """Even with all tasks complete and review report present, failing tests in ledger block DELIVERY_READY."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "orders"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Task complete\n")

            scratch = tmppath / ".scratch"
            scratch.mkdir(parents=True)
            report_file = scratch / "review_report.json"
            report_file.write_text(json.dumps({
                "reviewer": "judge",
                "status": "complete",
                "verdict": "PASS",
                "change": "orders",
                "findings": [],
                "test_evidence": True,
            }))

            # Record a failed test in the ledger
            self._approve_design(tmppath)
            inspect_lifecycle.record_test_run_to_ledger(
                tmppath,
                {"passed": False, "failed_count": 1, "command": "pytest"},
                change_id="orders",
            )

            res = inspect_lifecycle.evaluate_repository(tmppath, target_change="orders")
            self.assertEqual(res["gate"], "implementation")
            self.assertEqual(res["state_key"], "TDD_ACTIVE")
            self.assertIn("Blocked by", res["next_action"])
            self.assertNotEqual(res["state_key"], "DELIVERY_READY")

    def test_notes_evidence_namespaced_by_change_id(self):
        """Different changes attaching evidence to the same commit do not overwrite each other."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)
            (tmppath / "f.txt").write_text("data\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "commit1"], cwd=tmppath, check=True)
            head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmppath, text=True).strip()

            inspect_lifecycle.attach_git_note_evidence(
                tmppath, head_sha, "test_evidence", {"passed": True, "suite": "alpha_suite"}, change_id="alpha"
            )
            inspect_lifecycle.attach_git_note_evidence(
                tmppath, head_sha, "test_evidence", {"passed": False, "suite": "beta_suite"}, change_id="beta"
            )

            # Read back for alpha
            alpha_notes = inspect_lifecycle.read_git_note_evidence(tmppath, head_sha, change_id="alpha")
            self.assertEqual(alpha_notes["test_evidence"]["suite"], "alpha_suite")
            self.assertTrue(alpha_notes["test_evidence"]["passed"])
            self.assertEqual(len(alpha_notes["test_evidence_runs"]), 1)
            self.assertEqual(alpha_notes["test_evidence_runs"][0]["commit"], head_sha)

            # Read back for beta
            beta_notes = inspect_lifecycle.read_git_note_evidence(tmppath, head_sha, change_id="beta")
            self.assertEqual(beta_notes["test_evidence"]["suite"], "beta_suite")
            self.assertFalse(beta_notes["test_evidence"]["passed"])
            self.assertEqual(len(beta_notes["test_evidence_runs"]), 1)

    def test_trailers_reflect_failed_tests_despite_completed_tasks(self):
        """When tasks are complete but tests failed, commit trailer emits FAILED instead of PASSED."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "billing",
                lambda entry: entry.update({
                    "phase": "implementation",
                    "task_status": {"total": 4, "completed": 4, "pending": 0},
                    "blockers": ["Tests: 1 test(s) failing"],
                    "evidence": {
                        "implementation": {"status": "FAILED", "tests_passed": False, "failed_count": 1},
                        "delivery": {"status": "READY"},
                    }
                })
            )

            trailers = inspect_lifecycle.generate_gate_trailers(tmppath, change_id="billing")
            trailer_text = "\n".join(trailers)
            self.assertIn("Ship-Implementation: FAILED", trailer_text)
            self.assertNotIn("Ship-Implementation: PASSED", trailer_text)
            self.assertIn("Ship-Delivery: BLOCKED", trailer_text)
            self.assertNotIn("Ship-Delivery: READY", trailer_text)

    def test_archive_clears_active_change_and_records_archived_delivery(self):
        """Archiving a package clears active_change_id to None and evaluates to ARCHIVED."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg = tmppath / "openspec" / "changes" / "notifications"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] 1. Dispatch push notifications\n")

            inspect_lifecycle.set_active_change(tmppath, "notifications")
            self.assertEqual(inspect_lifecycle.get_active_change(tmppath), "notifications")

            res = inspect_lifecycle.apply_and_archive_openspec(tmppath, "notifications", force=True)
            self.assertEqual(res["change"], "notifications")

            # Active change should be cleared
            self.assertIsNone(inspect_lifecycle.get_active_change(tmppath))
            state = inspect_lifecycle.load_ledger(tmppath, auto_sync=False)
            self.assertIsNone(state.get("active_change_id"))

            # Evaluating archived change reports ARCHIVED state
            eval_res = inspect_lifecycle.evaluate_repository(tmppath, target_change="notifications")
            self.assertEqual(eval_res["gate"], "delivery")
            self.assertEqual(eval_res["state_key"], "ARCHIVED")
            self.assertIn("notifications", eval_res["next_action"])

    def test_archive_rejected_if_ledger_has_failing_tests_or_blockers(self):
        """Archiving without --force is rejected if ledger contains failing tests or blockers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg = tmppath / "openspec" / "changes" / "checkout"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] 1. Cart checkout\n")

            scratch = tmppath / ".scratch"
            scratch.mkdir(parents=True)
            report_file = scratch / "review_report.json"
            report_file.write_text(json.dumps({
                "reviewer": "judge",
                "status": "complete",
                "verdict": "PASS",
                "change": "checkout",
                "findings": [],
                "test_evidence": True,
                "coverage": 100,
                "questions": [],
                "routing_notes": "",
            }))

            self._approve_design(tmppath)
            # Record failing test run to ledger
            inspect_lifecycle.record_test_run_to_ledger(
                tmppath,
                {"passed": False, "failed_count": 2, "command": "npm test"},
                change_id="checkout",
            )

            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, "checkout", force=False)
            self.assertIn("Tests: 2 test(s) failing", str(ctx.exception))

    def test_sync_ledger_preserves_archived_changes(self):
        """sync_ledger_from_workspace does not reset archived changes back to design."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg = tmppath / "openspec" / "changes" / "search"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] 1. Indexing\n")

            inspect_lifecycle.apply_and_archive_openspec(tmppath, "search", force=True)

            # Re-sync ledger
            synced = inspect_lifecycle.sync_ledger_from_workspace(tmppath)
            search_entry = synced["changes"]["search"]
            self.assertEqual(search_entry["phase"], "delivery")
            self.assertEqual(search_entry["evidence"]["delivery"]["status"], "ARCHIVED")

    def test_rollback_clears_obsolete_review_blockers(self):
        """Rolling back to implementation clears obsolete Review blockers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._init_git_repo(tmppath)
            (tmppath / "service.py").write_text("value = 1\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=tmppath, check=True, capture_output=True)
            inspect_lifecycle.create_checkpoint(tmppath, "implementation", change="auth")
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "auth",
                lambda entry: entry.update({
                    "phase": "review",
                    "blockers": ["Review: 2 unresolved CRITICAL/HIGH finding(s)", "Tests: 1 test(s) failing"],
                    "evidence": {
                        "review": {"verdict": "FAIL"},
                        "implementation": {"status": "PASSED"},
                    }
                })
            )

            inspect_lifecycle.perform_rollback(tmppath, target_gate="implementation", change="auth", force=True)
            ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=False)
            auth_entry = ledger["changes"]["auth"]
            self.assertEqual(auth_entry["phase"], "implementation")
            self.assertNotIn("Review: 2 unresolved CRITICAL/HIGH finding(s)", auth_entry["blockers"])
            self.assertIn("Tests: 1 test(s) failing", auth_entry["blockers"])

    def test_sync_from_workspace_preserves_concurrent_changes(self):
        """Workspace sync holds file lock across entire read-modify-save transaction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Pre-populate ledger with an active change
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "change-a",
                lambda entry: entry.update({"phase": "design", "blockers": []})
            )

            # Custom openspec inspector that concurrently inserts a new change into ledger while sync is running
            def inspecting_openspec(r, target_change=None):
                # Another agent mutates ledger during workspace discovery
                inspect_lifecycle.mutate_change_state(
                    r,
                    "change-b",
                    lambda entry: entry.update({"phase": "implementation", "blockers": []})
                )
                return [{"change": "change-a", "total_tasks": 1, "completed_tasks": 0, "pending_tasks": 1, "next_task": "T1"}]

            res = inspect_lifecycle.FileLedgerStore.sync_from_workspace(
                tmppath,
                inspect_openspec_fn=inspecting_openspec,
            )
            # Both change-a and concurrently added change-b must exist in ledger
            self.assertIn("change-a", res["changes"])
            self.assertIn("change-b", res["changes"])
            fresh_ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=False)
            self.assertIn("change-a", fresh_ledger["changes"])
            self.assertIn("change-b", fresh_ledger["changes"])

    def test_sync_preserves_explicit_blockers_and_increments_revision(self):
        """Explicit domain blockers (e.g. Awaiting design approval) survive sync and bump revision_counter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "feature-x",
                lambda entry: entry.update({
                    "phase": "design",
                    "blockers": ["Awaiting design approval", "Security team signoff"],
                    "revision_counter": 2,
                })
            )

            # Sync workspace with package that has tasks
            def inspect_pkg(r, target_change=None):
                return [{
                    "change": "feature-x",
                    "total_tasks": 2,
                    "completed_tasks": 0,
                    "pending_tasks": 2,
                    "next_task": "Task 1",
                }]

            synced = inspect_lifecycle.FileLedgerStore.sync_from_workspace(
                tmppath,
                inspect_openspec_fn=inspect_pkg,
            )

            fx = synced["changes"]["feature-x"]
            # Explicit blockers must still be present!
            self.assertIn("Awaiting design approval", fx["blockers"])
            self.assertIn("Security team signoff", fx["blockers"])
            # Missing approval remains blocked; discovered tasks still increment the revision
            self.assertEqual(fx["phase"], "design")
            self.assertGreater(fx["revision_counter"], 2)

    def test_concurrent_worktrees_git_notes_shared_locking(self):
        """Cross-worktree evidence recording synchronizes on shared git common dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            repo = tmppath / "main_repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            (repo / "file.txt").write_text("hello")
            subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)
            head_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

            # Create a second worktree
            wt_path = tmppath / "worktree_b"
            subprocess.run(["git", "worktree", "add", "-b", "branch_b", str(wt_path)], cwd=repo, check=True, capture_output=True)

            # Record evidence from worktree A (main) and worktree B (linked worktree)
            sha_a = inspect_lifecycle.attach_git_note_evidence(
                repo,
                head_sha,
                evidence_type="review",
                data={"verdict": "PASS", "reviewer": "judge"},
                change_id="change_alpha",
            )
            sha_b = inspect_lifecycle.attach_git_note_evidence(
                wt_path,
                head_sha,
                evidence_type="test_evidence",
                data={"suite": "wt_tests", "passed": True},
                change_id="change_beta",
            )

            self.assertEqual(sha_a, head_sha)
            self.assertEqual(sha_b, head_sha)

            # Both changes must be readable from both worktrees!
            alpha_notes_main = inspect_lifecycle.read_git_note_evidence(repo, head_sha, change_id="change_alpha")
            beta_notes_main = inspect_lifecycle.read_git_note_evidence(repo, head_sha, change_id="change_beta")
            alpha_notes_wt = inspect_lifecycle.read_git_note_evidence(wt_path, head_sha, change_id="change_alpha")
            beta_notes_wt = inspect_lifecycle.read_git_note_evidence(wt_path, head_sha, change_id="change_beta")

            self.assertEqual(alpha_notes_main["review"]["verdict"], "PASS")
            self.assertEqual(beta_notes_main["test_evidence"]["suite"], "wt_tests")
            self.assertEqual(alpha_notes_wt["review"]["verdict"], "PASS")
            self.assertEqual(beta_notes_wt["test_evidence"]["suite"], "wt_tests")

    def test_default_archive_picks_active_package_over_newer_package(self):
        """When change is None, archive targets active_change_id from ledger rather than newest mtime package."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            changes_dir = tmppath / "openspec" / "changes"
            alpha_dir = changes_dir / "alpha"
            beta_dir = changes_dir / "beta"
            alpha_dir.mkdir(parents=True)
            beta_dir.mkdir(parents=True)

            (alpha_dir / "tasks.md").write_text("- [x] Complete alpha task\n")
            (alpha_dir / "specs.md").write_text("## Requirement: Alpha\nAlpha spec")
            (beta_dir / "tasks.md").write_text("- [x] Complete beta task\n")
            (beta_dir / "specs.md").write_text("## Requirement: Beta\nBeta spec")

            # Set mtime of beta to be newer than alpha
            os.utime(str(alpha_dir), (1000, 1000))
            os.utime(str(beta_dir), (2000, 2000))

            # Ledger explicitly sets alpha as active_change_id
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "alpha",
                lambda entry: entry.update({
                    "phase": "delivery",
                    "blockers": [],
                    "evidence": {"delivery": {"status": "READY"}}
                }),
                set_active=True,
            )

            # Archive with change=None (default)
            res = inspect_lifecycle.apply_and_archive_openspec(tmppath, change=None, force=True)

            self.assertEqual(res["change"], "alpha")
            self.assertFalse(alpha_dir.exists())
            self.assertTrue(beta_dir.exists())  # beta must remain untouched!

    def test_trailers_detect_stale_review_when_working_tree_fingerprint_changes(self):
        """If source tree is modified after review, review trailer emits STALE and delivery emits BLOCKED."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg = tmppath / "openspec/changes/feature-y"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] Task\n")
            self._approve_design(tmppath)
            # Create a real git repo
            subprocess.run(["git", "init"], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)
            src_file = tmppath / "main.py"
            src_file.write_text("print('hello')\n")
            subprocess.run(["git", "add", "main.py"], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmppath, check=True)

            client = inspect_lifecycle.GitClient()
            git_info_original = client.get_info(tmppath)
            original_fp = git_info_original["working_tree_fingerprint"]

            # Record review passing with original fingerprint
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "feature-y",
                lambda entry: entry.update({
                    "phase": "delivery",
                    "blockers": [],
                    "task_status": {"total": 2, "completed": 2, "pending": 0},
                    "evidence": {
                        "implementation": {"status": "PASSED", "tests_passed": True},
                        "review": {
                            "verdict": "PASS",
                            "reviewer": "judge",
                            "snapshot_fingerprint": original_fp,
                            "change": "feature-y", "is_judge": True, "judge_report_valid": True,
                            "status": "complete", "test_evidence_passed": True,
                        },
                        "delivery": {"status": "READY"},
                    }
                }),
                set_active=True,
            )

            # Before modification: trailers are PASS and READY
            self._approve_design(tmppath)
            trailers_before = inspect_lifecycle.generate_gate_trailers(tmppath, change_id="feature-y")
            text_before = "\n".join(trailers_before)
            self.assertIn("Ship-Review: PASS (by judge)", text_before)
            self.assertIn("Ship-Delivery: READY", text_before)

            # Modify source file post-review
            src_file.write_text("print('modified post-review')\n")

            # After modification: trailers must detect stale review and block delivery!
            trailers_after = inspect_lifecycle.generate_gate_trailers(tmppath, change_id="feature-y")
            text_after = "\n".join(trailers_after)
            self.assertIn("Ship-Review: STALE (modified since review by judge)", text_after)
            self.assertNotIn("Ship-Review: PASS (by judge)", text_after)
            self.assertIn("Ship-Delivery: BLOCKED", text_after)
            self.assertNotIn("Ship-Delivery: READY", text_after)

    def test_record_review_preserves_snapshot_sha_and_invalidates_on_new_commit(self):
        """Review recording stores snapshot_sha and trailers detect when a new commit is made."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg = tmppath / "openspec/changes/feature-z"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] Task\n")
            self._approve_design(tmppath)
            subprocess.run(["git", "init"], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)
            f1 = tmppath / "file.txt"
            f1.write_text("v1\n")
            subprocess.run(["git", "add", "file.txt", "openspec"], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "commit 1"], cwd=tmppath, check=True)
            c1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmppath, check=True, capture_output=True, text=True).stdout.strip()

            # Record review targeting commit c1 (SHA-only review, no snapshot_fingerprint)
            review_dict = {
                "is_judge": True, "judge_report_valid": True,
                "change": "feature-z",
                "reviewer": "judge",
                "status": "complete",
                "verdict": "PASS",
                "findings_count": 0,
                "critical_or_high_count": 0,
                "test_evidence_passed": True,
                "snapshot_sha": c1,
                "snapshot_fingerprint": None,
                "findings": [],
                "coverage": ["all"],
                "questions": [],
                "routing_notes": [],
            }
            self._approve_design(tmppath)
            inspect_lifecycle.record_review_to_ledger(tmppath, review_dict, change_id="feature-z")

            ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=False)
            fz = ledger["changes"]["feature-z"]
            # snapshot_sha must be preserved in ledger!
            self.assertEqual(fz["evidence"]["review"]["snapshot_sha"], c1)

            # Trailers at commit c1 emit PASS and READY
            trailers_c1 = inspect_lifecycle.generate_gate_trailers(tmppath, change_id="feature-z")
            text_c1 = "\n".join(trailers_c1)
            self.assertIn("Ship-Review: PASS (by judge)", text_c1)
            self.assertIn("Ship-Delivery: READY", text_c1)

            # Now commit new code (c2)
            f1.write_text("v2\n")
            subprocess.run(["git", "add", "file.txt", "openspec"], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "commit 2"], cwd=tmppath, check=True)

            # Trailers at commit c2 must detect that HEAD no longer matches snapshot_sha!
            trailers_c2 = inspect_lifecycle.generate_gate_trailers(tmppath, change_id="feature-z")
            text_c2 = "\n".join(trailers_c2)
            self.assertIn("Ship-Review: STALE (modified since review by judge)", text_c2)
            self.assertNotIn("Ship-Review: PASS (by judge)", text_c2)
            self.assertIn("Ship-Delivery: BLOCKED", text_c2)
            self.assertNotIn("Ship-Delivery: READY", text_c2)

    def test_record_passing_review_clears_sync_generated_failure_blockers(self):
        """Recording a PASS review clears previous review blockers generated by workspace sync."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg = tmppath / "openspec/changes/auth-service"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] Task\n")
            self._approve_design(tmppath)
            # Create a package and initialize state
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "auth-service",
                lambda entry: entry.update({
                    "phase": "implementation",
                    "task_status": {"total": 1, "completed": 1, "pending": 0},
                    "evidence": {
                        "implementation": {"status": "PASSED", "tests_passed": True},
                    }
                })
            )

            # Sync workspace where review failed
            def inspect_pkg(r, target_change=None):
                return [{"change": "auth-service", "total_tasks": 1, "completed_tasks": 1, "pending_tasks": 0, "next_task": None}]

            def inspect_fail_review(r, change=None):
                return {
                    "reviewer": "judge",
                    "status": "fail",
                    "verdict": "FAIL",
                    "findings_count": 1,
                    "critical_or_high_count": 0,
                    "test_evidence_passed": True,
                }

            self._approve_design(tmppath)
            synced = inspect_lifecycle.FileLedgerStore.sync_from_workspace(
                tmppath,
                inspect_openspec_fn=inspect_pkg,
                inspect_review_fn=inspect_fail_review,
            )
            auth_entry = synced["changes"]["auth-service"]
            self.assertEqual(auth_entry["phase"], "review")
            self.assertIn("Review: verdict is FAIL", auth_entry["blockers"])

            # Now record a replacement PASS review
            pass_review = {
                "is_judge": True, "judge_report_valid": True,
                "change": "auth-service",
                "reviewer": "judge",
                "status": "complete",
                "verdict": "PASS",
                "findings_count": 0,
                "critical_or_high_count": 0,
                "test_evidence_passed": True,
                "findings": [],
                "coverage": [],
                "questions": [],
                "routing_notes": [],
            }
            self._approve_design(tmppath)
            updated = inspect_lifecycle.record_review_to_ledger(tmppath, pass_review, change_id="auth-service")

            # Obsolete review failure must be completely cleared and phase transitioned to delivery!
            self.assertNotIn("Review: verdict is FAIL", updated["blockers"])
            self.assertEqual(updated["blockers"], [])
            self.assertEqual(updated["phase"], "delivery")

    def test_sync_increments_revision_on_task_progress(self):
        """Completing a task increments revision_counter even when phase and blockers do not change."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg = tmppath / "openspec/changes/checkout"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [ ] Task\n")
            self._approve_design(tmppath)
            entry = inspect_lifecycle.mutate_change_state(
                tmppath,
                "checkout",
                lambda e: e.update({
                    "phase": "implementation",
                    "task_status": {"total": 2, "completed": 0, "pending": 2, "next": "Task 1", "in_progress": "Task 1"},
                    "blockers": [],
                })
            )
            initial_rev = entry["revision_counter"]

            # Sync workspace where 1 task is now completed (phase stays 'implementation', blockers remain empty)
            def inspect_pkg(r, target_change=None):
                return [{
                    "change": "checkout",
                    "total_tasks": 2,
                    "completed_tasks": 1,
                    "pending_tasks": 1,
                    "next_task": "Task 2",
                }]

            synced = inspect_lifecycle.FileLedgerStore.sync_from_workspace(
                tmppath,
                inspect_openspec_fn=inspect_pkg,
            )
            ch = synced["changes"]["checkout"]
            self.assertEqual(ch["task_status"]["completed"], 1)
            self.assertEqual(ch["phase"], "implementation")
            self.assertEqual(ch["blockers"], [])
            # Revision counter must be incremented by 1!
            self.assertEqual(ch["revision_counter"], initial_rev + 1)


    def test_review_approval_contract_matches_ledger_and_trailers(self):
        """A fresh PASS cannot bypass Judge, schema, tests, or change validation."""
        for invalid in ({"reviewer": "correctness"}, {"status": "skipped"},
                        {"test_evidence": False}, {"change": "other"}, {"coverage": "invalid"}):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                self._init_git_repo(root)
                pkg = root / "openspec/changes/feature"
                pkg.mkdir(parents=True)
                (pkg / "tasks.md").write_text("- [x] Done\n")
                subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
                subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
                inspect_lifecycle.set_active_change(root, "feature")
                self._approve_design(root)
                inspect_lifecycle.sync_ledger_from_workspace(root)
                report = root / ".scratch/review_report.json"
                report.parent.mkdir()
                payload = {
                    "change": "feature", "reviewer": "judge", "status": "complete", "verdict": "PASS",
                    "findings": [], "coverage": ["Checked"], "questions": [], "routing_notes": [],
                    "test_evidence": True,
                    "working_tree_fingerprint": inspect_lifecycle.compute_working_tree_fingerprint(root),
                }
                payload.update(invalid)
                report.write_text(json.dumps(payload))
                entry = inspect_lifecycle.record_review_to_ledger(root, report, "feature")
                self.assertEqual(entry["phase"], "review")
                self.assertNotEqual(inspect_lifecycle.evaluate_repository(root)["state_key"], "DELIVERY_READY")
                for sync in (False, True):
                    if sync:
                        inspect_lifecycle.sync_ledger_from_workspace(root)
                    trailers = inspect_lifecycle.generate_gate_trailers(root, "feature")
                    self.assertNotIn("Ship-Review: PASS (by judge)", trailers)
                    self.assertNotIn("Ship-Delivery: READY", trailers)
                    self.assertIn("Ship-Delivery: BLOCKED", trailers)

    def test_sha_review_ignores_evidence_but_rejects_source_edits(self):
        """Evaluation, recording and trailers use the same source-only dirty check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._init_git_repo(root)
            pkg = root / "openspec/changes/feature"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] Done\n")
            (root / "service.py").write_text("value = 1\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            self._approve_design(root)
            inspect_lifecycle.set_active_change(root, "feature")
            inspect_lifecycle.sync_ledger_from_workspace(root)
            report = root / ".scratch/review_report.json"
            report.parent.mkdir()
            report.write_text(json.dumps({
                "change": "feature", "reviewer": "judge", "status": "complete", "verdict": "PASS",
                "findings": [], "coverage": ["Checked"], "questions": [], "routing_notes": [],
                "test_evidence": True, "commit": sha,
            }))
            entry = inspect_lifecycle.record_review_to_ledger(root, report, "feature")
            self.assertEqual(entry["phase"], "delivery")
            self.assertFalse(inspect_lifecycle.get_git_info(root)["is_clean"])
            self.assertEqual(inspect_lifecycle.evaluate_repository(root)["state_key"], "DELIVERY_READY")
            self.assertIn("Ship-Review: PASS (by judge)", inspect_lifecycle.generate_gate_trailers(root, "feature"))
            self.assertIn("Ship-Delivery: READY", inspect_lifecycle.generate_gate_trailers(root, "feature"))
            (root / "service.py").write_text("value = 2\n")
            self.assertNotEqual(inspect_lifecycle.evaluate_repository(root)["state_key"], "DELIVERY_READY")
            trailers = inspect_lifecycle.generate_gate_trailers(root, "feature")
            self.assertTrue(any(t.startswith("Ship-Review: STALE") for t in trailers))
            self.assertIn("Ship-Delivery: BLOCKED", trailers)
            self.assertEqual(inspect_lifecycle.record_review_to_ledger(root, report, "feature")["phase"], "review")


    def _recovery_repo(self, root):
        self._init_git_repo(root)
        pkg = root / "openspec/changes/alpha"
        pkg.mkdir(parents=True)
        (pkg / "tasks.md").write_text("- [x] Done\n")
        (root / "alpha.py").write_text("alpha = 1\n")
        (root / "beta.py").write_text("beta = 1\n")
        subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
        return pkg

    def test_rollback_rejects_other_active_changes_without_mutation(self):
        for source in ("ledger", "package", "default"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                self._recovery_repo(root)
                inspect_lifecycle.create_checkpoint(root, "design", change="alpha")
                if source in {"ledger", "default"}:
                    inspect_lifecycle.mutate_change_state(root, "default" if source == "default" else "beta", lambda e: e.update(phase="review"))
                else:
                    pkg = root / "openspec/changes/beta"
                    pkg.mkdir()
                    (pkg / "tasks.md").write_text("- [x] Done\n")
                (root / "alpha.py").write_text("alpha = 2\n")
                (root / "beta.py").write_text("beta = 2\n")
                before = (root / ".agentflow/state.json").read_bytes()
                for force in (False, True):
                    with self.assertRaisesRegex(RuntimeError, "isolated worktrees"):
                        inspect_lifecycle.perform_rollback(root, "design", change="alpha", force=force)
                self.assertEqual((root / "beta.py").read_text(), "beta = 2\n")
                self.assertEqual((root / "alpha.py").read_text(), "alpha = 2\n")
                self.assertEqual((root / ".agentflow/state.json").read_bytes(), before)

    def test_rollback_requires_valid_checkpoint_before_clearing_failures(self):
        for bad in ("missing", "corrupt", "missing-object", "mismatched-ref"):
            with self.subTest(checkpoint=bad), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                pkg = self._recovery_repo(root)
                if bad != "missing":
                    inspect_lifecycle.create_checkpoint(root, "design", change="alpha")
                    receipt = root / ".agentflow/checkpoints/alpha_design.json"
                    if bad == "corrupt":
                        receipt.write_text("{")
                    elif bad == "missing-object":
                        data = json.loads(receipt.read_text())
                        data["snapshot_commit"] = "f" * 40
                        receipt.write_text(json.dumps(data))
                    else:
                        subprocess.run(["git", "update-ref", "refs/ship/alpha/design", "HEAD"], cwd=root, check=True)
                inspect_lifecycle.record_test_run_to_ledger(root, {"passed": False, "failed_count": 1}, "alpha")
                before = (root / ".agentflow/state.json").read_bytes()
                with self.assertRaises(RuntimeError):
                    inspect_lifecycle.perform_rollback(root, "design", change="alpha")
                self.assertEqual((root / ".agentflow/state.json").read_bytes(), before)
                self.assertEqual((pkg / "tasks.md").read_text(), "- [x] Done\n")

    def test_corrupt_ledger_is_preserved_by_all_state_operations(self):
        for invalid in ('{"changes":', '{"version":1,"changes":[]}', '{"version":9,"changes":{}}'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                self._recovery_repo(root)
                (root / ".agentflow").mkdir()
                state = root / ".agentflow/state.json"
                state.write_text(invalid)
                operations = [
                    lambda: inspect_lifecycle.load_ledger(root),
                    lambda: inspect_lifecycle.sync_ledger_from_workspace(root),
                    lambda: inspect_lifecycle.set_active_change(root, "alpha"),
                    lambda: inspect_lifecycle.mutate_change_state(root, "alpha", lambda e: e.update(blockers=[])),
                    lambda: inspect_lifecycle.clear_active_change(root),
                    lambda: inspect_lifecycle.save_ledger(root, {"version": 1, "changes": {}}),
                    lambda: inspect_lifecycle.create_checkpoint(root, "design", change="alpha"),
                ]
                for operation in operations:
                    with self.assertRaisesRegex(ValueError, "preserved unchanged"):
                        operation()
                    self.assertEqual(state.read_text(), invalid)
                # Explicit operator recovery preserves the damaged file for inspection.
                state.rename(state.with_suffix(".damaged"))
                self.assertIn("alpha", inspect_lifecycle.sync_ledger_from_workspace(root)["changes"])

    def test_rollback_backup_failure_preserves_code_and_ledger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._recovery_repo(root)
            inspect_lifecycle.create_checkpoint(root, "design", change="alpha")
            (root / "alpha.py").write_text("alpha = 2\n")
            (root / "new.py").write_text("precious new code\n")
            before = (root / ".agentflow/state.json").read_bytes()
            with patch("lifecycle.checkpoints.shutil.copy2", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(RuntimeError, "Rollback failed"):
                    inspect_lifecycle.perform_rollback(root, "design", change="alpha", force=True)
            self.assertEqual((root / "alpha.py").read_text(), "alpha = 2\n")
            self.assertEqual((root / "new.py").read_text(), "precious new code\n")
            self.assertEqual((root / ".agentflow/state.json").read_bytes(), before)

    def test_failed_checkpoint_snapshot_does_not_replace_previous_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._recovery_repo(root)
            inspect_lifecycle.create_checkpoint(root, "design", change="alpha")
            receipt = root / ".agentflow/checkpoints/alpha_design.json"
            before = receipt.read_bytes()
            (root / "alpha.py").write_text("uncommitted work\n")
            from lifecycle.vcs import GitClient
            original = GitClient.run_cmd
            def fail_commit(client, path, *args, **kwargs):
                if args and args[0] == "commit-tree":
                    raise subprocess.CalledProcessError(1, args, stderr="failed snapshot")
                return original(client, path, *args, **kwargs)
            with patch.object(GitClient, "run_cmd", fail_commit):
                with self.assertRaisesRegex(RuntimeError, "snapshot failed"):
                    inspect_lifecycle.create_checkpoint(root, "design", change="alpha")
            self.assertEqual(receipt.read_bytes(), before)
            self.assertEqual((root / "alpha.py").read_text(), "uncommitted work\n")

    def test_rollback_preserves_unusual_filenames_in_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._recovery_repo(root)
            name = ' odd"name\n.py'
            (root / name).write_text("original\n")
            subprocess.run(["git", "add", "--", name], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "filename"], cwd=root, check=True, capture_output=True)
            inspect_lifecycle.create_checkpoint(root, "design", change="alpha")
            (root / name).write_text("changed\n")
            result = inspect_lifecycle.perform_rollback(root, "design", change="alpha", force=True)
            self.assertEqual((root / name).read_text(), "original\n")
            self.assertEqual((root / result["backup_directory"] / name).read_text(), "changed\n")


    def test_failed_git_note_write_does_not_advance_ledger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._recovery_repo(root)
            inspect_lifecycle.mutate_change_state(root, "alpha", lambda e: e.update(blockers=["Hold"]))
            before = (root / ".agentflow/state.json").read_bytes()
            from lifecycle.vcs import GitClient
            with patch.object(GitClient, "attach_git_note_evidence", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "Git notes; ledger unchanged"):
                    inspect_lifecycle.record_test_run_to_ledger(root, {"passed": True}, "alpha")
                with self.assertRaisesRegex(RuntimeError, "Git notes; ledger unchanged"):
                    inspect_lifecycle.record_review_to_ledger(root, {"verdict": "PASS"}, "alpha")
            self.assertEqual((root / ".agentflow/state.json").read_bytes(), before)

    def test_unborn_checkpoint_cannot_be_used_for_rollback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._init_git_repo(root)
            inspect_lifecycle.create_checkpoint(root, "design", change="alpha")
            before = (root / ".agentflow/state.json").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "with commits"):
                inspect_lifecycle.perform_rollback(root, "design", change="alpha")
            self.assertEqual((root / ".agentflow/state.json").read_bytes(), before)


    def _archive_workspace(self, root, changes):
        living = root / "openspec/specs/shared.md"
        living.parent.mkdir(parents=True)
        living.write_text("### Requirement: Base\nBase behavior\n")
        for cid in changes:
            pkg = root / "openspec/changes" / cid
            (pkg / "specs").mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] Done\n")
            (pkg / "specs/shared.md").write_text(f"### Requirement: {cid}\n{cid} behavior\n")
            report = root / ".scratch" / cid / "review_report.json"
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({
                "change": cid, "reviewer": "judge", "status": "complete", "verdict": "PASS",
                "findings": [], "coverage": ["Checked"], "questions": [], "routing_notes": [],
                "test_evidence": True,
            }))
        self._approve_design(root)
        inspect_lifecycle.sync_ledger_from_workspace(root)
        return living

    def test_concurrent_archives_preserve_both_spec_updates(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from lifecycle import specs
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            living = self._archive_workspace(root, ["alpha", "beta"])
            first_merging = threading.Event()
            release_first = threading.Event()
            second_started = threading.Event()
            second_finished = threading.Event()
            original = specs.merge_spec_requirements
            def controlled_merge(old, delta):
                if "alpha behavior" in delta:
                    first_merging.set()
                    if not release_first.wait(5):
                        raise RuntimeError("test timed out waiting for release")
                return original(old, delta)
            def archive_beta():
                second_started.set()
                try:
                    return inspect_lifecycle.apply_and_archive_openspec(root, "beta")
                finally:
                    second_finished.set()
            with patch.object(specs, "merge_spec_requirements", controlled_merge), ThreadPoolExecutor(2) as pool:
                alpha = pool.submit(inspect_lifecycle.apply_and_archive_openspec, root, "alpha")
                try:
                    self.assertTrue(first_merging.wait(5))
                    beta = pool.submit(archive_beta)
                    self.assertTrue(second_started.wait(5))
                    self.assertFalse(second_finished.wait(0.2), "second archive bypassed the transaction lock")
                finally:
                    release_first.set()
                alpha.result(timeout=5)
                beta.result(timeout=5)
            text = living.read_text()
            self.assertIn("alpha behavior", text)
            self.assertIn("beta behavior", text)
            state = inspect_lifecycle.load_ledger(root)
            for cid in ("alpha", "beta"):
                self.assertEqual(state["changes"][cid]["evidence"]["delivery"]["status"], "ARCHIVED")
                self.assertFalse((root / "openspec/changes" / cid).exists())

    def test_archive_ledger_failure_restores_files_and_active_pointer(self):
        from lifecycle.ledger import FileLedgerStore
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            living = self._archive_workspace(root, ["alpha"])
            new_spec = root / "openspec/changes/alpha/specs/new.md"
            new_spec.write_text("### Requirement: New\nNew behavior\n")
            self._approve_design(root)
            inspect_lifecycle.set_active_change(root, "alpha")
            state = root / ".agentflow/state.json"
            before_state = state.read_bytes()
            living.write_bytes(living.read_bytes().replace(b"\n", b"\r\n"))
            before_spec = living.read_bytes()
            with patch.object(FileLedgerStore, "save", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(RuntimeError, "Archive failed.*disk full"):
                    inspect_lifecycle.apply_and_archive_openspec(root, "alpha")
            self.assertEqual(state.read_bytes(), before_state)
            self.assertEqual(living.read_bytes(), before_spec)
            self.assertTrue(new_spec.exists())
            self.assertFalse((root / "openspec/specs/new.md").exists())
            self.assertEqual(list((root / "openspec/archive").iterdir()), [])
            # Retry succeeds once persistence is available.
            result = inspect_lifecycle.apply_and_archive_openspec(root, "alpha")
            self.assertTrue((root / result["archived_path"]).is_dir())
            self.assertIsNone(inspect_lifecycle.get_active_change(root))
            self.assertIn("Ship-Delivery: ARCHIVED", result["trailers"])

    def test_archive_reports_incomplete_recovery(self):
        from lifecycle import specs
        from lifecycle.ledger import FileLedgerStore
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._archive_workspace(root, ["alpha"])
            original_move = specs.shutil.move
            calls = []
            def fail_recovery(src, dst):
                calls.append((src, dst))
                if len(calls) > 1:
                    raise OSError("cannot restore package")
                return original_move(src, dst)
            with patch.object(FileLedgerStore, "save", side_effect=OSError("disk full")), patch.object(specs.shutil, "move", fail_recovery):
                with self.assertRaisesRegex(RuntimeError, "recovery incomplete.*cannot restore package"):
                    inspect_lifecycle.apply_and_archive_openspec(root, "alpha")


    def test_archive_without_ledger_has_one_final_state_write(self):
        from lifecycle.ledger import FileLedgerStore
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._archive_workspace(root, ["alpha"])
            (root / ".agentflow/state.json").unlink()
            with patch.object(FileLedgerStore, "save", wraps=FileLedgerStore.save) as save:
                inspect_lifecycle.apply_and_archive_openspec(root, "alpha", force=True)
            self.assertEqual(save.call_count, 1)
            state = inspect_lifecycle.load_ledger(root)
            self.assertEqual(set(state["changes"]), {"alpha"})
            self.assertEqual(state["changes"]["alpha"]["evidence"]["delivery"]["status"], "ARCHIVED")

    def test_next_turn_planning_across_lifecycle_phases(self):
        """get_next_turn_contract deterministically derives specialist turn contracts across phases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for args in [("init", "-b", "main"), ("config", "user.name", "Test"),
                         ("config", "user.email", "test@example.com"), ("config", "commit.gpgsign", "false")]:
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

            # Phase 1: Clean workspace -> design turn
            contract = inspect_lifecycle.get_next_turn(root)
            self.assertEqual(contract.skill, "design")
            self.assertIn(contract.phase, {"INITIAL_PROPOSAL", "FRONTIER_ROUNDS"})
            self.assertEqual(contract.role, "Senior Principal Systems Architect")

            # Phase 2: Design compiled but unapproved -> design approval turn
            pkg = root / "openspec/changes/alpha"
            (pkg / "specs").mkdir(parents=True)
            (pkg / "proposal.md").write_text("# Proposal\n")
            (pkg / "tasks.md").write_text("- [ ] Task 1\n")
            (pkg / "specs/spec.md").write_text("### Requirement: Spec\nSpec text\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "add spec"], cwd=root, check=True, capture_output=True)
            contract2 = inspect_lifecycle.get_next_turn(root, target_change="alpha")
            self.assertEqual(contract2.skill, "design")
            self.assertEqual(contract2.phase, "DESIGN_APPROVAL_REQUIRED")

            # Phase 3: Approved design with unchecked tasks -> tdd turn
            from lifecycle.evidence import design_fingerprint
            dfp = design_fingerprint(root, "alpha")
            inspect_lifecycle.FileLedgerStore.approve_design(root, "alpha", dfp, "architect")
            inspect_lifecycle.set_active_change(root, "alpha")
            contract3 = inspect_lifecycle.get_next_turn(root, target_change="alpha")
            self.assertEqual(contract3.skill, "tdd")
            self.assertEqual(contract3.phase, "TDD_ACTIVE")
            self.assertEqual(contract3.inputs["current_task"], "Task 1")

            # Phase 4: All tasks checked, review pending -> review turn
            (pkg / "tasks.md").write_text("- [x] Task 1\n")
            contract4 = inspect_lifecycle.get_next_turn(root, target_change="alpha")
            self.assertEqual(contract4.skill, "review")
            self.assertEqual(contract4.phase, "REVIEW_ACTIVE")

            # Phase 5: Judge PASS -> delivery turn
            # Phase 5: Judge PASS and tests passed -> delivery turn
            inspect_lifecycle.record_test_run_to_ledger(root, {"passed": True}, change_id="alpha")
            tree_fp = inspect_lifecycle.compute_working_tree_fingerprint(root)
            rev_file = root / ".scratch/alpha/review_report.json"
            rev_file.parent.mkdir(parents=True, exist_ok=True)
            rev_file.write_text(json.dumps({
                "change": "alpha", "reviewer": "judge", "status": "complete", "verdict": "PASS",
                "findings": [], "coverage": ["checked"], "questions": [], "routing_notes": [],
                "test_evidence": True, "working_tree_fingerprint": tree_fp,
            }))
            inspect_lifecycle.record_review_to_ledger(root, str(rev_file), change_id="alpha")
            verify_fixture(root, "alpha")
            contract5 = inspect_lifecycle.get_next_turn(root, target_change="alpha")
            self.assertEqual(contract5.skill, "delivery")
            self.assertEqual(contract5.phase, "DELIVERY_READY")

    def test_next_turn_cli_text_and_json(self):
        """CLI --next-turn outputs formatted turn contracts in text and JSON."""
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Text format
            out_buf = io.StringIO()
            with contextlib.redirect_stdout(out_buf):
                ret = inspect_lifecycle.main(["--path", str(root), "--next-turn"])
            self.assertEqual(ret, 0)
            text_out = out_buf.getvalue()
            self.assertIn("TURN CONTRACT: DESIGN", text_out)
            self.assertIn("DECLARED INPUTS", text_out)
            self.assertIn("EXIT VERIFICATION CHECKLIST", text_out)

            # JSON format
            json_buf = io.StringIO()
            with contextlib.redirect_stdout(json_buf):
                ret = inspect_lifecycle.main(["--path", str(root), "--next-turn", "--format", "json"])
            self.assertEqual(ret, 0)
            data = json.loads(json_buf.getvalue())
            self.assertEqual(data["skill"], "design")
            self.assertEqual(data["role"], "Senior Principal Systems Architect")

    def test_record_turn_and_provenance_retrieval(self):
        """Turns can be recorded into ledger and retrieved via API and CLI."""
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # Record turn via API
            turn_data = {
                "skill": "tdd",
                "harness": "claude-code",
                "execution_mode": "sequential",
                "inputs": {"task": "Task 1: Add authentication"},
                "evidence": {"tests_passed": True, "tests_run": 5},
                "state_delta": {"completed_tasks": 1},
            }
            res = inspect_lifecycle.record_turn(root, turn_data, change_id="alpha")
            self.assertEqual(res["change_id"], "alpha")
            turns = inspect_lifecycle.get_turns(root, change_id="alpha")
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0]["turn_id"], "turn-001")
            self.assertEqual(turns[0]["skill"], "tdd")
            self.assertEqual(turns[0]["harness"], "claude-code")
            self.assertTrue(turns[0]["evidence"]["tests_passed"])

            # Record second turn via CLI
            cli_turn = json.dumps({
                "skill": "review",
                "harness": "cursor",
                "inputs": {"scope": "auth.py"},
                "evidence": {"verdict": "PASS"},
            })
            ret = inspect_lifecycle.main(["--path", str(root), "--change", "alpha", "--record-turn", cli_turn])
            self.assertEqual(ret, 0)
            turns2 = inspect_lifecycle.get_turns(root, change_id="alpha")
            self.assertEqual(len(turns2), 2)
            self.assertEqual(turns2[1]["turn_id"], "turn-002")
            self.assertEqual(turns2[1]["skill"], "review")
            self.assertEqual(turns2[1]["harness"], "cursor")

            # Display provenance log via CLI --turns
            out_buf = io.StringIO()
            with contextlib.redirect_stdout(out_buf):
                self.assertEqual(inspect_lifecycle.main(["--path", str(root), "--change", "alpha", "--turns"]), 0)
            output = out_buf.getvalue()
            self.assertIn("TURN PROVENANCE AUDIT TRAIL FOR 'alpha'", output)
            self.assertIn("Skill: TDD", output)
            self.assertIn("Skill: REVIEW", output)

    def test_turn_provenance_backward_compatibility_and_validation(self):
        """Ledgers without turns remain valid; corrupt turns are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".agentflow").mkdir()
            state_file = root / ".agentflow/state.json"
            # Legacy ledger without turns
            legacy = {
                "version": 1,
                "active_change_id": "legacy",
                "changes": {
                    "legacy": {
                        "change_id": "legacy",
                        "phase": "design",
                        "task_status": {},
                        "blockers": [],
                        "revision_counter": 1,
                        "evidence": {},
                    }
                }
            }
            state_file.write_text(json.dumps(legacy))
            loaded = inspect_lifecycle.load_ledger(root)
            self.assertEqual(loaded["version"], 1)
            self.assertEqual(inspect_lifecycle.get_turns(root, "legacy"), [])

            # Corrupt turns: not a list
            corrupt1 = {
                "version": 1,
                "changes": {
                    "bad": {
                        "turns": "not-a-list",
                    }
                }
            }
            state_file.write_text(json.dumps(corrupt1))
            with self.assertRaises(ValueError):
                inspect_lifecycle.load_ledger(root)

            # Corrupt turns: contains non-dict element
            corrupt2 = {
                "version": 1,
                "changes": {
                    "bad": {
                        "turns": ["string-instead-of-dict"],
                    }
                }
            }
            state_file.write_text(json.dumps(corrupt2))
            with self.assertRaises(ValueError):
                inspect_lifecycle.load_ledger(root)

    def test_utility_scratch_dirs_not_flagged_as_active_spikes(self):
        """Utility directories like velocity, sessions, reports must not be treated as active spikes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for utility_name in ["velocity", "sessions", "reports"]:
                d = root / ".agentflow" / "spikes" / utility_name
                d.mkdir(parents=True)
                (d / "data.json").write_text("{}")
            spikes = inspect_lifecycle.inspect_spikes(root)
            self.assertEqual(spikes, [])

    def test_ensure_gitignore_has_ship_fallback_on_exclude_error(self):
        """If writing to .git/info/exclude fails, ensure_gitignore_has_ship falls back to .gitignore."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            info_dir = root / ".git" / "info"
            info_dir.mkdir(parents=True)
            exclude_file = info_dir / "exclude"
            # Create exclude as a directory or non-writable path to trigger OS exception on open("a")
            exclude_file.mkdir()  # IsADirectoryError when opened as file
            inspect_lifecycle.ensure_gitignore_has_ship(root)
            gitignore = root / ".gitignore"
            self.assertTrue(gitignore.exists())
            self.assertIn(".agentflow/", gitignore.read_text())

    def test_resolve_skill_name(self):
        """Delivery gate activity maps to ship orchestrator skill."""
        self.assertEqual(inspect_lifecycle.resolve_skill_name("delivery"), "ship")
        self.assertEqual(inspect_lifecycle.resolve_skill_name("review"), "review")
        self.assertEqual(inspect_lifecycle.resolve_skill_name("design"), "design")
        self.assertEqual(inspect_lifecycle.resolve_skill_name("tdd"), "tdd")
        self.assertEqual(inspect_lifecycle.resolve_skill_name("simplify"), "simplify")
        self.assertEqual(inspect_lifecycle.resolve_skill_name("spike"), "spike")

    def test_working_tree_fingerprint_handles_untracked_symlinks(self):
        """Untracked broken and valid symbolic links must be hashed deterministically without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for args in [("init", "-b", "main"), ("config", "user.name", "Dev"),
                         ("config", "user.email", "dev@example.com"), ("config", "commit.gpgsign", "false")]:
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            (root / "README.md").write_text("# Hello\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)

            fp_clean = inspect_lifecycle.compute_working_tree_fingerprint(root)
            self.assertIsNotNone(fp_clean)

            # Untracked broken symlink
            symlink = root / "broken_link"
            symlink.symlink_to("nonexistent_target_1")
            fp_broken = inspect_lifecycle.compute_working_tree_fingerprint(root)
            self.assertNotEqual(fp_clean, fp_broken)

            # Mutate symlink target
            symlink.unlink()
            symlink.symlink_to("nonexistent_target_2")
            fp_mutated = inspect_lifecycle.compute_working_tree_fingerprint(root)
            self.assertNotEqual(fp_broken, fp_mutated)

            # Remove symlink restores clean fingerprint
            symlink.unlink()
            fp_restored = inspect_lifecycle.compute_working_tree_fingerprint(root)
            self.assertEqual(fp_clean, fp_restored)

    def test_validate_walkthrough_report(self):
        from ship.lifecycle import validate_walkthrough_report

        good_walkthrough = (
            "# Ship Delivery Walkthrough: User Authentication\n\n"
            "## Architecture\n"
            "Implemented as specified in [docs/adr/ADR-0001-auth.md](docs/adr/ADR-0001-auth.md).\n\n"
            "## Review Scorecard\n"
            "| Stage | Status |\n"
            "| Concurrency | PASS |\n"
            "Judge PASS verdict received.\n\n"
            "## Technical Debt\n"
            "Scanned with scan_debt.py; 0 debt markers found.\n\n"
            "## Usage & Cost\n"
            "- Tokens: 125,000\n"
            "- Cost: $0.45 USD\n"
        )
        errors = validate_walkthrough_report(good_walkthrough)
        self.assertEqual(errors, [])

        # Missing cost summary
        bad_walkthrough = (
            "# Ship Delivery\n"
            "docs/adr/ADR-0001.md\n"
            "Review scorecard: PASS\n"
            "technical debt: clean\n"
        )
        bad_errors = validate_walkthrough_report(bad_walkthrough)
        self.assertTrue(any("SHP-COST-001" in e for e in bad_errors))

    def test_ship_fixtures(self):
        fixtures_dir = ROOT / "tests/fixtures/ship"

        # 01-unapproved-design-bypass
        f1_data = json.loads((fixtures_dir / "01-unapproved-design-bypass/state.json").read_text())
        auth_data = f1_data["changes"]["auth-tokens"]["evidence"]["design"]
        self.assertIsNone(auth_data["approval"])

        # 02-dirty-delivery-invalidation
        f2_data = json.loads((fixtures_dir / "02-dirty-delivery-invalidation/delivery_evidence.json").read_text())
        self.assertNotEqual(f2_data["reviewed_tree_fingerprint"], f2_data["current_tree_fingerprint"])

        # 03-unchecked-task-premature-advance
        tasks_text = (fixtures_dir / "03-unchecked-task-premature-advance/tasks.md").read_text()
        self.assertIn("- [ ]", tasks_text)

        # 04-fabricated-test-receipt
        f4_data = json.loads((fixtures_dir / "04-fabricated-test-receipt/receipt.json").read_text())
        self.assertFalse(f4_data["passed"])
        self.assertEqual(f4_data["tests_run"], 0)

    def test_evaluate_ship_rubric(self):
        sys.path.insert(0, str(ROOT / "tests/evaluation"))
        import evaluate_ship_rubric

        evaluator = evaluate_ship_rubric.ShipRubricEvaluator(passing_threshold=0.80)

        good_walkthrough = (
            "# Delivery Walkthrough\n"
            "Design: Approved in docs/adr/ADR-0001.md and openspec/changes/auth/tasks.md.\n"
            "Implementation: TDD red-green-refactor complete. Ran 42 tests in 0.15s (exit code: 0).\n"
            "Review: Judge PASS verdict confirmed with 0 critical findings.\n"
            "Delivery: Clean tree fingerprint verified.\n"
            "Usage: Tokens: 50,000 | Cost: $0.20 USD\n"
        )
        rep_good = evaluator.evaluate_delivery(good_walkthrough, target_name="GoodShip")
        self.assertTrue(rep_good.passed)
        self.assertEqual(rep_good.status, "PASS")

    def test_approve_design_auto_and_smart_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "streamlined-feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "proposal.md").write_text("# Proposal\n")
            (pkg_dir / "tasks.md").write_text("# Tasks\n- [ ] 1. Build\n")

            # Test 1: Run inspect_lifecycle main with --approve-design auto and --change
            with patch.object(sys, "argv", ["inspect_lifecycle.py", "--path", str(tmppath), "--approve-design", "auto", "--change", "streamlined-feature"]):
                self.assertEqual(inspect_lifecycle.main(), 0)

            state = inspect_lifecycle.load_ledger(tmppath)
            self.assertIn("streamlined-feature", state.get("changes", {}))
            self.assertEqual(state["changes"]["streamlined-feature"]["evidence"]["design"]["approval"]["approved_by"], "session-user")

            # Test 2: Modify proposal and approve with --approve-design without arguments (const="auto") and auto-detected change
            (pkg_dir / "proposal.md").write_text("# Proposal updated\n")
            with patch.object(sys, "argv", ["inspect_lifecycle.py", "--path", str(tmppath), "--approve-design"]):
                self.assertEqual(inspect_lifecycle.main(), 0)

            state2 = inspect_lifecycle.load_ledger(tmppath)
            self.assertEqual(state2["changes"]["streamlined-feature"]["evidence"]["design"]["approval"]["approved_by"], "session-user")
            self.assertNotEqual(
                state["changes"]["streamlined-feature"]["evidence"]["design"]["approval"]["fingerprint"],
                state2["changes"]["streamlined-feature"]["evidence"]["design"]["approval"]["fingerprint"],
            )


if __name__ == "__main__":
    unittest.main()




