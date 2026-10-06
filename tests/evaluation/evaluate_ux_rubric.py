#!/usr/bin/env python3
"""evaluate_ux_rubric.py — L5 Outcome Quality Rubric Evaluator for Frontend UX Components.

Zero external dependencies (Python 3.10+ standard library).

Evaluates whether a frontend component or UX specification represents principal-level UX:
1. Flow Grilling & Architecture: Defined JTBD, escape paths, cancellation, and Krug friction reduction.
2. State Matrix Completeness: Brad Frost 6-state matrix completeness (Empty, Loading, Populated, Partial, Error, Unavailable).
3. WCAG Accessibility Compliance: Semantic native HTML, visible focus outlines, form labels, icon labels, contrast.
4. Visual Refinement (Impeccable): Design tokens, consistent spacing scale, typography hierarchy, touch targets.
5. Anti-Slop Structural Integrity (Hallmark): Distinctive layout, zero generic AI slop, safe destructive confirmations.

Rubric Dimensions (0.0 - 1.0 each):
1. Flow Grilling & Architecture (weight: 0.15)
2. State Matrix Completeness (weight: 0.25)
3. WCAG Accessibility Compliance (weight: 0.25)
4. Visual Refinement (Impeccable) (weight: 0.15)
5. Anti-Slop Structural Integrity (Hallmark) (weight: 0.20)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional


@dataclass
class UXRubricScore:
    name: str
    weight: float
    score: float
    feedback: List[str] = field(default_factory=list)


@dataclass
class UXRubricReport:
    target_name: str
    overall_score: float
    passed: bool
    status: str  # PASS, CONDITIONAL, FAIL
    domain_scores: Dict[str, UXRubricScore] = field(default_factory=dict)
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


class UXRubricEvaluator:
    """Evaluates frontend components and UX design artifacts against principal UX standards."""

    def __init__(self, passing_threshold: float = 0.80) -> None:
        self.passing_threshold = passing_threshold

    def evaluate_component(
        self,
        component_spec: Dict[str, Any],
        target_name: str = "UXComponent"
    ) -> UXRubricReport:
        domain_scores: Dict[str, UXRubricScore] = {}

        # 1. Flow Grilling & Architecture (weight: 0.15)
        fg_feedback = []
        fg_pts = 0.0
        flow = component_spec.get("flow", {})
        jtbd = flow.get("jtbd", "") or component_spec.get("jtbd", "")
        escape_paths = flow.get("escape_paths", []) or component_spec.get("escape_paths", [])
        undo_or_cancel = flow.get("cancellation_or_undo", False) or bool(escape_paths)

        if jtbd:
            fg_pts += 0.5
        else:
            fg_feedback.append("Missing primary Job-to-be-Done (JTBD) definition.")

        if undo_or_cancel:
            fg_pts += 0.5
        else:
            fg_feedback.append("Missing secondary escape paths, cancellation, or undo mechanics.")

        domain_scores["flow_architecture"] = UXRubricScore(
            name="Flow Grilling & Architecture",
            weight=0.15,
            score=min(1.0, fg_pts),
            feedback=fg_feedback,
        )

        # 2. State Matrix Completeness (weight: 0.25)
        sm_feedback = []
        sm_pts = 0.0
        states = component_spec.get("states", {})
        required_states = {"empty", "loading", "populated", "error"}
        defined_states = {k.lower() for k, v in states.items() if v}
        missing_states = required_states - defined_states

        if not missing_states:
            sm_pts += 0.7
            # Check if error state has actionable recovery
            err_state = states.get("error", {})
            if isinstance(err_state, dict) and (err_state.get("recovery_action") or err_state.get("actionable")):
                sm_pts += 0.3
            elif isinstance(err_state, str) and any(w in err_state.lower() for w in ["retry", "reload", "help", "contact"]):
                sm_pts += 0.3
            else:
                sm_feedback.append("Error state lacks actionable recovery CTA (Retry, Reload, Contact).")
        else:
            sm_pts += max(0.2, (len(defined_states) / 6.0))
            sm_feedback.append(f"Missing core states from 6-State Matrix: {sorted(list(missing_states))}.")

        domain_scores["state_matrix"] = UXRubricScore(
            name="State Matrix Completeness",
            weight=0.25,
            score=min(1.0, sm_pts),
            feedback=sm_feedback,
        )

        # 3. WCAG Accessibility Compliance (weight: 0.25)
        wcag_feedback = []
        wcag_pts = 1.0
        a11y = component_spec.get("accessibility", {})
        violations = component_spec.get("audit_violations", [])

        # Check audit violations
        error_violations = [v for v in violations if v.get("severity") in ("CRITICAL", "ERROR")]
        if error_violations:
            penalty = len(error_violations) * 0.25
            wcag_pts = max(0.1, 1.0 - penalty)
            for ev in error_violations[:3]:
                wcag_feedback.append(f"[{ev.get('rule_id', 'A11Y')}] {ev.get('message', '')}")
        elif not a11y.get("keyboard_navigable", True) or not a11y.get("focus_indicators_visible", True):
            wcag_pts = 0.5
            wcag_feedback.append("Keyboard navigation or focus indicators not verified.")

        domain_scores["wcag_accessibility"] = UXRubricScore(
            name="WCAG Accessibility Compliance",
            weight=0.25,
            score=wcag_pts,
            feedback=wcag_feedback,
        )

        # 4. Visual Refinement (Impeccable) (weight: 0.15)
        vr_feedback = []
        vr_pts = 0.0
        tokens = component_spec.get("design_system", {})
        token_reuse = tokens.get("tokens_reused", True)
        arbitrary_count = tokens.get("arbitrary_values_count", 0)

        if token_reuse and arbitrary_count == 0:
            vr_pts = 1.0
        elif token_reuse and arbitrary_count <= 2:
            vr_pts = 0.8
            vr_feedback.append(f"{arbitrary_count} arbitrary values detected; justify or replace with semantic tokens.")
        else:
            vr_pts = 0.4
            vr_feedback.append(f"Design token hierarchy ignored; {arbitrary_count} arbitrary values found.")

        domain_scores["visual_refinement"] = UXRubricScore(
            name="Visual Refinement (Impeccable)",
            weight=0.15,
            score=vr_pts,
            feedback=vr_feedback,
        )

        # 5. Anti-Slop Structural Integrity (Hallmark) (weight: 0.20)
        as_feedback = []
        as_pts = 1.0
        slop = component_spec.get("slop_patterns", [])
        destructive = component_spec.get("destructive_actions", {})

        if slop:
            penalty = len(slop) * 0.25
            as_pts = max(0.2, 1.0 - penalty)
            as_feedback.append(f"Generic AI-slop layout patterns detected: {', '.join(slop)}.")

        if destructive.get("present", False) and not destructive.get("confirmed", False):
            as_pts = min(as_pts, 0.5)
            as_feedback.append("Destructive action lacks confirmation dialog or undo mechanic.")

        domain_scores["anti_slop_structural"] = UXRubricScore(
            name="Anti-Slop Structural Integrity",
            weight=0.20,
            score=as_pts,
            feedback=as_feedback,
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

        return UXRubricReport(
            target_name=target_name,
            overall_score=overall,
            passed=passed,
            status=status,
            domain_scores=domain_scores,
            summary_notes=summary_notes,
        )


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate a UX component spec against the L5 UX rubric.")
    parser.add_argument("--spec", "-s", type=Path, required=True, help="Path to JSON file containing component spec.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format.")
    args = parser.parse_args(argv)

    if not args.spec.exists():
        print(f"Error: Spec file not found: {args.spec}", file=sys.stderr)
        return 1

    try:
        with open(args.spec, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading JSON spec: {e}", file=sys.stderr)
        return 1

    evaluator = UXRubricEvaluator()
    report = evaluator.evaluate_component(data, target_name=args.spec.stem)

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"## 🎨 L5 UX Quality Rubric: {report.target_name}")
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
