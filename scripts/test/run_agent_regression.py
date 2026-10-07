#!/usr/bin/env python3
"""
scripts/test/run_agent_regression.py
====================================
CLI runner for response-contract regression checks.

Evaluates:
  Output predicates; default stub mode does not measure agent adherence.

Usage:
  python3 scripts/test/run_agent_regression.py [--skill review|debug|tdd|design|all]
                                               [--mode stub|anthropic|live]
                                               [--scenario <id>]
                                               [--format text|json|markdown]
                                               [--output <file>]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.agent_harness.core import AgentRunner, RegressionSuite  # noqa: E402
from tests.agent_harness.scenarios_debug import DEBUG_SCENARIOS  # noqa: E402
from tests.agent_harness.scenarios_design import DESIGN_SCENARIOS  # noqa: E402
from tests.agent_harness.scenarios_eval_cases import TWELVE_BEHAVIORAL_SCENARIOS  # noqa: E402
from tests.agent_harness.scenarios_review import REVIEW_SCENARIOS  # noqa: E402
from tests.agent_harness.scenarios_tdd import TDD_SCENARIOS  # noqa: E402

ALL_SCENARIOS = {
    "review": REVIEW_SCENARIOS,
    "debug": DEBUG_SCENARIOS,
    "tdd": TDD_SCENARIOS,
    "design": DESIGN_SCENARIOS,
    "eval12": TWELVE_BEHAVIORAL_SCENARIOS,
}


def format_markdown_report(report: dict, mode: str) -> str:
    lines = [
        "# Response Contract Report",
        "",
        f"- **Execution Mode**: `{mode}`",
        f"- **Assessment**: `{report['assessment_kind']}`; behavior is not independently verified",
        f"- **Status**: {report['status'].upper()}",
        f"- **Total Scenarios**: {report['total']}",
        f"- **Passed**: {report['n_passed']}",
        f"- **Failed**: {report['n_failed']}",
        "",
        "## Scenario Breakdown",
        "",
        "| Skill | Scenario ID | Description | Checks | Status |",
        "|---|---|---|---|---|",
    ]

    for r in report["results"]:
        status_icon = "✅ PASS" if r.passed else "❌ FAIL"
        checks_ratio = f"{r.checks_passed}/{r.checks_total}"
        lines.append(
            f"| `{r.skill}` | `{r.scenario_id}` | {r.scenario_description} | {checks_ratio} | {status_icon} |"
        )

    if report["n_failed"] > 0:
        lines.extend(["", "## Failure Details", ""])
        for r in report["results"]:
            if not r.passed:
                lines.append(f"### ❌ `{r.scenario_id}`")
                lines.append(f"**Description**: {r.scenario_description}\n")
                lines.append("**Failed Checks**:")
                for f in r.failures:
                    lines.append(f"- ✗ {f}")
                lines.append("")

    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run response predicates; defaults to canned stubs, not measured agent adherence."
    )
    parser.add_argument(
        "--skill",
        choices=["review", "debug", "tdd", "design", "eval12", "all"],
        default="all",
        help="Target skill or suite to test (default: all)",
    )
    parser.add_argument(
        "--suite",
        choices=["core", "12", "eval12", "all"],
        help="Target benchmark suite ('12' or 'eval12' selects the 12 behavioral evaluation cases)",
    )
    parser.add_argument(
        "--mode",
        choices=["stub", "anthropic", "live"],
        default=os.environ.get("AGENT_HARNESS_MODE", "stub"),
        help="Agent execution mode (stub: fast mock, anthropic: API, live: agy CLI)",
    )
    parser.add_argument(
        "--scenario",
        help="Filter by specific scenario ID prefix or exact name",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output presentation format",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Optional path to write output report to",
    )
    args = parser.parse_args(argv)

    # Gather scenarios
    scenarios = []
    if args.suite in ("12", "eval12"):
        scenarios.extend(TWELVE_BEHAVIORAL_SCENARIOS)
    elif args.suite == "core":
        for k in ("review", "debug", "tdd", "design"):
            scenarios.extend(ALL_SCENARIOS[k])
    elif args.skill == "all":
        for skill_scenarios in ALL_SCENARIOS.values():
            scenarios.extend(skill_scenarios)
    else:
        scenarios.extend(ALL_SCENARIOS[args.skill])

    if args.scenario:
        scenarios = [s for s in scenarios if args.scenario in s.id]
        if not scenarios:
            print(f"Error: No scenarios matched filter {args.scenario!r}", file=sys.stderr)
            return 2

    runner = AgentRunner(mode=args.mode)
    suite = RegressionSuite(scenarios=scenarios, runner=runner)
    report = suite.run()

    output_str = ""
    if args.format == "json":
        json_data = {
            "passed": report["passed"],
            "total": report["total"],
            "n_passed": report["n_passed"],
            "n_failed": report["n_failed"],
            "pass_rate": report["pass_rate"],
            "mode": args.mode,
            "assessment_kind": report["assessment_kind"],
            "behavior_verified": report["behavior_verified"],
            "status": report["status"],
            "results": [
                {
                    "scenario_id": r.scenario_id,
                    "description": r.scenario_description,
                    "skill": r.skill,
                    "passed": r.passed,
                    "checks_total": r.checks_total,
                    "checks_passed": r.checks_passed,
                    "failures": r.failures,
                    "elapsed_ms": r.elapsed_ms,
                }
                for r in report["results"]
            ],
        }
        output_str = json.dumps(json_data, indent=2)
    elif args.format == "markdown":
        output_str = format_markdown_report(report, args.mode)
    else:
        output_str = report["summary"]

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_str, encoding="utf-8")
        print(f"Report written to {args.output}")

    print(output_str)

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
