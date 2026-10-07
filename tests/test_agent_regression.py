"""
test_agent_regression.py
========================
**The real agent regression harness.** Proves "when an agent uses this skill,
does it actually behave as intended?" — not "does the validator script work?"

Architecture
------------
- In CI (default):          AGENT_HARNESS_MODE=stub  → fast, no LLM calls
- With LLM key (nightly):   AGENT_HARNESS_MODE=anthropic → real Anthropic API
- Full live integration:    AGENT_HARNESS_MODE=live → agy CLI

Test structure
--------------
Each skill has a dedicated TestCase subclass.  Every scenario maps to a single
``subTest``, so pytest reports granular pass/fail per scenario.

Release gate
------------
The full suite IS the release gate.  It is registered in pytest.ini_options as
a required path so it cannot be silently excluded from CI.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.agent_harness.core import AgentRunner, RegressionSuite
from tests.agent_harness.scenarios_debug import DEBUG_SCENARIOS
from tests.agent_harness.scenarios_design import DESIGN_SCENARIOS
from tests.agent_harness.scenarios_review import REVIEW_SCENARIOS
from tests.agent_harness.scenarios_tdd import TDD_SCENARIOS


# ---------------------------------------------------------------------------
# Shared runner – controlled by AGENT_HARNESS_MODE environment variable
# ---------------------------------------------------------------------------

def _make_runner() -> AgentRunner:
    mode = os.environ.get("AGENT_HARNESS_MODE", "stub")
    return AgentRunner(mode=mode)


# ---------------------------------------------------------------------------
# Review skill regression suite
# ---------------------------------------------------------------------------

class TestReviewSkillRegression(unittest.TestCase):
    """
    Asserts that the /review skill behaves correctly across 12 representative
    scenarios.  Every check corresponds to a hard constraint or explicit
    behavioural guarantee from the SKILL.md.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _make_runner()

    def _run_scenario(self, scenario_id: str) -> None:
        scenario = next(s for s in REVIEW_SCENARIOS if s.id == scenario_id)
        suite = RegressionSuite([scenario], runner=self.runner)
        report = suite.run()
        result = report["results"][0]
        if not result.passed:
            self.fail(
                f"Scenario {scenario_id!r} FAILED:\n"
                + "\n".join(f"  ✗ {f}" for f in result.failures)
            )

    def test_R01_clean_repo_finds_meaningful_defect(self):
        """A repo with a real division-by-zero defect must be flagged with evidence."""
        self._run_scenario("review-R01-clean-repo-finds-defect")

    def test_R02_genuinely_clean_code_reports_clean(self):
        """Genuinely clean code must yield READY TO DEPLOY, not manufactured findings."""
        self._run_scenario("review-R02-clean-code-reports-clean")

    def test_R03_missing_evidence_refused_by_judge(self):
        """A finding without source evidence must be rejected by the Judge, not returned."""
        self._run_scenario("review-R03-missing-evidence-refused")

    def test_R04_stale_phantom_evidence_rejected(self):
        """A finding citing a non-existent file must be BLOCKED by the Judge."""
        self._run_scenario("review-R04-stale-evidence-rejected")

    def test_R05_large_diff_scoped_across_all_stages(self):
        """Large diff (10 files) must traverse all 10 scorecard stages."""
        self._run_scenario("review-R05-large-diff-scoped")

    def test_R06_security_issue_escalated(self):
        """SQL injection must be CRITICAL with HIGH RISK BLOCKED verdict."""
        self._run_scenario("review-R06-security-issue-escalated")

    def test_R07_repair_no_silent_mutation(self):
        """In review-loop mode the agent must not silently mutate unrelated files."""
        self._run_scenario("review-R07-repair-no-silent-mutation")

    def test_R08_race_condition_identified(self):
        """Non-atomic read-modify-write on shared state must be flagged."""
        self._run_scenario("review-R08-race-condition-identified")

    def test_R09_n_plus_1_query_flagged(self):
        """N+1 query pattern inside a loop must be flagged as a Performance defect."""
        self._run_scenario("review-R09-n-plus-1-query-flagged")

    def test_R10_no_conversational_filler(self):
        """Agent must never start with 'Certainly', 'Of course', etc."""
        self._run_scenario("review-R10-no-conversational-filler")

    def test_R11_schema_compliance_all_12_fields(self):
        """Every finding must contain all 12 required schema fields."""
        self._run_scenario("review-R11-schema-compliance")

    def test_R12_requires_human_triggers_decision_round(self):
        """A requires-human finding must trigger a batched Decision Round."""
        self._run_scenario("review-R12-requires-human-decision-round")


# ---------------------------------------------------------------------------
# Debug skill regression suite
# ---------------------------------------------------------------------------

