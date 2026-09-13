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
            self.assertTrue(
                "Audit approval is for change 'auth'" in res["next_action"]
                or "Audit approval is for topic 'auth'" in res["next_action"]
            )
            self.assertIn("billing", res["next_action"])

            # Archive must raise RuntimeError
            with self.assertRaises(RuntimeError) as ctx:
                inspect_lifecycle.apply_and_archive_openspec(tmppath, topic="billing")
            self.assertTrue(
                "audit approval is for change 'auth'" in str(ctx.exception)
                or "audit approval is for topic 'auth'" in str(ctx.exception)
            )

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
                "Audit approval lacks 'change'" in res["next_action"]
                or "Audit approval lacks 'topic'" in res["next_action"]
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
                    "implementation": {"test": "pnpm test"},
                    "simplify": {"max_debt": 2},
                    "audit": {"max_iterations": 5},
                },
            }
            (tmppath / ".ship.json").write_text(json.dumps(config_data))

            cfg = inspect_lifecycle.load_ship_config(tmppath)
            self.assertEqual(cfg["config_source"], ".ship.json")
            self.assertEqual(cfg["project"]["name"], "billing")
            self.assertEqual(cfg["project"]["scope"], "services/billing")
            self.assertEqual(cfg["gates"]["implementation"]["test"], "pnpm test")
            self.assertEqual(cfg["gates"]["simplify"]["max_debt"], 2)
            self.assertEqual(cfg["gates"]["audit"]["max_iterations"], 5)

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
  implementation:
    test: "pytest -q"
  audit:
    max_iterations: 4
