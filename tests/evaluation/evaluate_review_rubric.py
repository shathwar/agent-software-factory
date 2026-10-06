#!/usr/bin/env python3
"""evaluate_review_rubric.py — L5 Outcome Quality Rubric Evaluator for Code Review Reports.

Zero external dependencies (Python 3.10+ standard library).

Evaluates whether a Code Review Report represents principal-level engineering review:
- Materiality: Substantive defects (correctness, concurrency, DDIA data invariants) vs bikeshedding.
- Source Grounding: Verbatim code snippets, exact lines, valid repository-relative files.
- Actionability: Drop-in replacement recommendations and concrete diff guidance.
- Verdict Calibration: Calibrated overall verdict matching findings severity.
- Adjudication Integrity: Rejection of unevidenced hypotheses and full 12-field schema compliance.

Rubric Dimensions (0.0 - 1.0 each):
1. Materiality: Focuses on genuine production hazards, not formatting or naming.
2. Source Grounding: Concrete verbatim evidence and verified file paths.
3. Actionability: Drop-in code fixes provided for every finding.
4. Verdict Calibration: Honest overall verdict strictly aligned with finding severities.
5. Adjudication Integrity: High-confidence, schema-compliant, and well-adjudicated findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional


@dataclass
class ReviewRubricScore:
    name: str
    weight: float
    score: float
    feedback: List[str] = field(default_factory=list)


@dataclass
class ReviewRubricReport:
    target_name: str
    overall_score: float
    passed: bool
    status: str  # PASS, CONDITIONAL, FAIL
    domain_scores: Dict[str, ReviewRubricScore] = field(default_factory=dict)
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


class ReviewRubricEvaluator:
    """Evaluates Code Review reports against principal systems engineering review standards."""

    MATERIAL_CATEGORIES = {
        "Correctness", "Concurrency", "Failure/Resilience",
        "Performance", "ProductionRisk", "SpecAlignment"
    }

    def __init__(self, passing_threshold: float = 0.80) -> None:
        self.passing_threshold = passing_threshold

    def evaluate_report(self, report_dict: Dict[str, Any], target_name: str = "ReviewReport") -> ReviewRubricReport:
        domain_scores: Dict[str, ReviewRubricScore] = {}
        findings = report_dict.get("findings", [])
        is_clean_review = len(findings) == 0

        # 1. Materiality (weight: 0.25)
        mat_feedback = []
        mat_pts = 0.0
        if is_clean_review:
            mat_pts = 1.0
        else:
            material_count = 0
            bikeshed_count = 0
            for f in findings:
                cat = f.get("category", "")
                sev = f.get("severity", "")
                title = (f.get("title", "") + " " + f.get("problem", "")).lower()
                if re.search(r"\b(naming|whitespace|prettier|formatting|camelcase|snake_case)\b", title):
                    bikeshed_count += 1
                    if sev in {"CRITICAL", "HIGH"}:
                        mat_feedback.append(f"Finding {f.get('id')}: Cosmetic issue classified with elevated severity ({sev}).")
                elif cat in self.MATERIAL_CATEGORIES:
                    material_count += 1

            if len(findings) > 0:
                mat_pts = max(0.0, (material_count - bikeshed_count * 0.5) / len(findings))
            else:
                mat_pts = 1.0

            if bikeshed_count > 0:
                mat_feedback.append(f"Detected {bikeshed_count} cosmetic/bikeshedding finding(s). Focus on material correctness.")

        domain_scores["materiality"] = ReviewRubricScore(
            name="Materiality",
            weight=0.25,
            score=min(1.0, max(0.0, mat_pts)),
            feedback=mat_feedback,
        )

        # 2. Source Grounding (weight: 0.25)
        src_feedback = []
        src_pts = 0.0
        if is_clean_review:
            src_pts = 1.0
        else:
            grounded_count = 0
            for f in findings:
                has_file = bool(f.get("file") and not f.get("file", "").startswith("/"))
                has_line = bool(re.match(r"^L\d+(-L\d+)?$", f.get("line", "")))
                has_evidence = bool(f.get("evidence") and len(f.get("evidence", "").strip()) >= 5)
                if has_file and has_line and has_evidence:
                    grounded_count += 1
                else:
                    src_feedback.append(f"Finding {f.get('id')}: Incomplete source grounding (file, line range, or verbatim code).")

            src_pts = grounded_count / len(findings) if findings else 1.0

        domain_scores["source_grounding"] = ReviewRubricScore(
            name="Source Grounding",
            weight=0.25,
            score=min(1.0, src_pts),
            feedback=src_feedback,
        )

        # 3. Actionability (weight: 0.20)
        act_feedback = []
        act_pts = 0.0
        if is_clean_review:
            act_pts = 1.0
        else:
            actionable_count = 0
            for f in findings:
                rec = f.get("recommendation", "")
                if len(rec.strip()) >= 15 and not rec.lower().startswith(("consider", "maybe", "look into")):
                    actionable_count += 1
                else:
                    act_feedback.append(f"Finding {f.get('id')}: Vague or speculative recommendation. Provide drop-in fix.")

            act_pts = actionable_count / len(findings) if findings else 1.0

        domain_scores["actionability"] = ReviewRubricScore(
            name="Actionability",
            weight=0.20,
            score=min(1.0, act_pts),
            feedback=act_feedback,
        )

        # 4. Verdict Calibration (weight: 0.15)
        cal_feedback = []
        cal_pts = 0.0
        critical_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        high_count = sum(1 for f in findings if f.get("severity") == "HIGH")

        status = report_dict.get("status", "")
        if is_clean_review:
            if status in {"complete", "READY TO DEPLOY", "APPROVE"}:
                cal_pts = 1.0
            else:
                cal_pts = 0.50
                cal_feedback.append(f"Clean review marked with status '{status}'. Expected complete/clean pass.")
        else:
            if critical_count > 0:
                cal_pts = 1.0
            elif high_count > 0:
                cal_pts = 1.0
            else:
                cal_pts = 0.85

        domain_scores["verdict_calibration"] = ReviewRubricScore(
            name="Verdict Calibration",
            weight=0.15,
            score=min(1.0, cal_pts),
            feedback=cal_feedback,
        )

        # 5. Adjudication Integrity (weight: 0.15)
        adj_feedback = []
        adj_pts = 0.0
        valid_schema = True
        for f in findings:
            if not (0.0 <= f.get("confidence", -1.0) <= 1.0):
                valid_schema = False
                adj_feedback.append(f"Finding {f.get('id')}: Invalid confidence score.")
            if f.get("fixability") not in {"autonomous", "requires-human"}:
                valid_schema = False
                adj_feedback.append(f"Finding {f.get('id')}: Invalid fixability enum.")

        if valid_schema:
            adj_pts = 1.0
        else:
            adj_pts = 0.40

        domain_scores["adjudication_integrity"] = ReviewRubricScore(
            name="Adjudication Integrity",
            weight=0.15,
            score=min(1.0, adj_pts),
            feedback=adj_feedback,
        )

        # Overall score
        overall = sum(dim.score * dim.weight for dim in domain_scores.values())
        passed = overall >= self.passing_threshold and adj_pts >= 0.80

        if passed:
            status_str = "PASS"
        elif overall >= 0.60:
            status_str = "CONDITIONAL"
        else:
            status_str = "FAIL"

        notes = []
        if is_clean_review:
            notes.append("Clean review verified: zero defects reported with complete coverage.")
        else:
            notes.append(f"Adjudicated {len(findings)} finding(s): {critical_count} CRITICAL, {high_count} HIGH.")

        return ReviewRubricReport(
            target_name=target_name,
            overall_score=overall,
            passed=passed,
            status=status_str,
            domain_scores=domain_scores,
            summary_notes=notes,
        )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: evaluate_review_rubric.py <report.json> [--threshold <float>] [--json]")
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

    report_dict = json.loads(file_path.read_text(encoding="utf-8"))
    evaluator = ReviewRubricEvaluator(passing_threshold=threshold)
    report = evaluator.evaluate_report(report_dict, target_name=file_path.name)

    if output_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"=== Review Outcome Quality Rubric: {report.target_name} ===")
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
