"""
test_behavioral_eval_cases.py
=============================
Automated execution of the 12 Behavioral Evaluation Cases from tests/skill_evaluations.md.

Proves:
"When an agent uses this skill in each realistic acceptance scenario,
does it actually observe boundaries and behave as intended?"
"""

from __future__ import annotations

import os
import unittest

from tests.agent_harness.core import AgentRunner, RegressionSuite
from tests.agent_harness.scenarios_eval_cases import (
    TWELVE_BEHAVIORAL_SCENARIOS,
    SCENARIO_EC01,
    SCENARIO_EC02,
    SCENARIO_EC03,
    SCENARIO_EC04,
    SCENARIO_EC05,
    SCENARIO_EC06,
    SCENARIO_EC07,
    SCENARIO_EC08,
    SCENARIO_EC09,
    SCENARIO_EC10,
    SCENARIO_EC11,
    SCENARIO_EC12,
)


class TestTwelveBehavioralScenarios(unittest.TestCase):
    """
    Automated regression tests for the 12 behavioral evaluation cases
    documented in tests/skill_evaluations.md.
    """

    @classmethod
    def setUpClass(cls) -> None:
        mode = os.environ.get("AGENT_HARNESS_MODE", "stub")
        cls.runner = AgentRunner(mode=mode)

    def _run_scenario(self, scenario) -> None:
        suite = RegressionSuite([scenario], runner=self.runner)
        report = suite.run()
        result = report["results"][0]
        if not result.passed:
            self.fail(
                f"Scenario {scenario.id!r} FAILED:\n"
                + "\n".join(f"  ✗ {f}" for f in result.failures)
            )

    def test_01_clean_tree_review(self):
        """Case 1 (m-clean-review): Clean-tree review flags defect despite clean working tree."""
        self._run_scenario(SCENARIO_EC01)

    def test_02_pr_review_authorisation(self):
        """Case 2 (m-pr): PR review runs without calling external comment APIs or mutating source."""
        self._run_scenario(SCENARIO_EC02)

    def test_03_malformed_reviewer_output(self):
        """Case 3 (m-schema): Rejects finding missing fixability, records incomplete coverage."""
        self._run_scenario(SCENARIO_EC03)

    def test_04_unresolved_repair(self):
        """Case 4 (m-repair): Unresolved repair does not receive VERIFIED or APPROVE."""
        self._run_scenario(SCENARIO_EC04)

    def test_05_context_resumption(self):
        """Case 5 (m-context): Resume at 3/3 honors ceiling, executes no 4th repair batch."""
        self._run_scenario(SCENARIO_EC05)

    def test_06_postfix_regression(self):
        """Case 6 (m-regression): Post-fix regression on existing test halts immediately."""
        self._run_scenario(SCENARIO_EC06)

    def test_07_facts_vs_decisions_law(self):
        """Case 7 (m-facts): Facts discovered autonomously from Express/Redis configs, batches trade-offs."""
        self._run_scenario(SCENARIO_EC07)

    def test_08_ungrillable_question_spike(self):
        """Case 8 (m-spike): Empirical throughput question delegated to isolated spike in .scratch/."""
        self._run_scenario(SCENARIO_EC08)

    def test_09_red_state_verification(self):
        """Case 9 (m-red): Proves AssertionError failure receipt before writing implementation."""
        self._run_scenario(SCENARIO_EC09)

    def test_10_laziness_ladder_stdlib_first(self):
        """Case 10 (m-stdlib): Uses built-in structuredClone(), refuses external lodash package."""
        self._run_scenario(SCENARIO_EC10)

    def test_11_simplify_debt_syntax(self):
        """Case 11 (m-debt): Documents explicit debt marker with simplify:, Ceiling:, and Upgrade:."""
        self._run_scenario(SCENARIO_EC11)

    def test_12_ship_crash_recovery(self):
        """Case 12 (m-resume): Resumes at Task 2 in Red phase, preserves Task 1, no re-prompting."""
        self._run_scenario(SCENARIO_EC12)

    def test_13_ux_accessibility_check(self):
        """Case 13 (m-ux-source): Source markup inspected for accessibility attributes."""
        from tests.agent_harness.scenarios_eval_cases import SCENARIO_EC13
        self._run_scenario(SCENARIO_EC13)

    def test_14_evals_trace_failure_discovery(self):
        """Case 14 (m-evals-trace): Execution traces analyzed to isolate failure modes."""
        from tests.agent_harness.scenarios_eval_cases import SCENARIO_EC14
        self._run_scenario(SCENARIO_EC14)

    def test_all_behavioral_scenarios_pass_as_suite(self):
        """Run all behavioral scenarios as a unified batch suite."""
        suite = RegressionSuite(TWELVE_BEHAVIORAL_SCENARIOS, runner=self.runner)
        report = suite.run()
        self.assertTrue(
            report["passed"],
            f"Some behavioral scenarios failed:\n{report['summary']}",
        )
        self.assertEqual(report["total"], len(TWELVE_BEHAVIORAL_SCENARIOS))
        self.assertEqual(report["n_passed"], len(TWELVE_BEHAVIORAL_SCENARIOS))
        self.assertEqual(report["n_failed"], 0)


if __name__ == "__main__":
    unittest.main()