"""
            (tmppath / ".ship.yaml").write_text(yaml_content)

            cfg = inspect_lifecycle.load_ship_config(tmppath)
            self.assertEqual(cfg["config_source"], ".ship.yaml")
            self.assertEqual(cfg["project"]["name"], "auth-service")
            self.assertEqual(cfg["gates"]["implementation"]["test"], "pytest -q")
            self.assertEqual(cfg["gates"]["audit"]["max_iterations"], 4)

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
  implementation:
    test: "pytest -q" # quiet mode
  audit:
    max_iterations: 3
    critical_paths:
      - services/billing/core
      - services/billing/api
"""
        parsed = inspect_lifecycle.parse_simple_yaml(yaml_text)
        self.assertEqual(parsed["project"]["name"], "billing")
        self.assertEqual(parsed["gates"]["implementation"]["test"], "pytest -q")
        self.assertEqual(parsed["gates"]["audit"]["max_iterations"], 3)
        self.assertEqual(
            parsed["gates"]["audit"]["critical_paths"],
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

    def test_rollback_handles_renamed_files(self):
        """Rollback must restore original file and remove destination when a file was renamed after checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init", "-b", "main"], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

            pkg_dir = tmppath / "openspec" / "changes" / "feature"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "tasks.md").write_text("- [x] 1. Initial task\n")

            orig_file = tmppath / "original.py"
            orig_file.write_text("def orig(): pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmppath, check=True, capture_output=True)

            # Create checkpoint for Gate 2
            chk = inspect_lifecycle.create_checkpoint(tmppath, gate_name="gate-2-impl", topic="feature")
            self.assertEqual(chk["gate"], "gate-2-impl")

            # Rename file using git mv
            subprocess.run(["git", "mv", "original.py", "renamed.py"], cwd=tmppath, check=True)
            self.assertFalse((tmppath / "original.py").exists())
            self.assertTrue((tmppath / "renamed.py").exists())

            # Perform rollback
            rb = inspect_lifecycle.perform_rollback(tmppath, target_gate="gate-2-impl", topic="feature")
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

    def test_checkpoint_private_ref_does_not_pollute_tags(self):
        """create_checkpoint must isolate refs to refs/ship/ without creating refs/tags/ by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

            (tmppath / "README.md").write_text("# Test\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Init"], cwd=tmppath, check=True, capture_output=True)

            # 1. Default: records to refs/ship/... but NOT to refs/tags/
            chk = inspect_lifecycle.create_checkpoint(tmppath, "gate-1-spec", topic="auth")
            self.assertTrue(chk["ref_created"])
            self.assertFalse(chk["tag_created"])
            self.assertIsNone(chk["tag"])

            ref_check = subprocess.run(
                ["git", "rev-parse", "--verify", "refs/ship/auth/gate-1-spec"],
                cwd=tmppath, capture_output=True, text=True
            )
            self.assertEqual(ref_check.returncode, 0)

            tag_check = subprocess.run(
                ["git", "rev-parse", "--verify", "refs/tags/ship/auth/gate-1-spec"],
                cwd=tmppath, capture_output=True, text=True
            )
            self.assertNotEqual(tag_check.returncode, 0)

            # 2. With create_git_tag=True: explicitly permits git tag in refs/tags/
            chk_tagged = inspect_lifecycle.create_checkpoint(tmppath, "gate-1-spec", topic="auth", create_git_tag=True)
            self.assertTrue(chk_tagged["tag_created"])
            self.assertIsNotNone(chk_tagged["tag"])

            tag_check2 = subprocess.run(
                ["git", "rev-parse", "--verify", "refs/tags/ship/auth/gate-1-spec"],
                cwd=tmppath, capture_output=True, text=True
            )
            self.assertEqual(tag_check2.returncode, 0)

    def test_rollback_preserves_untracked_directories_and_files(self):
        """Rollback must safely archive newly created untracked directories and files into untracked_removed/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

            (tmppath / "main.py").write_text("def main(): pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Base"], cwd=tmppath, check=True, capture_output=True)

            # Checkpoint
            inspect_lifecycle.create_checkpoint(tmppath, "gate-1-spec", topic="data-safety")

            # Create new untracked file and new untracked directory
            (tmppath / "new_file.py").write_text("# precious untracked content\n")
            new_dir = tmppath / "new_package"
            new_dir.mkdir()
            (new_dir / "module.py").write_text("def helper(): return 42\n")

            # Perform rollback
            rb = inspect_lifecycle.perform_rollback(tmppath, "gate-1-spec", topic="data-safety")
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

    def test_telemetry_sink_emission(self):
        """Emits structured JSON events to telemetry sink upon lifecycle events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)

            (tmppath / "app.py").write_text("pass\n")
            subprocess.run(["git", "add", "."], cwd=tmppath, check=True)
            subprocess.run(["git", "commit", "-m", "Init"], cwd=tmppath, check=True, capture_output=True)

            sink_file = tmppath / ".scratch" / "telemetry_events.jsonl"
            inspect_lifecycle.create_checkpoint(tmppath, "gate-1-spec", topic="metrics", telemetry_sink=str(sink_file))
            inspect_lifecycle.perform_rollback(tmppath, "gate-1-spec", topic="metrics", telemetry_sink=str(sink_file))

            self.assertTrue(sink_file.exists())
            lines = [json.loads(line) for line in sink_file.read_text().splitlines() if line.strip()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["event_type"], "checkpoint_created")
            self.assertEqual(lines[1]["event_type"], "rollback_executed")
            self.assertEqual(lines[0]["payload"]["topic"], "metrics")

    def test_ship_schema_conformance(self):
        """Verify load_ship_config default_config aligns with ship.schema.json structure."""
        schema_file = Path(__file__).resolve().parent.parent / "skills" / "ship" / "references" / "ship.schema.json"
        self.assertTrue(schema_file.exists())
        schema = json.loads(schema_file.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = inspect_lifecycle.load_ship_config(Path(tmpdir))

            # Validate top-level keys
            expected_gates = {"design", "spike", "implementation", "simplify", "audit", "delivery"}
            self.assertEqual(set(cfg["gates"].keys()), expected_gates)

            # Check implementation gate commands
            self.assertIn("test", cfg["gates"]["implementation"])
            self.assertIn("typecheck", cfg["gates"]["implementation"])
            self.assertIn("lint", cfg["gates"]["implementation"])

            # Check audit gate properties
            self.assertIn("base_branch", cfg["gates"]["audit"])
            self.assertIn("reviewers", cfg["gates"]["audit"])
            self.assertIn("max_iterations", cfg["gates"]["audit"])

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
                    "phase": "gate-2-impl",
                    "blockers": ["1 failing test in test_alpha.py"],
                })
            )
            # 2. Mutate change-beta
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "change-beta",
                lambda entry: entry.update({
                    "phase": "gate-3-audit",
                    "blockers": [],
                })
            )

            ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=False)
            self.assertIn("change-alpha", ledger["changes"])
            self.assertIn("change-beta", ledger["changes"])
            self.assertEqual(ledger["changes"]["change-alpha"]["phase"], "gate-2-impl")
            self.assertEqual(ledger["changes"]["change-alpha"]["blockers"], ["1 failing test in test_alpha.py"])
            self.assertEqual(ledger["changes"]["change-beta"]["phase"], "gate-3-audit")
            self.assertEqual(ledger["changes"]["change-beta"]["blockers"], [])
            self.assertEqual(ledger["active_change_id"], "change-beta")

    def test_ledger_monotonic_revision_counter(self):
        """Revision counter monotonically increments on each change mutation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            entry1 = inspect_lifecycle.mutate_change_state(
                tmppath, "topic-a", lambda e: e.update({"phase": "gate-1-design"})
            )
            self.assertEqual(entry1["revision_counter"], 1)

            entry2 = inspect_lifecycle.mutate_change_state(
                tmppath, "topic-a", lambda e: e.update({"phase": "gate-2-impl"})
            )
            self.assertEqual(entry2["revision_counter"], 2)

            entry3 = inspect_lifecycle.mutate_change_state(
                tmppath, "topic-a", lambda e: e["task_status"].update({"completed": 3})
            )
            self.assertEqual(entry3["revision_counter"], 3)

    def test_ledger_atomic_persistence(self):
        """save_ledger atomically creates .ship/state.json without temp file remnants."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            data = {"version": 1, "active_change_id": "test", "changes": {}}
            inspect_lifecycle.save_ledger(tmppath, data)

            state_file = tmppath / ".ship" / "state.json"
            self.assertTrue(state_file.exists())
            loaded = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(loaded["active_change_id"], "test")

            # Check no .tmp files remain
            tmp_files = list((tmppath / ".ship").glob("*.tmp"))
            self.assertEqual(len(tmp_files), 0)

    def test_ledger_self_healing_from_workspace(self):
        """Missing .ship/state.json is reconstructed deterministically from workspace artifacts."""
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

            # Ensure .ship does NOT exist
            self.assertFalse((tmppath / ".ship" / "state.json").exists())

            # Load ledger should trigger self-healing sync
            ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=True)
            self.assertTrue((tmppath / ".ship" / "state.json").exists())
            self.assertIn("billing", ledger["changes"])
            billing = ledger["changes"]["billing"]
            self.assertEqual(billing["phase"], "gate-2-impl")
            self.assertEqual(billing["task_status"]["total"], 2)
            self.assertEqual(billing["task_status"]["completed"], 1)
            self.assertEqual(billing["task_status"]["pending"], 1)
            self.assertEqual(billing["evidence"]["design"]["status"], "ACCEPTED")

    def test_git_notes_evidence_attachment_and_retrieval(self):
        """Structured validation evidence can be attached and retrieved via git notes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmppath, check=True)
            (tmppath / "code.py").write_text("print('hello')\n")
            subprocess.run(["git", "add", "code.py"], cwd=tmppath, check=True)
            commit_res = subprocess.run(
                ["git", "commit", "-m", "Initial"], cwd=tmppath, check=True, capture_output=True, text=True
            )
            head_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=tmppath, check=True, capture_output=True, text=True
            ).stdout.strip()

            # Attach audit evidence
            audit_data = {"verdict": "PASS", "reviewer": "judge", "findings_count": 0}
            oid = inspect_lifecycle.attach_git_note_evidence(tmppath, head_sha, "audit", audit_data)
            self.assertIsNotNone(oid)

            # Retrieve evidence
            notes = inspect_lifecycle.read_git_note_evidence(tmppath, head_sha)
            self.assertIn("audit", notes)
            self.assertEqual(notes["audit"]["verdict"], "PASS")

            # Attach additional test evidence to the same commit
            test_data = {"passed": True, "tests_run": 42}
            inspect_lifecycle.attach_git_note_evidence(tmppath, head_sha, "tests", test_data)

            # Both should coexist in the note
            updated_notes = inspect_lifecycle.read_git_note_evidence(tmppath, head_sha)
            self.assertIn("audit", updated_notes)
            self.assertIn("tests", updated_notes)
            self.assertEqual(updated_notes["tests"]["tests_run"], 42)

    def test_git_notes_sync_configuration(self):
        """configure_git_notes_sync adds safe tracking fetch refspec and preserves default branch push."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "git@github.com:example/repo.git"],
                cwd=tmppath,
                check=True,
            )

            res = inspect_lifecycle.configure_git_notes_sync(tmppath, remote="origin")
            self.assertTrue(res["configured"])
            self.assertEqual(res["fetch_refspec"], "refs/notes/*:refs/notes/origin/*")
            self.assertIsNone(res["push_refspec"])

            fetch_cfg = subprocess.run(
                ["git", "config", "--get-all", "remote.origin.fetch"],
                cwd=tmppath,
                capture_output=True,
                text=True,
            )
            self.assertIn("refs/notes/*:refs/notes/origin/*", fetch_cfg.stdout)
            self.assertNotIn("+refs/notes/*:refs/notes/*", fetch_cfg.stdout)

            push_cfg = subprocess.run(
                ["git", "config", "--get-all", "remote.origin.push"],
                cwd=tmppath,
                capture_output=True,
                text=True,
            )
            self.assertNotIn("refs/notes", push_cfg.stdout)

    def test_gate_trailers_generation(self):
        """Commit trailers are generated matching ship.json gates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "auth-v2",
                lambda entry: entry.update({
                    "phase": "gate-4-delivery",
                    "task_status": {"total": 3, "completed": 3, "pending": 0},
                    "evidence": {
                        "design": {"adr": "docs/adr/ADR-0002-auth.md", "status": "ACCEPTED"},
                        "spike": {"status": "PASSED", "verdict": "latency < 20ms"},
                        "implementation": {"status": "PASSED"},
                        "simplify": {"debt_count": 0},
                        "audit": {"verdict": "PASS", "reviewer": "judge"},
                        "delivery": {"status": "READY"},
                    }
                })
            )

            trailers = inspect_lifecycle.generate_gate_trailers(tmppath, change_id="auth-v2")
            trailer_text = "\n".join(trailers)

            self.assertIn("Ship-Change: auth-v2", trailer_text)
            self.assertIn("Ship-Design: ADR-0002-auth (ACCEPTED)", trailer_text)
            self.assertIn("Ship-Spike: PASSED (latency < 20ms)", trailer_text)
            self.assertIn("Ship-Implementation: PASSED (3/3 tasks)", trailer_text)
            self.assertIn("Ship-Simplify: DEBT-0", trailer_text)
            self.assertIn("Ship-Audit: PASS (by judge)", trailer_text)
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
            self.assertTrue((tmppath / ".ship" / "state.json").exists())

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

    def test_audit_report_path_recorded_in_ledger(self):
        """Verify audit report path is correctly recorded in state.json evidence."""
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
                "tests_passed": True,
            }))

            entry = inspect_lifecycle.record_audit_to_ledger(tmppath, report_file, change_id="payments")
            self.assertEqual(entry["evidence"]["audit"]["report_path"], ".scratch/review_report.json")
            self.assertEqual(entry["evidence"]["audit"]["verdict"], "PASS")

            # Also verify self-healing sync populates report_path
            synced = inspect_lifecycle.sync_ledger_from_workspace(tmppath, target_change_id="payments")
            self.assertEqual(synced["changes"]["payments"]["evidence"]["audit"]["report_path"], ".scratch/review_report.json")

    def test_concurrent_ledger_mutations_preserve_all_changes(self):
        """Concurrent mutations to distinct change IDs must not clobber each other (flock protection)."""
        import concurrent.futures
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            change_ids = [f"change-{i}" for i in range(10)]

            def worker(cid: str) -> None:
                def updater(entry: dict) -> None:
                    entry["phase"] = "gate-2-impl"
                    entry["task_status"]["total"] = 5
                inspect_lifecycle.mutate_change_state(tmppath, cid, updater)

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                list(executor.map(worker, change_ids))

            ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=False)
            for cid in change_ids:
                self.assertIn(cid, ledger["changes"], f"Change {cid} was clobbered by concurrent writes!")
                self.assertEqual(ledger["changes"][cid]["phase"], "gate-2-impl")

    def test_ledger_blockers_and_failed_tests_prevent_delivery_ready(self):
        """Even with all tasks complete and audit report present, failing tests in ledger block DELIVERY_READY."""
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
                "tests_passed": True,
            }))

            # Record a failed test in the ledger
            inspect_lifecycle.record_test_run_to_ledger(
                tmppath,
                {"passed": False, "failed_count": 1, "command": "pytest"},
                change_id="orders",
            )

            res = inspect_lifecycle.evaluate_repository(tmppath, target_change="orders")
            self.assertEqual(res["gate"], "GATE 2: IMPLEMENTATION (TDD + SIMPLIFY)")
            self.assertEqual(res["state_key"], "TDD_ACTIVE")
            self.assertIn("Blocked by", res["next_action"])
            self.assertNotEqual(res["state_key"], "DELIVERY_READY")

    def test_notes_fetch_and_push_preserves_branch_push_and_local_evidence(self):
        """Notes sync fetches into tracking namespace, reconciles divergence, and pushes notes without overwriting local evidence."""
        with tempfile.TemporaryDirectory() as tmp_remote, tempfile.TemporaryDirectory() as tmp_local:
            remote_path = Path(tmp_remote)
            local_path = Path(tmp_local)

            # 1. Bare remote
            subprocess.run(["git", "init", "--bare"], cwd=remote_path, check=True, capture_output=True)

            # 2. Local repo with commit
            subprocess.run(["git", "init"], cwd=local_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=local_path, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=local_path, check=True)
            (local_path / "README.md").write_text("hello\n")
            subprocess.run(["git", "add", "."], cwd=local_path, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=local_path, check=True)
            head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=local_path, text=True).strip()
            subprocess.run(["git", "remote", "add", "origin", str(remote_path)], cwd=local_path, check=True)
            subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=local_path, check=True)

            # 3. Attach local note
            inspect_lifecycle.attach_git_note_evidence(local_path, head_sha, "test_evidence", {"passed": True}, change_id="local_unpushed")

            # 4. Sync notes
            sync_res = inspect_lifecycle.sync_git_notes(local_path, remote="origin")
            self.assertEqual(sync_res["push"], "success")

            # 5. Verify local note still intact
            notes = inspect_lifecycle.read_git_note_evidence(local_path, head_sha, change_id="local_unpushed")
            self.assertIn("test_evidence", notes)
            self.assertTrue(notes["test_evidence"]["passed"])

            # 6. Verify default branch push is NOT overridden (remote.origin.push is not set)
            push_cfg = subprocess.run(
                ["git", "config", "--get-all", "remote.origin.push"],
                cwd=local_path,
                capture_output=True,
                text=True,
            )
            self.assertNotIn("refs/notes", push_cfg.stdout)

    def test_notes_evidence_namespaced_by_change_id(self):
        """Different changes attaching evidence to the same commit do not overwrite each other."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmppath, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmppath, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmppath, check=True)
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
                    "phase": "gate-2-impl",
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
            self.assertIn("Ship-Implementation: FAILED (4/4 tasks)", trailer_text)
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
            self.assertEqual(eval_res["gate"], "GATE 4: READY TO SHIP")
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
                "tests_passed": True,
                "coverage": 100,
                "questions": [],
                "routing_notes": "",
            }))

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
        """sync_ledger_from_workspace does not reset archived changes back to gate-1-design."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            pkg = tmppath / "openspec" / "changes" / "search"
            pkg.mkdir(parents=True)
            (pkg / "tasks.md").write_text("- [x] 1. Indexing\n")

            inspect_lifecycle.apply_and_archive_openspec(tmppath, "search", force=True)

            # Re-sync ledger
            synced = inspect_lifecycle.sync_ledger_from_workspace(tmppath)
            search_entry = synced["changes"]["search"]
            self.assertEqual(search_entry["phase"], "gate-4-delivery")
            self.assertEqual(search_entry["evidence"]["delivery"]["status"], "ARCHIVED")

    def test_rollback_clears_obsolete_audit_blockers(self):
        """Rolling back to gate-2-impl clears obsolete Audit blockers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            inspect_lifecycle.mutate_change_state(
                tmppath,
                "auth",
                lambda entry: entry.update({
                    "phase": "gate-3-audit",
                    "blockers": ["Audit: 2 unresolved CRITICAL/HIGH finding(s)", "Tests: 1 test(s) failing"],
                    "evidence": {
                        "audit": {"verdict": "FAIL"},
                        "implementation": {"status": "PASSED"},
                    }
                })
            )

            # Create mock checkpoint
            chk_dir = tmppath / ".scratch" / "checkpoints"
            chk_dir.mkdir(parents=True)
            (chk_dir / "auth_gate-2-impl.json").write_text(json.dumps({
                "gate": "gate-2-impl",
                "timestamp": "2026-09-13T00:00:00Z",
                "files": {},
            }))

            inspect_lifecycle.perform_rollback(tmppath, target_gate="gate-2-impl", change="auth")
            ledger = inspect_lifecycle.load_ledger(tmppath, auto_sync=False)
            auth_entry = ledger["changes"]["auth"]
            self.assertEqual(auth_entry["phase"], "gate-2-impl")
            self.assertNotIn("Audit: 2 unresolved CRITICAL/HIGH finding(s)", auth_entry["blockers"])
            self.assertIn("Tests: 1 test(s) failing", auth_entry["blockers"])


if __name__ == "__main__":
    unittest.main()