class TestDebugSkillRegression(unittest.TestCase):
    """
    Asserts that the /debug skill behaves correctly across 10 representative
    scenarios.  Every check corresponds to a hard constraint from SKILL.md.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _make_runner()

    def _run_scenario(self, scenario_id: str) -> None:
        scenario = next(s for s in DEBUG_SCENARIOS if s.id == scenario_id)
        suite = RegressionSuite([scenario], runner=self.runner)
        report = suite.run()
        result = report["results"][0]
        if not result.passed:
            self.fail(
                f"Scenario {scenario_id!r} FAILED:\n"
                + "\n".join(f"  ✗ {f}" for f in result.failures)
            )

    def test_D01_root_cause_not_crash_site(self):
        """Stack trace: root cause must be traced backward to origin, not crash site."""
        self._run_scenario("debug-D01-root-cause-not-crash-site")

    def test_D02_refuses_symptom_masking(self):
        """Agent must refuse null guard at crash site; must fix at origin instead."""
        self._run_scenario("debug-D02-refuses-symptom-masking")

    def test_D03_reproduction_mandate(self):
        """Agent must write a failing test before any production code edit."""
        self._run_scenario("debug-D03-reproduction-mandate")

    def test_D04_red_receipt_required(self):
        """Agent must paste raw terminal failure snippet proving Red state."""
        self._run_scenario("debug-D04-red-receipt-required")

    def test_D05_test_weakening_rejected(self):
        """Agent must refuse @pytest.mark.skip; must fix production code instead."""
        self._run_scenario("debug-D05-test-weakening-rejected")

    def test_D06_two_strike_rethink(self):
        """After 2 failed hypotheses, agent must stop and re-read from entry point."""
        self._run_scenario("debug-D06-two-strike-rethink")

    def test_D07_three_strike_circuit_breaker(self):
        """After 3 failed fixes each breaking subsystems, agent must halt."""
        self._run_scenario("debug-D07-three-strike-circuit-breaker")

    def test_D08_surgical_diff(self):
        """Fix must be minimal: only root-cause lines changed."""
        self._run_scenario("debug-D08-surgical-diff")

    def test_D09_nondeterministic_boundary_logging(self):
        """Heisenbug must use stress scripts / boundary logging approach."""
        self._run_scenario("debug-D09-nondeterministic-boundary-logging")

    def test_D10_no_conversational_filler(self):
        """Agent must open with investigation, not a greeting."""
        self._run_scenario("debug-D10-no-conversational-filler")


# ---------------------------------------------------------------------------
# TDD skill regression suite
# ---------------------------------------------------------------------------

class TestTDDSkillRegression(unittest.TestCase):
    """
    Asserts that the /tdd skill behaves correctly across 10 representative
    scenarios.  Every check corresponds to a hard constraint from SKILL.md.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _make_runner()

    def _run_scenario(self, scenario_id: str) -> None:
        scenario = next(s for s in TDD_SCENARIOS if s.id == scenario_id)
        suite = RegressionSuite([scenario], runner=self.runner)
        report = suite.run()
        result = report["results"][0]
        if not result.passed:
            self.fail(
                f"Scenario {scenario_id!r} FAILED:\n"
                + "\n".join(f"  ✗ {f}" for f in result.failures)
            )

    def test_T01_test_written_first(self):
        """Production code must only be written after a failing test is confirmed Red."""
        self._run_scenario("tdd-T01-test-written-first")

    def test_T02_iron_law_enforced(self):
        """If production code is written before tests, agent must STOP and revert."""
        self._run_scenario("tdd-T02-iron-law-enforced")

    def test_T03_behavioral_red_verified(self):
        """Red state must be a behavioral assertion failure, not a syntax/import error."""
        self._run_scenario("tdd-T03-behavioral-red-verified")

    def test_T04_minimum_viable_green(self):
        """Green phase must write only the minimum code; no speculative edge cases."""
        self._run_scenario("tdd-T04-minimum-viable-green")

    def test_T05_refactor_under_green(self):
        """Refactoring must happen only when all tests are green."""
        self._run_scenario("tdd-T05-refactor-under-green")

    def test_T06_hollow_mock_rejected(self):
        """Hollow mock pattern must be detected and rejected."""
        self._run_scenario("tdd-T06-hollow-mock-rejected")

    def test_T07_assertless_test_rejected(self):
        """A test with no assertions must be rejected."""
        self._run_scenario("tdd-T07-assertless-test-rejected")

    def test_T08_db_engine_not_mocked(self):
        """Persistence tests must use ephemeral DB, never mock the DB client."""
        self._run_scenario("tdd-T08-db-engine-not-mocked")

    def test_T09_brownfield_characterisation_wrap(self):
        """Legacy untested code must be wrapped in characterisation tests first."""
        self._run_scenario("tdd-T09-brownfield-characterisation-wrap")

    def test_T10_no_conversational_filler(self):
        """Agent must open with test code immediately, not a greeting."""
        self._run_scenario("tdd-T10-no-conversational-filler")


