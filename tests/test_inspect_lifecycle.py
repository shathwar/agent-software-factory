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
            self.assertIn("Run '/adversarial-design'", res["next_action"])

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
            self.assertEqual(res["gate"], "GATE 2: IMPLEMENTATION (TDD + PONYTAIL)")
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
                    "reviewer": "judge",
                    "status": "complete",
                    "verdict": "PASS",
                    "findings": [],
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
            self.assertEqual(res["gate"], "GATE 2: IMPLEMENTATION (TDD + PONYTAIL)")
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
                "verdict": "PASS",
                "snapshot": {"commit": head_commit},
                "test_evidence": {"exit_code": 0, "passed": True, "tests_run": 5},
                "judge_report": {
                    "reviewer": "judge",
                    "status": "complete",
                    "findings": [],
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
            validate_script = ROOT / "skills" / "adversarial-review" / "scripts" / "validate_report.py"
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


if __name__ == "__main__":
    unittest.main()
