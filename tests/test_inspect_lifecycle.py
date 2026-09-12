"""Unit tests for ship lifecycle inspector (inspect_lifecycle.py)."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSPECT_LIFECYCLE = ROOT / "skills" / "ship" / "scripts" / "inspect_lifecycle.py"

sys.path.insert(0, str(INSPECT_LIFECYCLE.parent))
import inspect_lifecycle


class TestInspectLifecycle(unittest.TestCase):
    def test_gate1_empty_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            res = inspect_lifecycle.evaluate_repository(Path(tmpdir))
            self.assertEqual(res["gate"], "GATE 1: SPECIFICATION & DESIGN")
            self.assertEqual(res["state_key"], "INITIAL_PROPOSAL")
            self.assertIn("Run '/design'", res["next_action"])

    def test_gate1b_active_spike(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            spike_dir = tmppath / ".scratch" / "spike_redis_perf"
            spike_dir.mkdir(parents=True)

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 1b: EMPIRICAL SPIKE ACTIVE")
            self.assertEqual(res["state_key"], "SPIKE_ACTIVE")
            self.assertIn("spike_redis_perf", res["next_action"])

    def test_gate1_adr_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            adr_dir = tmppath / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "ADR-0001-events.md").write_text("# ADR\n**Status**: ACCEPTED\n")

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 1: SPECIFICATION & DESIGN")
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
            self.assertEqual(res["gate"], "GATE 1: SPECIFICATION & DESIGN")
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

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 2: IMPLEMENTATION (TDD + SIMPLIFY)")
            self.assertEqual(res["state_key"], "TDD_ACTIVE")
            self.assertIn("1/3 tasks complete", res["next_action"])
            self.assertIn("2. Handle retries with jitter", res["next_action"])

    def test_gate3_audit_active_when_tasks_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "webhooks"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text(
                "# Tasks\n"
                "- [x] 1. Setup endpoint\n"
                "- [x] 2. Handle retries with jitter\n"
            )

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
            self.assertIn("review-loop mode", res["next_action"])

    def test_gate4_ready_to_ship_with_passed_audit(self):
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
                    "topic": "webhooks",
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

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 4: READY TO SHIP")
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

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
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

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
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

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
            self.assertIn("lacks verified test evidence", res["next_action"])

    def test_cli_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [sys.executable, str(INSPECT_LIFECYCLE), "--path", str(tmpdir), "--format", "json"]
            run = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0)
            data = json.loads(run.stdout)
            self.assertEqual(data["gate"], "GATE 1: SPECIFICATION & DESIGN")
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

            # With force=True to bypass audit requirement in unit test
            res = inspect_lifecycle.apply_and_archive_openspec(tmppath, "billing", force=True)
            self.assertEqual(res["topic"], "billing")
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

            # Verify lifecycle state reset to Gate 1
            eval_data = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(eval_data["gate"], "GATE 1: SPECIFICATION & DESIGN")
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
            res_fail = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_fail["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res_fail["state_key"], "AUDIT_ACTIVE")
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
            self.assertEqual(res_bad_tests["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res_bad_tests["state_key"], "AUDIT_ACTIVE")
            self.assertIn("lacks verified test evidence", res_bad_tests["next_action"])

    def test_archive_blocked_when_tasks_pending_or_audit_missing(self):
        """Reproduction for Issue 3: archiving must validate package completion before mutating."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "unfinished"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [ ] 1. Pending task\n")

            # 1. Unchecked tasks must block archiving
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, "unfinished")
            self.assertIn("pending tasks in tasks.md", str(ctx.exception))

            # 2. Completed tasks without passing audit must block archiving
            (pkg_dir / "tasks.md").write_text("- [x] 1. Finished task\n")
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, "unfinished")
            self.assertIn("no passing audit report found", str(ctx.exception))

    def test_resume_selects_active_topic_and_ignores_completed_spikes(self):
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

            # evaluate_repository must select 'z-current' in TDD_ACTIVE, NOT 'a-old' in AUDIT_ACTIVE
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 2: IMPLEMENTATION (TDD + SIMPLIFY)")
            self.assertEqual(res["state_key"], "TDD_ACTIVE")
            self.assertEqual(res["openspec_packages"][0]["topic"], "z-current")

            # Explicit openspec/.active persistence
            inspect_lifecycle.set_active_topic(tmppath, "a-old")
            res_explicit = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_explicit["openspec_packages"][0]["topic"], "a-old")

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
            subprocess.run(["git", "init"], cwd=tmppath, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

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
                "topic": "feature",
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
            res_clean = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_clean["gate"], "GATE 4: READY TO SHIP")
            self.assertEqual(res_clean["state_key"], "DELIVERY_READY")

            # Now modify implementation to raise an exception
            src_file.write_text("def run(): raise RuntimeError('unreviewed crash')\n")

            # Must revoke DELIVERY_READY and demand re-audit
            res_dirty = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_dirty["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res_dirty["state_key"], "AUDIT_ACTIVE")
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
            validate_script = ROOT / "skills" / "audit" / "scripts" / "validate_report.py"
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
                "topic": "payments",
                "verdict": "PASS",
                "snapshot": {"commit": "HEAD"},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 10},
                "judge_report": canonical_judge_report,
            }
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 4: READY TO SHIP")
            self.assertEqual(res["state_key"], "DELIVERY_READY")
            self.assertTrue(res["audit_report"]["is_envelope"])

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

    def test_explicit_invalid_topic_fails_visibly(self):
        """Reproduction for Issue 5: requesting an invalid topic must error, not silently fall back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "auth"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Auth done\n")

            # Direct inspect_openspec call with invalid topic
            with self.assertRaises(ValueError) as ctx:
                inspect_lifecycle.inspect_openspec(tmppath, target_topic="auth-typo")
            self.assertIn("auth-typo", str(ctx.exception))
            self.assertIn("Available: auth", str(ctx.exception))

            # CLI call with --topic auth-typo
            cmd = [sys.executable, str(INSPECT_LIFECYCLE), "--path", str(tmpdir), "--topic", "auth-typo"]
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

    def test_envelope_topic_mismatch_blocks_delivery_and_archive(self):
        """Reproduction for Issue 1: approval envelope for topic 'auth' cannot authorise package 'billing'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "billing"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Billing implemented\n")

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            # Envelope approves topic 'auth'
            envelope = {
                "schema_version": "1.0",
                "topic": "auth",
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

            # Delivery check must reject because envelope topic is 'auth', but active package is 'billing'
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
            self.assertIn("Audit approval is for topic 'auth'", res["next_action"])
            self.assertIn("billing", res["next_action"])

            # Archive must raise RuntimeError
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, topic="billing")
            self.assertIn("audit approval is for topic 'auth'", str(ctx.exception))

            # Matching topic 'billing' clears gate
            envelope["topic"] = "billing"
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))
            res_ok = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_ok["gate"], "GATE 4: READY TO SHIP")
            self.assertEqual(res_ok["state_key"], "DELIVERY_READY")

    def test_reviewed_working_tree_fingerprint_clears_delivery_and_detects_subsequent_changes(self):
        """Reproduction for Issue 2: reviewed working tree modifications clear delivery via fingerprint; post-review edits are blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

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
                "topic": "feature",
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
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 4: READY TO SHIP")
            self.assertEqual(res["state_key"], "DELIVERY_READY")

            # Post-review modification: change service.py
            service_file.write_text("def run(): return 999\n")

            # Fingerprint mismatch must revoke DELIVERY_READY
            res_modified = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_modified["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res_modified["state_key"], "AUDIT_ACTIVE")
            self.assertIn("fingerprint mismatch", res_modified["next_action"])

            # Archive must also be blocked by fingerprint mismatch
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, topic="feature")
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
            subprocess.run(["git", "init"], cwd=tmppath, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

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
                "topic": "feature",
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
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
            self.assertIn("symbolic or unresolved", res["next_action"])

            # Archive must also reject symbolic commit
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, topic="feature")
            self.assertIn("symbolic or unresolved", str(ctx.exception))

            # Resolving to immutable commit SHA clears delivery
            head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmppath, capture_output=True, text=True).stdout.strip()
            envelope["snapshot"]["commit"] = head_commit
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(envelope))
            res_resolved = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_resolved["gate"], "GATE 4: READY TO SHIP")
            self.assertEqual(res_resolved["state_key"], "DELIVERY_READY")

            # Subsequent commit (regression) invalidates the immutable SHA approval
            src_file.write_text("def run(): raise RuntimeError('broken')\n")
            subprocess.run(["git", "add", "service.py"], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Regression"], cwd=tmppath, check=True)

            res_regression = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_regression["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res_regression["state_key"], "AUDIT_ACTIVE")
            self.assertIn("does not match current commit", res_regression["next_action"])

    def test_malformed_nested_judge_report_blocks_delivery(self):
        """Reproduction for Issue 2: delivery gate strictly validates nested Judge report contract."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

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
                "topic": "feature",
                "verdict": "PASS",
                "snapshot": {"commit": head_commit},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 5},
                "judge_report": {"reviewer": "judge"},
            }
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps(malformed_envelope))

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
            self.assertIn("Judge report in delivery envelope is malformed", res["next_action"])

            # Archive must also reject malformed judge report
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, topic="feature")
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
            self.assertEqual(res_valid["gate"], "GATE 4: READY TO SHIP")
            self.assertEqual(res_valid["state_key"], "DELIVERY_READY")

    def test_archive_failure_rolls_back_specs_and_allows_resumable_recovery(self):
        """Reproduction for Issue 3: archive failure rolls back spec changes, and retry recovers without blocking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

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
                "topic": "auth",
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

            # Simulate failure during directory move
            import unittest.mock as mock
            with mock.patch("shutil.move", side_effect=OSError("Simulated move failure")):
                with self.assertRaises(RuntimeError) as ctx:
                    inspect_lifecycle.apply_and_archive_openspec(tmppath, topic="auth")
                self.assertIn("Simulated move failure", str(ctx.exception))

            # Spec modification must be rolled back!
            self.assertEqual(living_spec.read_text(), living_content)
            self.assertTrue(pkg_dir.exists())

            # Now retry with normal shutil.move - archive must succeed cleanly
            inspect_lifecycle.apply_and_archive_openspec(tmppath, topic="auth")
            # Living spec should now contain both Login and Logout
            merged_text = living_spec.read_text()
            self.assertIn("Requirement: Login", merged_text)
            self.assertIn("Requirement: Logout", merged_text)
            self.assertFalse(pkg_dir.exists())

    def test_active_topic_persistence_does_not_revoke_delivery_or_block_archive(self):
        """Active topic written to openspec/.active must not count as an unreviewed source modification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=tmppath, check=True)

            pkg = tmppath / "openspec" / "changes" / "feat"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] 1. Done\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmppath, check=True)
            commit_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmppath, capture_output=True, text=True).stdout.strip()

            (tmppath / ".scratch").mkdir()
            (tmppath / ".scratch" / "delivery_evidence.json").write_text(json.dumps({
                "topic": "feat",
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

            # Set active topic
            inspect_lifecycle.set_active_topic(tmppath, "feat")

            # Must remain DELIVERY_READY (not revoked to AUDIT_ACTIVE due to openspec/.active)
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 4: READY TO SHIP")
            self.assertEqual(res["state_key"], "DELIVERY_READY")

            # Must archive cleanly without error about openspec/.active
            arch_res = inspect_lifecycle.apply_and_archive_openspec(tmppath, topic="feat")
            self.assertEqual(arch_res["topic"], "feat")

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
            subprocess.run(["git", "init"], cwd=tmppath, check=True, capture_output=True)

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

    def test_legacy_flat_report_without_topic_or_contract_blocks_delivery(self):
        """A flat report lacking topic or standard contract fields (status, findings, coverage) must block delivery."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            # Flat legacy report missing topic and required contract fields
            (scratch_dir / "review_report.json").write_text(json.dumps({
                "reviewer": "judge",
                "verdict": "PASS",
                "commit": "abc1234",
                "test_evidence": True,
            }))

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
            self.assertTrue(
                "Audit approval lacks 'topic'" in res["next_action"]
                or "Judge report is malformed" in res["next_action"]
            )

    def test_malformed_topic_evidence_blocks_delivery_without_fallback(self):
        """Malformed topic evidence (judge_report: null) must block delivery and not fall back to global approval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            # Global passing report (older approval)
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps({
                "topic": "feature",
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

            # Topic-specific envelope with judge_report: null
            topic_scratch = scratch_dir / "feature"
            topic_scratch.mkdir()
            (topic_scratch / "delivery_evidence.json").write_text(json.dumps({
                "topic": "feature",
                "verdict": "PASS",
                "judge_report": None,
                "test_evidence": True,
            }))

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
            self.assertIn("Judge report in delivery envelope is malformed", res["next_action"])
            self.assertIn("Envelope is missing required 'judge_report' object", res["next_action"])

    def test_normalize_req_title_handles_bracketed_and_prefixed_ids(self):
        """normalize_req_title strips bracketed requirement tags and colon prefixes."""
        self.assertEqual(inspect_lifecycle.normalize_req_title("[REQ-001] User Authentication"), "user authentication")
        self.assertEqual(inspect_lifecycle.normalize_req_title("REQ-002: User Authentication"), "user authentication")
        self.assertEqual(inspect_lifecycle.normalize_req_title("**[REQ-003] User Authentication**"), "user authentication")

    def test_pre_commit_repo_requires_working_tree_fingerprint(self):
        """In a repo before first commit, an audit report must provide matching snapshot fingerprint and not a fake commit SHA."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True, capture_output=True)

            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Done\n")

            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            # 1. Report without snapshot_fingerprint
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps({
                "topic": "feature",
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

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
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
                "topic": "feature",
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
            self.assertEqual(res2["gate"], "GATE 4: READY TO SHIP")
            self.assertEqual(res2["state_key"], "DELIVERY_READY")

    def test_archiving_package_does_not_create_phantom_active_spike(self):
        """Retained delivery evidence in .scratch/<topic> must not be flagged as an active spike after archiving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True, capture_output=True)
            pkg_dir = tmppath / "openspec" / "changes" / "auth"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Auth implementation\n")

            scratch_dir = tmppath / ".scratch" / "auth"
            scratch_dir.mkdir(parents=True)
            current_fp = inspect_lifecycle.compute_working_tree_fingerprint(tmppath)
            (scratch_dir / "delivery_evidence.json").write_text(json.dumps({
                "topic": "auth",
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
            res_ready = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res_ready["gate"], "GATE 4: READY TO SHIP")
            self.assertEqual(res_ready["state_key"], "DELIVERY_READY")

            # Successfully archive auth
            inspect_lifecycle.apply_and_archive_openspec(tmppath, topic="auth")

            # Next evaluation must NOT treat .scratch/auth as an active spike
            res_after = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertNotEqual(res_after["state_key"], "SPIKE_ACTIVE")
            self.assertEqual(len(res_after["active_spikes"]), 0)
            self.assertEqual(res_after["gate"], "GATE 1: SPECIFICATION & DESIGN")

    def test_skipped_judge_review_blocks_delivery_and_archive(self):
        """A report with status: skipped must block delivery and archiving even if verdict is PASS."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init", "-b", "main"], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

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
                "topic": "feature",
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
            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertEqual(res["gate"], "GATE 3: ADVERSARIAL AUDIT")
            self.assertEqual(res["state_key"], "AUDIT_ACTIVE")
            self.assertIn("not complete", res["next_action"])

            # Archive must also reject skipped status
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, topic="feature")
            self.assertIn("requires 'complete'", str(ctx.exception))

    def test_ship_json_config_loading(self):
        """Verify .ship.json config loading and overriding in inspect_lifecycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            config_data = {
                "project": {"name": "billing", "scope": "services/billing"},
                "gates": {
                    "gate2_tdd": {"test_command": "pnpm test"},
                    "gate3_audit": {"max_fix_iterations": 5, "debt_threshold": 2},
                },
            }
            (tmppath / ".ship.json").write_text(json.dumps(config_data))

            cfg = inspect_lifecycle.load_ship_config(tmppath)
            self.assertEqual(cfg["config_source"], ".ship.json")
            self.assertEqual(cfg["project"]["name"], "billing")
            self.assertEqual(cfg["project"]["scope"], "services/billing")
            self.assertEqual(cfg["gates"]["gate2_tdd"]["test_command"], "pnpm test")
            self.assertEqual(cfg["gates"]["gate3_audit"]["max_fix_iterations"], 5)

            # Check format_summary displays config
            eval_data = inspect_lifecycle.evaluate_repository(tmppath)
            summary = inspect_lifecycle.format_summary(eval_data)
            self.assertIn(".ship.json", summary)
            self.assertIn("pnpm test", summary)

    def test_ship_yaml_config_loading(self):
        """Verify zero-dependency .ship.yaml parsing and loading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            yaml_content = """# Ship lifecycle configuration
project:
  name: "auth-service"
gates:
  gate2_tdd:
    test_command: "pytest -q"
  gate3_audit:
    max_fix_iterations: 4
"""
            (tmppath / ".ship.yaml").write_text(yaml_content)

            cfg = inspect_lifecycle.load_ship_config(tmppath)
            self.assertEqual(cfg["config_source"], ".ship.yaml")
            self.assertEqual(cfg["project"]["name"], "auth-service")
            self.assertEqual(cfg["gates"]["gate2_tdd"]["test_command"], "pytest -q")
            self.assertEqual(cfg["gates"]["gate3_audit"]["max_fix_iterations"], 4)

    def test_create_checkpoint_and_rollback(self):
        """Verify checkpoint creation and safe rollback with backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

            # Setup openspec package
            pkg_dir = tmppath / "openspec" / "changes" / "payment"
            pkg_dir.mkdir(parents=True)
            tasks_file = pkg_dir / "tasks.md"
            tasks_file.write_text("- [x] Task 1: Setup stripe\n- [ ] Task 2: Webhooks\n")

            service_file = tmppath / "service.py"
            service_file.write_text("def pay(): pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial spec commit"], cwd=tmppath, check=True)

            # Create checkpoint for gate-1
            chk = inspect_lifecycle.create_checkpoint(tmppath, "gate-1-spec", topic="payment")
            self.assertEqual(chk["gate"], "gate-1-spec")
            self.assertEqual(chk["topic"], "payment")
            self.assertTrue(chk["ref_created"])
            chk_file = tmppath / ".scratch" / "checkpoints" / "payment_gate-1-spec.json"
            self.assertTrue(chk_file.exists())

            # Now simulate partial dirty edits in gate 2
            service_file.write_text("def pay(): return 'broken'\n")
            tasks_file.write_text("- [x] Task 1: Setup stripe\n- [x] Task 2: Webhooks\n")

            # Perform rollback to gate-1-spec
            rb = inspect_lifecycle.perform_rollback(tmppath, "gate-1-spec", topic="payment")
            self.assertEqual(rb["status"], "success")
            self.assertEqual(rb["target_gate"], "gate-1-spec")
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
            subprocess.run(["git", "init"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

            # Setup checkpoint at gate-1-spec
            pkg_dir = tmppath / "openspec" / "changes" / "payment"
            pkg_dir.mkdir(parents=True)
            tasks_file = pkg_dir / "tasks.md"
            tasks_file.write_text("- [x] Task 1: Setup stripe\n")
            service_file = tmppath / "service.py"
            service_file.write_text("def pay(): pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial checkpoint commit"], cwd=tmppath, check=True)

            inspect_lifecycle.create_checkpoint(tmppath, "gate-1-spec", topic="payment")

            # Commit a broken implementation and an additional file in gate 2
            service_file.write_text("def pay(): raise RuntimeError('broken')\n")
            extra_file = tmppath / "extra.py"
            extra_file.write_text("def extra(): pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Broken gate 2 implementation"], cwd=tmppath, check=True)

            # Perform rollback to gate-1-spec
            rb = inspect_lifecycle.perform_rollback(tmppath, "gate-1-spec", topic="payment")
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

    def test_ship_yaml_multiline_lists_and_comments(self):
        """Verify YAML parser handles multiline bullet lists and unquoted inline comments."""
        yaml_text = """
project:
  name: "billing" # Project name comment
gates:
  gate2_tdd:
    test_command: "pytest -q" # quiet mode
  gate3_audit:
    max_fix_iterations: 3
    critical_paths:
      - services/billing/core
      - services/billing/api
"""
        parsed = inspect_lifecycle.parse_simple_yaml(yaml_text)
        self.assertEqual(parsed["project"]["name"], "billing")
        self.assertEqual(parsed["gates"]["gate2_tdd"]["test_command"], "pytest -q")
        self.assertEqual(parsed["gates"]["gate3_audit"]["max_fix_iterations"], 3)
        self.assertEqual(
            parsed["gates"]["gate3_audit"]["critical_paths"],
            ["services/billing/core", "services/billing/api"],
        )

    def test_checkpoint_in_precommit_repo(self):
        """Verify checkpoint gracefully handles repository before first commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True)
            chk = inspect_lifecycle.create_checkpoint(tmppath, "gate-1-spec", topic="new-feature")
            self.assertEqual(chk["gate"], "gate-1-spec")
            self.assertEqual(chk["commit"], "none")
            self.assertFalse(chk["ref_created"])
            self.assertTrue((tmppath / ".scratch" / "checkpoints" / "new-feature_gate-1-spec.json").exists())

    def test_status_check_exit_codes(self):
        """Verify --status-check exit code returns: 0 for ready, 1 for in-progress, 2 for audit rejection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Empty repo -> Gate 1 -> status_check exit code 1 (in-progress)
            code = inspect_lifecycle.main(["--path", str(tmppath), "--status-check"])
            self.assertEqual(code, 1)

            # Add failing audit report -> status_check exit code 2 (remediation/rollback)
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()
            report_data = {
                "reviewer": "judge",
                "status": "fail",
                "verdict": "FAIL",
                "critical_or_high_count": 1,
            }
            (scratch_dir / "audit_report.json").write_text(json.dumps(report_data))
            code = inspect_lifecycle.main(["--path", str(tmppath), "--status-check"])
            self.assertEqual(code, 2)

    def test_rollback_preserves_precheckpoint_uncommitted_edits(self):
        """Verify rollback restores checkpoint state without reverting uncommitted edits made prior to checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

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
            chk = inspect_lifecycle.create_checkpoint(tmppath, "gate-1-spec", topic="payment")
            self.assertTrue(chk["ref_created"])
            self.assertIn("snapshot_commit", chk)

            # 4. User changes implementation in gate 2 and modifies unrelated file again
            service_file.write_text("def pay(): raise RuntimeError('broken')\n")
            unrelated_file.write_text("unrelated post-checkpoint modification\n")
            new_gate2_file = tmppath / "gate2_temp.py"
            new_gate2_file.write_text("temp = 1\n")

            # 5. Perform rollback to gate-1-spec
            rb = inspect_lifecycle.perform_rollback(tmppath, "gate-1-spec", topic="payment")
            self.assertEqual(rb["status"], "success")

            # 6. Verify unrelated file reverted to CHECKPOINT content (not initial commit content!)
            self.assertEqual(unrelated_file.read_text(), "unrelated pre-checkpoint edit\n")
            # Verify service.py reverted to its checkpoint state
            self.assertEqual(service_file.read_text(), "def pay(): pass\n")
            # Verify new file created after checkpoint was removed
            self.assertFalse(new_gate2_file.exists())

    def test_rollback_preserves_tracked_files_matching_gitignore(self):
        """Verify rollback does not delete tracked files that happen to match .gitignore rules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

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
            chk = inspect_lifecycle.create_checkpoint(tmppath, "gate-1-spec", topic="payment")
            self.assertTrue(chk["ref_created"])

            # 3. User modifies service.py in gate 2
            service_file.write_text("def pay(): raise RuntimeError('broken')\n")

            # 4. Perform rollback
            rb = inspect_lifecycle.perform_rollback(tmppath, "gate-1-spec", topic="payment")
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
            (chk_dir / "feature_gate-1-spec.json").write_text(json.dumps({"topic": "feature", "gate": "gate-1-spec"}))

            # Create a rollback backup directory
            rollback_dir = scratch_dir / "rollback_20260912_120000"
            rollback_dir.mkdir()
            (rollback_dir / "dummy.py").write_text("dummy = 1\n")

            # Create an audit evidence dir with audit_report.json
            evidence_dir = scratch_dir / "old-evidence"
            evidence_dir.mkdir()
            (evidence_dir / "audit_report.json").write_text(json.dumps({"status": "complete"}))

            spikes = inspect_lifecycle.inspect_spikes(tmppath)
            self.assertEqual(spikes, [])

            res = inspect_lifecycle.evaluate_repository(tmppath)
            self.assertNotEqual(res["state_key"], "SPIKE_ACTIVE")
            self.assertEqual(res["gate"], "GATE 2: IMPLEMENTATION (TDD + SIMPLIFY)")

    def test_audit_report_json_recognized_as_evidence_dir(self):
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

    def test_topic_suffixed_audit_and_review_reports_discovered(self):
        """inspect_audit_reports must discover .scratch/review_report_<topic>.json and audit_report_<topic>.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            scratch_dir = tmppath / ".scratch"
            scratch_dir.mkdir()

            rev_file = scratch_dir / "review_report_billing.json"
            rev_file.write_text(json.dumps({
                "reviewer": "judge",
                "status": "complete",
                "verdict": "PASS",
                "topic": "billing",
                "findings": [],
                "coverage": ["billing.py"],
                "questions": [],
                "routing_notes": [],
                "tests_passed": True,
            }))

            rep = inspect_lifecycle.inspect_audit_reports(tmppath, topic="billing")
            self.assertIsNotNone(rep)
            self.assertEqual(rep["topic"], "billing")
            self.assertTrue(rep["test_evidence_passed"])

    def test_porcelain_quoted_filenames_stripped(self):
        """Filenames enclosed in double quotes by git status porcelain must have quotes stripped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init", "-b", "main"], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

            spaced_file = tmppath / "spaced file.py"
            spaced_file.write_text("x = 1\n")
            subprocess.run(["git", "add", "spaced file.py"], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmppath, check=True, capture_output=True)

            spaced_file.write_text("x = 2\n")
            git_info = inspect_lifecycle.get_git_info(tmppath)
            self.assertIn("spaced file.py", git_info["modified_source_files"])
            self.assertNotIn('"spaced file.py"', git_info["modified_source_files"])


if __name__ == "__main__":
    unittest.main()




