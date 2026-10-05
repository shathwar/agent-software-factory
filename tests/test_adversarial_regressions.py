"""Behavioral reproductions from the October repository review."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ship.lifecycle.capabilities import CapabilityManager
from ship.lifecycle.coordination import CoordinationManager
from ship.lifecycle.convergence import ConvergenceController, evaluate_convergence
from ship.lifecycle.evidence import parse_review_report_file
from ship.lifecycle.events import EventLogger, EventReplayer
from ship.lifecycle.gates import validate_delivery_readiness
from ship.lifecycle.ledger import FileLedgerStore, create_empty_change_entry
from ship.lifecycle.provenance import ProvenanceManager
from ship.lifecycle.resources import ChangeBudget, ResourceGovernor
from ship.lifecycle.verification import verify_finding_grounding, verify_review_grounding
from ship.mcp.server import run_stdio_server
from ship.mcp.tools import dispatch_tool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/evals/scripts"))
sys.path.insert(0, str(ROOT / "skills/debug/scripts"))
import score_calibration
import verify_fix


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.change = "review-test"
        FileLedgerStore.save(self.root, {
            "version": 1, "active_change_id": self.change,
            "changes": {self.change: create_empty_change_entry(self.change)},
        })


class LeaseRegressions(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.manager = CoordinationManager(self.root, self.change)

    def test_released_owner_cannot_write_after_reassignment(self):
        caps = CapabilityManager(self.root)
        for owner, task in (("a", "1"), ("b", "2")):
            ProvenanceManager(self.root).register_identity(owner, change_id=self.change)
            caps.grant_capability(owner, "WRITE", "src/a.py", task_id=task, change_id=self.change)
        first = self.manager.claim_task("1", "a", files=["src/a.py"]).lease
        self.manager.release_task("1", first.lease_token)
        second = self.manager.claim_task("2", "b", files=["src/a.py"]).lease
        old = caps.evaluate_access("a", "WRITE", "src/a.py", task_id="1", lease_token=first.lease_token, change_id=self.change)
        new = caps.evaluate_access("b", "WRITE", "src/a.py", task_id="2", lease_token=second.lease_token, change_id=self.change)
        self.assertFalse(old.allowed)
        self.assertTrue(new.allowed)

    def test_renewal_cannot_expand_into_another_workers_files(self):
        self.manager.claim_task("1", "a", files=["src/a.py"])
        self.manager.claim_task("2", "b", files=["src/b.py"])
        result = self.manager.claim_task("1", "a", files=["src/b.py"])
        self.assertFalse(result.success)
        self.assertEqual(result.conflict_type, "FILE_OVERLAP")
        self.assertEqual(self.manager.list_leases(active_only=True)[0].target_files, ["src/a.py"])

    def test_heartbeat_cannot_resurrect_released_lease(self):
        first = self.manager.claim_task("1", "a", files=["src/a.py"]).lease
        self.manager.release_task("1", first.lease_token)
        self.manager.claim_task("2", "b", files=["src/a.py"])
        self.assertFalse(self.manager.heartbeat_lease("1", first.lease_token).success)
        self.assertEqual(len(self.manager.list_leases(active_only=True)), 1)

    def test_heartbeat_cannot_resurrect_timed_out_lease(self):
        first = self.manager.claim_task("1", "a").lease
        FileLedgerStore.mutate_change(self.root, self.change, lambda e: e["coordination"]["leases"]["1"].update(expires_at="2000-01-01T00:00:00Z"))
        self.assertFalse(self.manager.heartbeat_lease("1", first.lease_token).success)

    def test_retried_completion_counts_once(self):
        FileLedgerStore.mutate_change(self.root, self.change, lambda e: e.update(task_status={"total": 2, "completed": 0, "pending": 2}))
        lease = self.manager.claim_task("1", "a").lease
        for _ in range(2):
            self.assertTrue(self.manager.release_task("1", lease.lease_token, completed=True).success)
        change = FileLedgerStore.load(self.root)["changes"][self.change]
        self.assertEqual(change["task_status"], {"total": 2, "completed": 1, "pending": 1})

    def test_real_claim_is_consistent_with_event_replay(self):
        self.manager.claim_task("1", "a", files=["src/a.py"])
        matches, message, mismatches = EventReplayer.verify_state_matches_events(self.root, self.change)
        self.assertTrue(matches, (message, mismatches))


class GroundingRegressions(WorkspaceTest):
    def test_ungrounded_review_blocks_ledger_and_trailers(self):
        from test_archive_recovery import ArchiveRecoveryTests
        from ship.lifecycle.engine import LifecycleEngine
        from ship.lifecycle.trailers import CommitTrailerGenerator
        ArchiveRecoveryTests().workspace(self.root)
        path = self.root / ".agentflow/reviews/alpha/review_report.json"
        report = json.loads(path.read_text())
        report["findings"] = [{"id": "FINDING-001", "severity": "MEDIUM", "category": "Correctness", "file": "missing.py", "line": "L1", "title": "Missing source finding", "problem": "Missing source.", "evidence": "invented()", "impact": "Wrong result.", "recommendation": "Fix the result.", "confidence": 1.0, "fixability": "autonomous"}]
        path.write_text(json.dumps(report))
        entry = FileLedgerStore.record_review(self.root, path, change_id="alpha")
        with self.subTest(surface="ledger"):
            self.assertNotEqual(entry["phase"], "delivery")
            self.assertEqual(entry["evidence"]["review"]["findings"], report["findings"])
        with self.subTest(surface="trailers"):
            self.assertIn("Ship-Delivery: BLOCKED", CommitTrailerGenerator.generate(self.root, change_id="alpha"))
        self.assertEqual(LifecycleEngine().evaluate_repository(self.root, target_change="alpha")["state_key"], "VERIFICATION_FAILED")
        LifecycleEngine().sync_ledger(self.root, "alpha")
        synced = FileLedgerStore.load(self.root)["changes"]["alpha"]
        self.assertNotEqual(synced["phase"], "delivery")
        self.assertEqual(synced["evidence"]["review"]["findings"], report["findings"])

    def test_fabricated_remainder_and_blank_window_are_rejected(self):
        (self.root / "sample.py").write_text("import os\n\nanswer = 42\n")
        for line, evidence in (("L2", "invented()"), ("L1", "import os\ninvented()")):
            with self.subTest(line=line):
                self.assertFalse(verify_finding_grounding({"file": "sample.py", "line": line, "evidence": evidence}, self.root)[0])

    def test_parsed_review_keeps_findings_for_delivery_grounding(self):
        finding = {"id": "FINDING-001", "severity": "MEDIUM", "category": "Correctness", "file": "missing.py", "line": "L1", "title": "A reproduced missing source finding", "problem": "Missing source.", "evidence": "invented()", "impact": "Wrong result.", "recommendation": "Fix the result.", "confidence": 1.0, "fixability": "autonomous"}
        judge = {"reviewer": "judge", "status": "complete", "findings": [finding], "coverage": ["Source"], "questions": [], "routing_notes": []}
        for envelope in (False, True):
            with self.subTest(envelope=envelope):
                report = ({"judge_report": judge} if envelope else dict(judge))
                report.update(verdict="PASS", change=self.change, test_evidence={"passed": True, "tests_run": 1, "exit_code": 0})
                path = self.root / "review.json"
                path.write_text(json.dumps(report))
                parsed = parse_review_report_file(path, self.root)
                self.assertTrue(parsed["judge_report_valid"])
                self.assertEqual(verify_review_grounding(parsed, self.root).verdict, "NOT_VERIFIED")
                state = validate_delivery_readiness(parsed, {"change": self.change, "has_tasks": True, "total_tasks": 1, "completed_tasks": 1, "pending_tasks": 0}, {"is_git": False}, {"change_id": self.change, "verification": {"execution": {"verdict": "VERIFIED", "metadata": {"tests_run": 1, "exit_code": 0, "failed_count": 0}}}}, repo_root=self.root)
                self.assertNotEqual(state[1], "DELIVERY_READY")


class MCPRegressions(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.env = patch.dict(os.environ, {"AGENTFLOW_MCP_ALLOW_MUTATIONS": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        ProvenanceManager(self.root).register_identity("worker", role="MAKER", change_id=self.change)

    def test_network_read_cannot_authorize_shell_execution(self):
        CapabilityManager(self.root).grant_capability("worker", "NETWORK_READ", "https://example.com/*", change_id=self.change)
        with self.assertRaises(PermissionError):
            dispatch_tool("ship_spike_run", {"command": "touch executed", "iterations": 1, "path": str(self.root), "agent_id": "worker", "operation": "NETWORK_READ", "target": "https://example.com/", "change": self.change})
        self.assertFalse((self.root / "executed").exists())

    def test_execute_target_must_match_actual_command(self):
        CapabilityManager(self.root).grant_capability("worker", "EXECUTE", "echo safe", change_id=self.change)
        with self.assertRaises(PermissionError):
            dispatch_tool("ship_spike_run", {"command": "touch executed", "iterations": 1, "path": str(self.root), "agent_id": "worker", "operation": "EXECUTE", "target": "echo safe", "change": self.change})
        self.assertFalse((self.root / "executed").exists())

    def test_authorized_benchmark_returns_serializable_metrics(self):
        CapabilityManager(self.root).grant_capability("worker", "EXECUTE", "echo safe", change_id=self.change)
        result = dispatch_tool("ship_spike_run", {"command": "echo safe", "iterations": 1, "path": str(self.root), "agent_id": "worker", "operation": "EXECUTE", "target": "echo safe", "change": self.change})
        self.assertEqual(result["summary"]["successful_runs"], 1)
        self.assertIsInstance(result["table"], str)
        json.dumps(result)

    def test_malformed_messages_do_not_prevent_later_ping(self):
        messages = [[], {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": ["bad"]}, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "ship_status", "arguments": ["bad"]}}, {"jsonrpc": "2.0", "id": 3, "method": "ping"}]
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO("\n".join(map(json.dumps, messages)))), patch("sys.stdout", output), patch("sys.stderr", io.StringIO()):
            self.assertEqual(run_stdio_server(), 0)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r["error"]["code"] for r in responses[:-1]], [-32600, -32602, -32602])
        self.assertEqual(responses[-1], {"jsonrpc": "2.0", "id": 3, "result": {}})


class ToolRegressions(WorkspaceTest):
    def test_blank_csv_columns_fall_back_without_losing_false_labels(self):
        path = self.root / "labels.csv"
        path.write_text("human,ground_truth,evaluator,prediction\n,Fail,,Pass\nPass,,Pass,\n")
        pairs = score_calibration.load_pairs(path)
        self.assertEqual(pairs, [("Fail", "Pass"), ("Pass", "Pass")])
        self.assertEqual(score_calibration.compute_metrics(pairs)["accuracy"], 0.5)

    def test_hook_preserves_wrapped_deletion_and_database_guards(self):
        hook = ROOT / "templates/ci/safety/block-destructive.sh"
        for command in ("sudo rm -rf /var/data", "command rm -rf /var/data", "db.users.drop()"):
            with self.subTest(command=command):
                result = subprocess.run(["bash", str(hook)], input=command, text=True, capture_output=True, cwd=self.root, env={**os.environ, "AGT_VELOCITY_LIMITER_DISABLED": "1"})
                self.assertEqual(result.returncode, 2, result.stdout)

    def test_calibration_default_report_and_false_labels(self):
        records = [{"human": True, "evaluator": True}, {"human": False, "evaluator": True}, {"human": 0, "evaluator": 0}]
        for suffix in (".json", ".jsonl"):
            path = self.root / ("labels" + suffix)
            path.write_text(json.dumps(records) if suffix == ".json" else "\n".join(map(json.dumps, records)))
            pairs = score_calibration.load_pairs(path)
            self.assertEqual(pairs, [("Pass", "Pass"), ("Fail", "Pass"), ("Fail", "Fail")])
        report = score_calibration.format_report(score_calibration.evaluate_calibration([("Pass", "Fail"), ("Fail", "Fail")]))
        self.assertIn("1 (FN", report)

    def test_calibration_default_markdown_command(self):
        path = self.root / "labels.json"
        path.write_text('[{"human": "Pass", "evaluator": "Fail"}]')
        with patch("sys.stdout", io.StringIO()) as output:
            self.assertEqual(score_calibration.main(["--input", str(path)]), 0)
        self.assertIn("1 (FN", output.getvalue())

    def test_bugfix_audit_rejects_non_git_workspace(self):
        with self.assertRaises(RuntimeError):
            verify_fix.get_git_diff(self.root)
        with patch("sys.stderr", io.StringIO()):
            self.assertEqual(verify_fix.main(["--path", str(self.root), "--strict"]), 1)

    def test_hook_checks_quoted_and_traversing_operands(self):
        hook = ROOT / "templates/ci/safety/block-destructive.sh"
        commands = ['rm -rf "/var/data"', 'cat ".env"', 'curl "http://169.254.169.254/latest/meta-data"', "rm -rf build/../../src", "rm -rf build/../src", "rm -rf build/link/"]
        (self.root / "build").mkdir()
        (self.root / "src").mkdir()
        (self.root / "build/link").symlink_to(self.root / "src", target_is_directory=True)
        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run(["bash", str(hook)], input=json.dumps({"tool_input": {"command": command}}), cwd=self.root, text=True, capture_output=True, env={**os.environ, "AGT_VELOCITY_LIMITER_DISABLED": "1"})
                self.assertEqual(result.returncode, 2, result.stdout)


class BudgetRegressions(WorkspaceTest):
    def test_tiny_costs_accumulate_in_ledger_and_replay(self):
        governor = ResourceGovernor(self.root)
        governor.set_budget(self.change, ChangeBudget(max_dollars=0.0003))
        for _ in range(10):
            status = governor.record_consumption(self.change, dollars=0.00004)
        self.assertAlmostEqual(status.usage.dollars, 0.0004, places=10)
        self.assertTrue(status.is_exceeded)
        replay = EventReplayer.replay(EventLogger(self.root).query(change_id=self.change), target_change=self.change)
        self.assertAlmostEqual(replay["changes"][self.change]["budget"]["consumed"]["dollars"], 0.0004, places=10)

    def test_cost_ceiling_uses_unrounded_usage(self):
        status = ResourceGovernor(self.root).evaluate(self.change, change_entry={"budget": {"consumed": {"dollars": 0.00004}}}, config={"budget": {"max_dollars": 0.00003}})
        self.assertTrue(status.is_exceeded)

    def test_zero_resource_limits_are_enforced(self):
        governor = ResourceGovernor(self.root)
        for metric in ("tokens", "model_calls", "time_seconds", "dollars", "tool_executions", "network_operations"):
            with self.subTest(metric=metric):
                status = governor.evaluate(self.change, change_entry={"budget": {"consumed": {metric: 1}}}, config={"budget": {"max_" + metric: 0}})
                self.assertTrue(status.is_exceeded)
        change = {"change_id": self.change, "turns": [], "budget": {"consumed": {"tokens": 1}}}
        self.assertTrue(evaluate_convergence(change, {"budget": {"max_tokens": 0}}).is_halted)

    def test_controller_keeps_nondefault_resource_limits(self):
        change = {"change_id": self.change, "turns": [], "budget": {"consumed": {"tokens": 2}}, "verification": {"execution": {"verdict": "VERIFIED"}}}
        controller = ConvergenceController({"budget": {"max_tokens": 1}})
        self.assertFalse(controller.certify_convergence(change)[0])

    def test_unlimited_limits_survive_persistence(self):
        governor = ResourceGovernor(self.root)
        fields = ("max_tokens", "max_model_calls", "max_turns", "max_time_seconds", "max_dollars", "max_tool_executions", "max_network_operations")
        governor.set_budget(self.change, ChangeBudget(**dict.fromkeys(fields)))
        loaded = governor.get_budget(self.change)
        for field in fields:
            self.assertIsNone(getattr(loaded, field), field)


if __name__ == "__main__":
    unittest.main()