# ---------------------------------------------------------------------------
# Design skill regression suite
# ---------------------------------------------------------------------------

class TestDesignSkillRegression(unittest.TestCase):
    """
    Asserts that the /design skill behaves correctly across 8 representative
    scenarios.  Every check corresponds to a hard constraint from SKILL.md.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _make_runner()

    def _run_scenario(self, scenario_id: str) -> None:
        scenario = next(s for s in DESIGN_SCENARIOS if s.id == scenario_id)
        suite = RegressionSuite([scenario], runner=self.runner)
        report = suite.run()
        result = report["results"][0]
        if not result.passed:
            self.fail(
                f"Scenario {scenario_id!r} FAILED:\n"
                + "\n".join(f"  ✗ {f}" for f in result.failures)
            )

    def test_DS01_facts_autonomously_inspected(self):
        """Agent must read the existing stack from files, never ask 'what DB?'"""
        self._run_scenario("design-DS01-facts-autonomously-inspected")

    def test_DS02_frontier_batched_in_rounds(self):
        """All unblocked questions must be batched into a single numbered round."""
        self._run_scenario("design-DS02-frontier-batched-in-rounds")

    def test_DS03_recommended_stance_required(self):
        """Every design question must include a concrete ➡️ Recommended Stance."""
        self._run_scenario("design-DS03-recommended-stance-required")

    def test_DS04_ungrillable_spike_delegated(self):
        """Empirical questions must be delegated to a spike, not debated."""
        self._run_scenario("design-DS04-ungrillable-spike-delegated")

    def test_DS05_confirmation_gate_enforced(self):
        """ADR and OpenSpec must not be written until user confirms."""
        self._run_scenario("design-DS05-confirmation-gate-enforced")

    def test_DS06_concurrency_domain_covered(self):
        """Concurrency domain (race windows, idempotency) must be surfaced."""
        self._run_scenario("design-DS06-concurrency-domain-covered")

    def test_DS07_five_domains_traversed(self):
        """All 5 systems inquiry domains must appear in the design round."""
        self._run_scenario("design-DS07-five-domains-traversed")

    def test_DS08_no_conversational_filler(self):
        """Agent must start with fact inspection or a frontier round."""
        self._run_scenario("design-DS08-no-conversational-filler")


# ---------------------------------------------------------------------------
# Cross-skill universal invariants
# ---------------------------------------------------------------------------

class TestUniversalSkillInvariants(unittest.TestCase):
    """
    Invariants that must hold across ALL skills:
    - Zero conversational filler
    - Stub responses are non-empty (sanity check for harness itself)
    - Every scenario has at least one BehaviourCheck
    - No scenario has a duplicate ID
    """

    ALL_SCENARIOS = REVIEW_SCENARIOS + DEBUG_SCENARIOS + TDD_SCENARIOS + DESIGN_SCENARIOS

    def test_all_scenarios_have_at_least_one_check(self):
        for scenario in self.ALL_SCENARIOS:
            with self.subTest(scenario_id=scenario.id):
                self.assertGreater(
                    len(scenario.checks), 0,
                    f"Scenario {scenario.id!r} has no BehaviourChecks",
                )

    def test_all_scenario_ids_are_unique(self):
        ids = [s.id for s in self.ALL_SCENARIOS]
        duplicates = [sid for sid in set(ids) if ids.count(sid) > 1]
        self.assertEqual(
            duplicates, [],
            f"Duplicate scenario IDs found: {duplicates}",
        )

    def test_all_stub_scenarios_have_stub_responses(self):
        """In stub mode every scenario must have a non-empty stub_response."""
        for scenario in self.ALL_SCENARIOS:
            with self.subTest(scenario_id=scenario.id):
                self.assertTrue(
                    scenario.stub_response.strip(),
                    f"Scenario {scenario.id!r} has no stub_response (required for stub mode / CI)",
                )

    def test_stub_mode_full_suite_passes(self):
        """All 40 scenarios must pass in stub mode."""
        runner = AgentRunner(mode="stub")
        suite = RegressionSuite(self.ALL_SCENARIOS, runner=runner)
        report = suite.run()

        failed = [r for r in report["results"] if not r.passed]
        if failed:
            lines = []
            for r in failed:
                lines.append(f"  FAIL {r.scenario_id}")
                for f in r.failures:
                    lines.append(f"       ✗ {f}")
            self.fail(
                f"{len(failed)} scenario(s) failed in stub mode:\n" + "\n".join(lines)
            )

    def test_scenario_count_meets_minimum(self):
        """At least 5 scenarios per skill as per release gate requirement."""
        from collections import Counter
        counts = Counter(s.skill for s in self.ALL_SCENARIOS)
        for skill in ("review", "debug", "tdd", "design"):
            with self.subTest(skill=skill):
                self.assertGreaterEqual(
                    counts[skill], 5,
                    f"Skill {skill!r} has only {counts[skill]} scenarios (minimum: 5)",
                )

    def test_harness_summary_report_format(self):
        """RegressionSuite.run() must return a valid summary report dict."""
        runner = AgentRunner(mode="stub")
        suite = RegressionSuite(REVIEW_SCENARIOS[:2], runner=runner)
        report = suite.run()

        self.assertIn("passed", report)
        self.assertIn("total", report)
        self.assertIn("n_passed", report)
        self.assertIn("n_failed", report)
        self.assertIn("pass_rate", report)
        self.assertIn("results", report)
        self.assertIn("summary", report)
        self.assertIsInstance(report["pass_rate"], float)
        self.assertGreaterEqual(report["pass_rate"], 0.0)
        self.assertLessEqual(report["pass_rate"], 1.0)


# ---------------------------------------------------------------------------
# Skill-specific constraint completeness checks
# ---------------------------------------------------------------------------

class TestConstraintCoverage(unittest.TestCase):
    """
    Validates that every hard_constraint defined in each SKILL.md has at least
    one corresponding scenario that exercises it.
    """

    CONSTRAINT_COVERAGE = {
        # review constraints → scenario tags/IDs that cover them
        "review/Evidence Requirement": [
            s.id for s in REVIEW_SCENARIOS
            if any(t in s.tags for t in ["evidence-gate", "judge", "stale-evidence"])
        ],
        "review/Judge Adjudication": [
            s.id for s in REVIEW_SCENARIOS
            if "judge" in s.tags or "evidence-gate" in s.tags
        ],
        "review/Schema Compliance": [
            s.id for s in REVIEW_SCENARIOS if "schema" in s.tags
        ],
        "review/Repair Ceiling": [
            s.id for s in REVIEW_SCENARIOS if "review-loop" in s.tags
        ],
        # debug constraints
        "debug/Reproduction Mandate": [
            s.id for s in DEBUG_SCENARIOS
            if any(t in s.tags for t in ["reproduction-mandate", "red-receipt"])
        ],
        "debug/Root Cause Over Symptom": [
            s.id for s in DEBUG_SCENARIOS if "symptom-masking" in s.tags
        ],
        "debug/Zero Test Weakening": [
            s.id for s in DEBUG_SCENARIOS if "test-weakening" in s.tags
        ],
        "debug/Two-Strike Rethink": [
            s.id for s in DEBUG_SCENARIOS if "two-strike" in s.tags
        ],
        "debug/Three-Strike Circuit Breaker": [
            s.id for s in DEBUG_SCENARIOS if "circuit-breaker" in s.tags
        ],
        "debug/Surgical Diff": [
            s.id for s in DEBUG_SCENARIOS if "surgical" in s.tags
        ],
        # tdd constraints
        "tdd/Iron Law of Test-First": [
            s.id for s in TDD_SCENARIOS if "iron-law" in s.tags or "test-first" in s.tags
        ],
        "tdd/Dual-Speed Testing": [
            s.id for s in TDD_SCENARIOS if "tier-2" in s.tags or "ephemeral-db" in s.tags
        ],
        "tdd/No Mocking of DB Engines": [
            s.id for s in TDD_SCENARIOS if "ephemeral-db" in s.tags
        ],
        # design constraints
        "design/Facts vs Decisions Law": [
            s.id for s in DESIGN_SCENARIOS if "facts-law" in s.tags
        ],
        "design/Frontier Batching": [
            s.id for s in DESIGN_SCENARIOS if "frontier-batching" in s.tags
        ],
        "design/Recommended Stance": [
            s.id for s in DESIGN_SCENARIOS if "recommended-stance" in s.tags
        ],
        "design/Ungrillable Isolation": [
            s.id for s in DESIGN_SCENARIOS if "ungrillable" in s.tags
        ],
        "design/Confirmation Gate": [
            s.id for s in DESIGN_SCENARIOS if "confirmation-gate" in s.tags
        ],
    }

    def test_every_hard_constraint_has_coverage(self):
        """Every hard_constraint must have at least one scenario covering it."""
        uncovered = [
            constraint
            for constraint, covering in self.CONSTRAINT_COVERAGE.items()
            if not covering
        ]
        self.assertEqual(
            uncovered, [],
            "The following hard constraints have NO scenario coverage:\n"
            + "\n".join(f"  • {c}" for c in uncovered),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
