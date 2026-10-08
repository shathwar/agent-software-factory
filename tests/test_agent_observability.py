"""
test_agent_observability.py
===========================
Tests for the Real-Agent Observability & Immutable Execution Trace Engine.

Verifies:
Agent
 ├─ tool calls
 ├─ file changes
 ├─ commands
 ├─ test results
 ├─ lifecycle transitions
 └─ timestamps/order

Proves:
"Test failed before production code changed" mechanically from the execution trace,
rather than trusting the agent's prose narrative.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ship.lifecycle.observability import (
    CausalTraceVerifier,
    ExecutionObserver,
)
from tests.agent_harness.core import (
    AgentRunner,
    RegressionSuite,
    Scenario,
    ScenarioFixture,
    check_red_green_cycle,
    check_test_failed_before_production_code_changed,
    check_trace_integrity,
)


class RealAgentObservabilityTests(unittest.TestCase):
    """Exhaustive tests for host-side execution observation and causal trace proofs."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_observes_tool_calls_with_arguments_and_timestamps(self):
        """Tool calls are recorded with arguments, timestamps, and monotonic sequence numbers."""
        with ExecutionObserver(self.root, run_id="run-tool-test", skill="review") as obs:
            c1 = obs.observe_tool_call("view_file", {"path": "calc.py"}, agent_id="agent-01")
            obs.observe_tool_result(c1.call_id, "view_file", result="def add(a, b): return a + b", duration_ms=12.5)

            c2 = obs.observe_tool_call("run_command", {"command": "pytest"}, agent_id="agent-01")
            obs.observe_tool_result(c2.call_id, "run_command", result="1 passed", duration_ms=45.0)

        trace = obs.get_trace()
        calls = trace.tool_calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].name, "view_file")
        self.assertEqual(calls[0].arguments, {"path": "calc.py"})
        self.assertEqual(calls[0].seq, 0)
        self.assertEqual(calls[1].name, "run_command")
        self.assertEqual(calls[1].seq, 2)
        self.assertTrue(calls[0].timestamp <= calls[1].timestamp)

    def test_observes_file_changes_with_hashes_diffs_and_classification(self):
        """File modifications on disk are snapshotted with SHA-256 before/after and test/prod classification."""
        with ExecutionObserver(self.root, run_id="run-file-test", skill="tdd") as obs:
            # 1. Create a test file
            test_file = self.root / "tests" / "test_calc.py"
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text("def test_add(): assert add(1, 2) == 3\n", encoding="utf-8")
            changes_1 = obs.snapshot_file_changes()

            self.assertEqual(len(changes_1), 1)
            self.assertEqual(changes_1[0].path, "tests/test_calc.py")
            self.assertEqual(changes_1[0].change_type, "created")
            self.assertTrue(changes_1[0].is_test)
            self.assertFalse(changes_1[0].is_production)

            # 2. Create production code file
            prod_file = self.root / "src" / "calc.py"
            prod_file.parent.mkdir(parents=True, exist_ok=True)
            prod_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")
            changes_2 = obs.snapshot_file_changes()

            self.assertEqual(len(changes_2), 1)
            self.assertEqual(changes_2[0].path, "src/calc.py")
            self.assertFalse(changes_2[0].is_test)
            self.assertTrue(changes_2[0].is_production)
            self.assertIn("+def add(a, b):", changes_2[0].diff)

    def test_observes_command_execution_and_parses_test_results(self):
        """Commands are recorded with exit codes and parsed test metrics (pytest, unittest)."""
        with ExecutionObserver(self.root, run_id="run-cmd-test", skill="tdd") as obs:
            # Simulate a failing pytest run
            obs.observe_command(
                command="pytest tests/test_calc.py",
                exit_code=1,
                stdout="FAILED tests/test_calc.py::test_add - AssertionError\n1 failed in 0.05s",
                stderr="",
                duration_ms=65.0,
            )

            # Simulate a passing pytest run
            obs.observe_command(
                command="pytest tests/test_calc.py",
                exit_code=0,
                stdout="1 passed in 0.03s",
                stderr="",
                duration_ms=40.0,
            )

        trace = obs.get_trace()
        cmds = trace.commands()
        self.assertEqual(len(cmds), 2)
        self.assertTrue(cmds[0].is_test_run)
        self.assertEqual(cmds[0].exit_code, 1)

        test_runs = trace.test_results()
        self.assertEqual(len(test_runs), 2)
        self.assertEqual(test_runs[0].framework, "pytest")
        self.assertEqual(test_runs[0].failed_count, 1)
        self.assertFalse(test_runs[0].passed)
        self.assertEqual(test_runs[1].passed_count, 1)
        self.assertTrue(test_runs[1].passed)

    def test_observes_lifecycle_transitions(self):
        """Lifecycle transitions are chronologically recorded in the trace."""
        with ExecutionObserver(self.root, run_id="run-life-test", skill="ship") as obs:
            obs.observe_lifecycle_transition("design", "SPEC_CONFIRMED", "Design approved by user")
            obs.observe_lifecycle_transition("tdd", "TDD_ACTIVE", "Beginning task 1 implementation")

        trace = obs.get_trace()
        trans = trace.lifecycle_transitions()
        self.assertEqual(len(trans), 2)
        self.assertEqual(trans[0].skill, "design")
        self.assertEqual(trans[0].phase, "SPEC_CONFIRMED")
        self.assertEqual(trans[1].skill, "tdd")
        self.assertEqual(trans[1].phase, "TDD_ACTIVE")

    def test_cryptographic_hash_chain_verifies_immutability(self):
        """Trace verifies SHA-256 hash chaining; tampering breaks verification."""
        with ExecutionObserver(self.root, run_id="run-hash-test", skill="review") as obs:
            obs.observe_tool_call("tool_a", {"x": 1})
            obs.observe_tool_call("tool_b", {"y": 2})
            obs.observe_tool_call("tool_c", {"z": 3})

        trace = obs.get_trace()
        valid, msg = trace.verify_integrity()
        self.assertTrue(valid, msg)

        # Tampering with an event payload breaks the hash chain
        trace.events[1].payload["y"] = 999  # Tamper!
        valid_after, error_msg = trace.verify_integrity()
        self.assertFalse(valid_after)
        self.assertIn("Tampered payload", error_msg)

    # ------------------------------------------------------------------ #
    # Causal Invariant Proof Tests (Mechanically Proving Iron Law)        #
    # ------------------------------------------------------------------ #

    def test_causal_proof_test_failed_before_production_code_changed(self):
        """Mechanical proof: test failed before production code changed passes when order is correct."""
        with ExecutionObserver(self.root, run_id="run-causal-pass", skill="tdd") as obs:
            # Step 1: Write test file
            (self.root / "tests").mkdir(parents=True, exist_ok=True)
            (self.root / "tests" / "test_math.py").write_text("def test_inc(): assert inc(3) == 4\n")
            obs.snapshot_file_changes()

            # Step 2: Run test -> FAILS (Red Phase proven)
            obs.observe_command(
                command="pytest tests/test_math.py",
                exit_code=1,
                stdout="FAILED tests/test_math.py::test_inc - NameError: inc is not defined\n1 failed in 0.02s",
            )

            # Step 3: Edit production code AFTER the failing test
            (self.root / "src").mkdir(parents=True, exist_ok=True)
            (self.root / "src" / "math_utils.py").write_text("def inc(n): return n + 1\n")
            obs.snapshot_file_changes()

            # Step 4: Run test -> PASSES (Green Phase)
            obs.observe_command(
                command="pytest tests/test_math.py",
                exit_code=0,
                stdout="1 passed in 0.02s",
            )

        verifier = CausalTraceVerifier(obs.get_trace())
        proven, reason, evidence = verifier.prove_test_failed_before_production_code_changed()
        self.assertTrue(proven, reason)
        self.assertIn("Proved mechanically", reason)
        self.assertGreater(evidence["seq_delta"], 0)

        # Also prove complete Red-Green cycle
        rg_proven, rg_reason, _ = verifier.prove_red_green_cycle()
        self.assertTrue(rg_proven, rg_reason)

    def test_causal_proof_rejects_narrative_when_code_changed_before_test(self):
        """CRITICAL: Rejects agent narrative when production code was written before test failed."""
        with ExecutionObserver(self.root, run_id="run-causal-fail", skill="tdd") as obs:
            # Agent cheat: writes production code FIRST
            (self.root / "src").mkdir(parents=True, exist_ok=True)
            (self.root / "src" / "math_utils.py").write_text("def inc(n): return n + 1\n")
            obs.snapshot_file_changes()

            # Agent then writes test
            (self.root / "tests").mkdir(parents=True, exist_ok=True)
            (self.root / "tests" / "test_math.py").write_text("def test_inc(): assert inc(3) == 4\n")
            obs.snapshot_file_changes()

            # Agent runs test (passes immediately)
            obs.observe_command(
                command="pytest tests/test_math.py",
                exit_code=0,
                stdout="1 passed in 0.02s",
            )

        verifier = CausalTraceVerifier(obs.get_trace())
        proven, reason, _ = verifier.prove_test_failed_before_production_code_changed()

        # Must reject: Iron Law violation!
        self.assertFalse(proven)
        self.assertIn("Iron Law violation", reason)
        self.assertIn("NO failing test execution was ever recorded", reason)

    def test_causal_proof_no_file_changes_outside_boundary(self):
        """Verifies file change containment and catches mutations to unexpected files."""
        with ExecutionObserver(self.root, run_id="run-containment", skill="review") as obs:
            (self.root / "src").mkdir(parents=True, exist_ok=True)
            (self.root / "src" / "target.py").write_text("fixed\n")
            obs.snapshot_file_changes()

        verifier = CausalTraceVerifier(obs.get_trace())
        # Allowed target passes
        ok, _ = verifier.prove_no_file_changes_outside([r"src/target\.py"])
        self.assertTrue(ok)

        # Disallowed target fails
        ok_fail, reason = verifier.prove_no_file_changes_outside([r"src/other\.py"])
        self.assertFalse(ok_fail)
        self.assertIn("Containment violation", reason)

    def test_causal_proof_detects_test_weakening_in_diffs(self):
        """Detects skip decorators inserted into test files."""
        with ExecutionObserver(self.root, run_id="run-weakening", skill="debug") as obs:
            (self.root / "tests").mkdir(parents=True, exist_ok=True)
            test_file = self.root / "tests" / "test_flaky.py"
            test_file.write_text("def test_flaky(): assert True\n")
            obs.snapshot_file_changes()

            # Weakening edit: insert @pytest.mark.skip
            test_file.write_text("@pytest.mark.skip(reason='flaky')\ndef test_flaky(): assert True\n")
            obs.snapshot_file_changes()

        verifier = CausalTraceVerifier(obs.get_trace())
        proven, reason = verifier.prove_no_test_weakening()
        self.assertFalse(proven)
        self.assertIn("inserted skip decorator", reason)

    # ------------------------------------------------------------------ #
    # Regression Harness Integration with Observable Actions             #
    # ------------------------------------------------------------------ #

    def test_scenario_with_observable_actions_reports_behavior_verified(self):
        """A Scenario with observable actions produces an execution trace and reports behavior_verified=True."""
        def _mock_observable_actions(observer: ExecutionObserver, workdir: Path):
            # 1. Red test failure
            observer.observe_command("pytest tests/", exit_code=1, stdout="1 failed in 0.05s")
            # 2. Production file edit
            prod = workdir / "service.py"
            prod.write_text("def run(): return 'ok'\n")
            observer.snapshot_file_changes()
            # 3. Green test pass
            observer.observe_command("pytest tests/", exit_code=0, stdout="1 passed in 0.02s")

        fixture = ScenarioFixture(
            files={"tests/test_service.py": "def test_service(): pass\n"}
        )

        scenario = Scenario(
            skill="tdd",
            id="obs-scenario-tdd-proof",
            description="Real observable actions prove TDD Red-Green invariant mechanically",
            prompt="Implement service with TDD",
            fixture=fixture,
            stub_response="I implemented the service using TDD.",
            observable_actions=_mock_observable_actions,
            checks=[
                check_test_failed_before_production_code_changed(),
                check_red_green_cycle(),
                check_trace_integrity(),
            ],
        )

        suite = RegressionSuite([scenario], runner=AgentRunner(mode="stub"))
        report = suite.run()

        self.assertTrue(report["passed"])
        self.assertEqual(report["assessment_kind"], "observable_execution_trace")
        self.assertTrue(report["behavior_verified"])
        self.assertIn("execution trace verified", report["summary"])


if __name__ == "__main__":
    unittest.main()
