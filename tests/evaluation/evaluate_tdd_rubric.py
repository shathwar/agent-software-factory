#!/usr/bin/env python3
"""evaluate_tdd_rubric.py — L5 Outcome Quality Rubric Evaluator for TDD Test Suites.

Zero external dependencies (Python 3.10+ standard library).

Evaluates whether a TDD test suite exhibits high engineering quality,
behavioral boundary coverage, specific assertions, and true integration fidelity
without database mocking or assertless tautologies.

Rubric Dimensions (0.0 - 1.0 each):
1. AAA Structure: Clear Arrange-Act-Assert isolation and readable test structure.
2. Assertion Specificity: Strict value assertions; rejection of tautologies or vacuous checks.
3. Dual-Speed Fidelity: Ephemeral DB or pure domain fakes; zero mocked DB drivers/engines.
4. Failure & Boundary Coverage: Negative cases, boundary probes, and exception assertions.
5. Micro-Cycle Focus: Targeted, atomic unit/behavioral tests rather than monolithic scripts.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional


@dataclass
class TDDRubricScore:
    name: str
    weight: float
    score: float
    feedback: List[str] = field(default_factory=list)


@dataclass
class TDDRubricReport:
    target_name: str
    overall_score: float
    passed: bool
    status: str  # PASS, CONDITIONAL, FAIL
    domain_scores: Dict[str, TDDRubricScore] = field(default_factory=dict)
    summary_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_name": self.target_name,
            "overall_score": round(self.overall_score, 3),
            "passed": self.passed,
            "status": self.status,
            "domain_scores": {
                k: {
                    "name": v.name,
                    "weight": v.weight,
                    "score": round(v.score, 3),
                    "feedback": v.feedback,
                }
                for k, v in self.domain_scores.items()
            },
            "summary_notes": self.summary_notes,
        }


class TDDRubricEvaluator:
    """Evaluates test files and suites against principal TDD outcome quality standards."""

    FORBIDDEN_DB_MODULES = {
        "psycopg", "psycopg2", "sqlite3", "asyncpg", "pymysql", "mysql",
        "prisma", "sqlalchemy", "redis", "ioredis", "pg", "mongo", "pymongo"
    }

    def __init__(self, passing_threshold: float = 0.80) -> None:
        self.passing_threshold = passing_threshold

    def evaluate_test_code(self, code_text: str, target_name: str = "TestSuite") -> TDDRubricReport:
        domain_scores: Dict[str, TDDRubricScore] = {}

        # 1. AAA Structure (weight: 0.20)
        aaa_feedback = []
        aaa_pts = 0.0
        has_setup = bool(re.search(r"(?:#\s*arrange|def setUp|fixture|pytest\.fixture|given\b)", code_text, re.IGNORECASE))
        has_act = bool(re.search(r"(?:#\s*act|result\s*=|actual\s*=|when\b|response\s*=)", code_text, re.IGNORECASE))
        has_assert = bool(re.search(r"(?:#\s*assert|assert\s+|self\.assert|expect\(|then\b)", code_text, re.IGNORECASE))

        if has_assert:
            aaa_pts += 0.40
        else:
            aaa_feedback.append("No assertions found in test suite.")

        if has_act:
            aaa_pts += 0.30
        else:
            aaa_feedback.append("No clear Act phase or action variable identified.")

        if has_setup:
            aaa_pts += 0.30
        else:
            aaa_feedback.append("No explicit Arrange/fixture setup block observed.")

        domain_scores["aaa_structure"] = TDDRubricScore(
            name="AAA Structure",
            weight=0.20,
            score=min(1.0, aaa_pts),
            feedback=aaa_feedback,
        )

        # 2. Assertion Specificity (weight: 0.25)
        spec_feedback = []
        spec_pts = 0.0
        # Check for tautologies
        has_tautology = bool(re.search(r"\bassert\s+True\b|\bassertTrue\(\s*True\s*\)|\bassertEqual\(\s*([a-zA-Z0-9_]+)\s*,\s*\1\s*\)", code_text))
        if has_tautology:
            spec_feedback.append("Critical failure: Tautological assertion detected (e.g. assert True or assertEqual(x, x)).")
            spec_pts = 0.0
        else:
            spec_pts += 0.40
            # Check for value comparisons (equality, membership, raises)
            has_value_checks = bool(re.search(r"(?:==|assertEqual|toBe|toEqual|assertIn|\.status_code\s*==)", code_text))
            if has_value_checks:
                spec_pts += 0.40
            else:
                spec_feedback.append("Lacks concrete equality/value comparisons; assertions appear loose.")

            # Multiple assertions or detailed failure messages
            has_detailed_assertions = len(re.findall(r"(?:assert\s+|self\.assert|expect\()", code_text)) >= 2
            if has_detailed_assertions:
                spec_pts += 0.20
            else:
                spec_feedback.append("Sparse assertion coverage (fewer than 2 assertions).")

        domain_scores["assertion_specificity"] = TDDRubricScore(
            name="Assertion Specificity",
            weight=0.25,
            score=min(1.0, spec_pts),
            feedback=spec_feedback,
        )

        # 3. Dual-Speed Fidelity (weight: 0.25)
        ds_feedback = []
        ds_pts = 0.0
        # Check for mocked database
        mocked_db = False
        for mod in self.FORBIDDEN_DB_MODULES:
            if re.search(rf"@patch(?:\.object)?\([^)]*['\"]\S*{mod}\S*['\"]", code_text) or \
               re.search(rf"mocker\.patch\([^)]*['\"]\S*{mod}\S*['\"]", code_text):
                mocked_db = True
                ds_feedback.append(f"Forbidden database mock detected for engine/client '{mod}'.")
                break

        if mocked_db:
            ds_pts = 0.0
        else:
            ds_pts += 0.50
            # Bonus for real ephemeral or domain fake usage
            if re.search(r"sqlite|:memory:|testcontainer|fake|mock_client|in_memory", code_text, re.IGNORECASE):
                ds_pts += 0.50
            else:
                ds_pts += 0.30

        domain_scores["dual_speed_fidelity"] = TDDRubricScore(
            name="Dual-Speed Fidelity",
            weight=0.25,
            score=min(1.0, ds_pts),
            feedback=ds_feedback,
        )

        # 4. Failure & Boundary Coverage (weight: 0.15)
        fail_feedback = []
        fail_pts = 0.0
        has_exception_test = bool(re.search(r"assertRaises|pytest\.raises|toThrow|expect\(\s*async\s*\(\)\s*=>", code_text))
        if has_exception_test:
            fail_pts += 0.60
        else:
            fail_feedback.append("No negative/exception assertion tests found (e.g. pytest.raises or assertRaises).")

        has_boundary_probes = bool(re.search(r"(-1|0|None|null|empty|\"\"|\[\]|\{\}|float\('inf'\)|404|400|500)", code_text))
        if has_boundary_probes:
            fail_pts += 0.40
        else:
            fail_feedback.append("No boundary or zero-value probe cases identified.")

        domain_scores["failure_and_boundary"] = TDDRubricScore(
            name="Failure & Boundary Coverage",
            weight=0.15,
            score=min(1.0, fail_pts),
            feedback=fail_feedback,
        )

        # 5. Micro-Cycle Focus (weight: 0.15)
        micro_feedback = []
        micro_pts = 0.0
        test_defs = re.findall(r"def\s+(test_[a-zA-Z0-9_]+)\s*\(", code_text)
        if not test_defs:
            test_defs = re.findall(r"(?:it|test)\s*\(\s*['\"]([^'\"]+)['\"]", code_text)

        if len(test_defs) >= 2:
            micro_pts += 0.60
        elif len(test_defs) == 1:
            micro_pts += 0.40
            micro_feedback.append("Single test function detected; consider splitting into atomic behavior micro-cycles.")
        else:
            micro_feedback.append("No test functions identified.")

        # Test name descriptiveness
        descriptive_names = [name for name in test_defs if len(name) > 10 and ("should" in name or "when" in name or "fails" in name or "returns" in name or "raises" in name or "_" in name)]
        if descriptive_names:
            micro_pts += 0.40
        else:
            micro_feedback.append("Test function names lack descriptive intent (e.g. test_when_empty_should_raise).")

        domain_scores["micro_cycle_focus"] = TDDRubricScore(
            name="Micro-Cycle Focus",
            weight=0.15,
            score=min(1.0, micro_pts),
            feedback=micro_feedback,
        )

        # Calculate overall score
        overall = sum(dim.score * dim.weight for dim in domain_scores.values())
        passed = overall >= self.passing_threshold and not has_tautology and not mocked_db

        if passed:
            status = "PASS"
        elif overall >= 0.60:
            status = "CONDITIONAL"
        else:
            status = "FAIL"

        notes = []
        if has_tautology:
            notes.append("REJECTED: Tautological assertion detected.")
        if mocked_db:
            notes.append("REJECTED: Database engine/driver mocked in violation of Tier 2 testing policy.")
        if not notes:
            notes.append(f"TDD Rubric Assessment completed with score {round(overall, 3)} ({status}).")

        return TDDRubricReport(
            target_name=target_name,
            overall_score=overall,
            passed=passed,
            status=status,
            domain_scores=domain_scores,
            summary_notes=notes,
        )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: evaluate_tdd_rubric.py <test_file_path> [--threshold <float>] [--json]")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"Error: File {file_path} does not exist.")
        sys.exit(1)

    threshold = 0.80
    output_json = "--json" in sys.argv
    if "--threshold" in sys.argv:
        t_idx = sys.argv.index("--threshold")
        if t_idx + 1 < len(sys.argv):
            threshold = float(sys.argv[t_idx + 1])

    evaluator = TDDRubricEvaluator(passing_threshold=threshold)
    report = evaluator.evaluate_test_code(file_path.read_text(encoding="utf-8"), target_name=file_path.name)

    if output_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"=== TDD Outcome Quality Rubric: {report.target_name} ===")
        print(f"Status: {report.status} (Score: {report.overall_score:.2f} / Threshold: {threshold:.2f})")
        print("\nDomain Breakdown:")
        for k, v in report.domain_scores.items():
            status_icon = "✓" if v.score >= 0.80 else ("~" if v.score >= 0.50 else "✗")
            print(f"  [{status_icon}] {v.name:30s} {v.score:.2f} (weight: {v.weight:.2f})")
            for fb in v.feedback:
                print(f"      - {fb}")
        print("\nSummary Notes:")
        for note in report.summary_notes:
            print(f"  • {note}")

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
