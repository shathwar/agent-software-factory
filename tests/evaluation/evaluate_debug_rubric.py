#!/usr/bin/env python3
"""evaluate_debug_rubric.py — L5 Outcome Quality Rubric Evaluator for Bugfixes and Debug Audits.

Zero external dependencies (Python 3.10+ standard library).

Evaluates whether a bugfix demonstrates principal-level root-cause debugging:
1. Causal Grounding: Fix addresses root origin rather than patching at the point of impact.
2. Reproduction Rigor: Minimal, isolated, deterministic failing reproduction test proven Red before fix.
3. Surgical Laziness: Minimal diff strictly focused on root cause; zero unrequested refactoring.
4. Zero Test Weakening: Test suite assertions are preserved or strengthened; no skipped/xfail tests.
5. Zero Symptom Masking: No defensive exception swallowing or crash-site null guards.

Rubric Dimensions (0.0 - 1.0 each):
1. Causal Grounding (weight: 0.25)
2. Reproduction Rigor (weight: 0.25)
3. Surgical Laziness (weight: 0.20)
4. Zero Test Weakening (weight: 0.15)
5. Zero Symptom Masking (weight: 0.15)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional


@dataclass
class DebugRubricScore:
    name: str
    weight: float
    score: float
    feedback: List[str] = field(default_factory=list)


@dataclass
class DebugRubricReport:
    target_name: str
    overall_score: float
    passed: bool
    status: str  # PASS, CONDITIONAL, FAIL
    domain_scores: Dict[str, DebugRubricScore] = field(default_factory=dict)
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


class DebugRubricEvaluator:
    """Evaluates bugfixes and debugging audit records against principal systems engineering standards."""

    def __init__(self, passing_threshold: float = 0.80) -> None:
        self.passing_threshold = passing_threshold

    def evaluate_bugfix(
        self,
        audit_record: Dict[str, Any],
        target_name: str = "BugfixAudit"
    ) -> DebugRubricReport:
        domain_scores: Dict[str, DebugRubricScore] = {}

        # 1. Causal Grounding (weight: 0.25)
        cg_feedback = []
        cg_pts = 0.0
        hypothesis = audit_record.get("hypothesis", "")
        causal_trace = audit_record.get("causal_trace", [])
        point_of_impact = audit_record.get("point_of_impact", "")
        root_cause_origin = audit_record.get("root_cause_origin", "")

        if point_of_impact and root_cause_origin:
            if point_of_impact == root_cause_origin:
                cg_feedback.append("Point of impact matches root cause origin. Ensure this is not a symptom patch.")
                cg_pts = 0.7
            else:
                cg_pts = 1.0
        elif hypothesis and causal_trace:
            cg_pts = 1.0
        elif hypothesis or causal_trace:
            cg_pts = 0.6
            cg_feedback.append("Causal trace or hypothesis partially documented.")
        else:
            cg_feedback.append("No causal trace or hypothesis provided; root cause unverified.")
            cg_pts = 0.2

        domain_scores["causal_grounding"] = DebugRubricScore(
            name="Causal Grounding",
            weight=0.25,
            score=min(1.0, cg_pts),
            feedback=cg_feedback,
        )

        # 2. Reproduction Rigor (weight: 0.25)
        rr_feedback = []
        rr_pts = 0.0
        repro_test = audit_record.get("reproduction_test", {})
        repro_found = audit_record.get("repro_test_found", False) or bool(repro_test)
        repro_red_proven = repro_test.get("red_proven", False)
        assertions = repro_test.get("assertions", [])

        if not repro_found:
            rr_feedback.append("Reproduction mandate violated: No reproduction test provided in diff.")
            rr_pts = 0.0
        else:
            if repro_red_proven:
                rr_pts += 0.5
            else:
                rr_feedback.append("Reproduction test was not explicitly proven failing (Red) before fix.")
                rr_pts += 0.2

            if assertions:
                tautological = [a for a in assertions if "True" in a or "true" in a or "1 == 1" in a]
                if len(tautological) == len(assertions):
                    rr_feedback.append("Hollow reproduction test: Only tautological assertions found.")
                    rr_pts += 0.0
                else:
                    rr_pts += 0.5
            else:
                rr_pts += 0.3

        domain_scores["reproduction_rigor"] = DebugRubricScore(
            name="Reproduction Rigor",
            weight=0.25,
            score=min(1.0, rr_pts),
            feedback=rr_feedback,
        )

        # 3. Surgical Laziness (weight: 0.20)
        sl_feedback = []
        sl_pts = 0.0
        prod_files = audit_record.get("prod_files_modified", [])
        total_prod_lines = audit_record.get("total_prod_lines_added", 0)

        if len(prod_files) == 0:
            sl_feedback.append("No production files modified.")
            sl_pts = 0.5
        elif len(prod_files) <= 2 and total_prod_lines <= 30:
            sl_pts = 1.0  # Ideal surgical diff
        elif len(prod_files) <= 4 and total_prod_lines <= 80:
            sl_pts = 0.8
            sl_feedback.append("Diff is moderately sized. Ensure no extraneous refactoring.")
        elif len(prod_files) <= 5 and total_prod_lines <= 150:
            sl_pts = 0.6
            sl_feedback.append("Diff approaches non-surgical boundary.")
        else:
            sl_feedback.append(f"Excessive diff scope: {len(prod_files)} files, {total_prod_lines} lines added. Violates laziness ladder.")
            sl_pts = 0.2

        domain_scores["surgical_laziness"] = DebugRubricScore(
            name="Surgical Laziness",
            weight=0.20,
            score=min(1.0, sl_pts),
            feedback=sl_feedback,
        )

        # 4. Zero Test Weakening (weight: 0.15)
        tw_feedback = []
        tw_pts = 1.0
        violations = audit_record.get("violations", [])
        weakening_violations = [v for v in violations if "Test Weakening" in v or "Assertion Degradation" in v]

        if weakening_violations:
            tw_pts = 0.0
            tw_feedback.extend(weakening_violations)

        domain_scores["zero_test_weakening"] = DebugRubricScore(
            name="Zero Test Weakening",
            weight=0.15,
            score=tw_pts,
            feedback=tw_feedback,
        )

        # 5. Zero Symptom Masking (weight: 0.15)
        sm_feedback = []
        sm_pts = 1.0
        masking_violations = [v for v in violations if "Symptom Masking" in v or "Hollow Repro" in v]

        if masking_violations:
            sm_pts = 0.0
            sm_feedback.extend(masking_violations)

        domain_scores["zero_symptom_masking"] = DebugRubricScore(
            name="Zero Symptom Masking",
            weight=0.15,
            score=sm_pts,
            feedback=sm_feedback,
        )

        overall = sum(s.score * s.weight for s in domain_scores.values())
        passed = overall >= self.passing_threshold and all(
            s.score >= 0.5 for s in domain_scores.values()
        )
        status = "PASS" if passed else ("CONDITIONAL" if overall >= 0.65 else "FAIL")

        summary_notes = []
        for s in domain_scores.values():
            if s.score < 0.70:
                summary_notes.append(f"{s.name} scored low ({s.score:.2f}): " + "; ".join(s.feedback))

        return DebugRubricReport(
            target_name=target_name,
            overall_score=overall,
            passed=passed,
            status=status,
            domain_scores=domain_scores,
            summary_notes=summary_notes,
        )


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate a bugfix audit record against the L5 debug rubric.")
    parser.add_argument("--record", "-r", type=Path, required=True, help="Path to JSON file containing bugfix audit record.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format.")
    args = parser.parse_args(argv)

    if not args.record.exists():
        print(f"Error: Record file not found: {args.record}", file=sys.stderr)
        return 1

    try:
        with open(args.record, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading JSON record: {e}", file=sys.stderr)
        return 1

    evaluator = DebugRubricEvaluator()
    report = evaluator.evaluate_bugfix(data, target_name=args.record.stem)

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"## 🛠️ L5 Debug Quality Rubric: {report.target_name}")
        print(f"- **Overall Score**: {report.overall_score:.2f} / 1.00 ({report.status})")
        print(f"- **Outcome Gate**: {'✅ PASSED' if report.passed else '❌ FAILED'}\n")
        print("### Domain Scores")
        for key, ds in report.domain_scores.items():
            icon = "✅" if ds.score >= 0.8 else ("⚠️" if ds.score >= 0.6 else "❌")
            print(f"- {icon} **{ds.name}** (weight: {ds.weight:.2f}): {ds.score:.2f}")
            for fb in ds.feedback:
                print(f"  - {fb}")
        if report.summary_notes:
            print("\n### Critical Gaps")
            for note in report.summary_notes:
                print(f"- {note}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
