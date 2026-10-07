#!/usr/bin/env python3
"""evaluate_evals_rubric.py — L5 Outcome Quality Rubric Evaluator for AI Evaluation Suites.

Zero external dependencies (Python 3.10+ standard library).

Evaluates whether an AI evaluation design reflects Hamel Husain & Parlance Labs methodology:
1. Code-First Priority: Objective checks (schemas, status codes, regex, tool calls) handled via deterministic code.
2. Binary Judge Design: Binary Pass/Fail with explicit critique-before-result; zero Likert scales.
3. Split Isolation: Strict separation between few-shot prompt examples and held-out test sets (zero leakage).
4. Statistical Rigor: Independent TPR and TNR reporting; never relying solely on raw accuracy on imbalanced data.
5. Rogan-Gladen Correction: Bias-corrected true prevalence estimation with bootstrap confidence intervals.

Rubric Dimensions (0.0 - 1.0 each):
1. Code-First Priority (weight: 0.20)
2. Binary Judge Precision (weight: 0.25)
3. Split Isolation Rigor (weight: 0.20)
4. Statistical Rigor (TPR/TNR) (weight: 0.20)
5. Rogan-Gladen Prevalence (weight: 0.15)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional


@dataclass
class EvalsRubricScore:
    name: str
    weight: float
    score: float
    feedback: List[str] = field(default_factory=list)


@dataclass
class EvalsRubricReport:
    target_name: str
    overall_score: float
    passed: bool
    status: str  # PASS, CONDITIONAL, FAIL
    domain_scores: Dict[str, EvalsRubricScore] = field(default_factory=dict)
    summary_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assessment_kind": "spec_lint",
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


class EvalsRubricEvaluator:
    """Evaluates AI Evaluation suites and judge specs against Parlance Labs rigor standards."""

    def __init__(self, passing_threshold: float = 0.80) -> None:
        self.passing_threshold = passing_threshold

    def evaluate_eval_suite(
        self,
        eval_spec: Dict[str, Any],
        target_name: str = "EvalsSuite"
    ) -> EvalsRubricReport:
        if not isinstance(eval_spec, dict):
            return EvalsRubricReport(target_name, 0.0, False, 'FAIL', summary_notes=['Expected an evaluation spec object.'])
        evaluators = eval_spec.get('evaluators', [])
        if (not isinstance(evaluators, list) or
                any(not isinstance(e, dict) or any(not isinstance(e.get(k, ''), str)
                    for k in ('type', 'name', 'description', 'prompt', 'rubric', 'model')) for e in evaluators) or
                any(not isinstance(eval_spec.get(k, {}), dict) for k in ('splits', 'calibration', 'production_monitoring'))):
            return EvalsRubricReport(target_name, 0.0, False, 'FAIL', summary_notes=['Malformed evaluators or evidence sections.'])
        domain_scores: Dict[str, EvalsRubricScore] = {}

        # 1. Code-First Priority (weight: 0.20)
        cfp_feedback = []
        cfp_pts = 0.0
        evaluators = eval_spec.get("evaluators", [])
        code_evaluators = [e for e in evaluators if e.get("type") in ("code", "deterministic", "assertion", "regex", "schema")]
        llm_evaluators = [e for e in evaluators if e.get("type") in ("llm_judge", "model", "prompt")]

        # Check if objective checks are misrouted to LLMs
        misrouted = []
        for e in llm_evaluators:
            task = (e.get("name", "") + " " + e.get("description", "")).lower()
            if any(term in task for term in ["json valid", "schema valid", "status code", "regex", "exact match", "latency", "token count"]):
                misrouted.append(e.get("name", "unnamed"))

        if misrouted:
            cfp_feedback.append(f"Objective assertion misrouted to LLM judge: {misrouted}. Must use code assertions.")
            cfp_pts += 0.2
        elif code_evaluators or llm_evaluators:
            ratio = len(code_evaluators) / max(1, len(evaluators))
            if ratio >= 0.3:
                cfp_pts += 1.0
            else:
                cfp_pts += 0.7
                cfp_feedback.append(f"Code-first ratio ({ratio:.1%}) is low; ensure objective checks are asserted in code.")
        else:
            cfp_feedback.append("No evaluators defined.")

        domain_scores["code_first_priority"] = EvalsRubricScore(
            name="Code-First Priority",
            weight=0.20,
            score=min(1.0, cfp_pts),
            feedback=cfp_feedback,
        )

        # 2. Binary Judge Precision (weight: 0.25)
        bjp_feedback = []
        bjp_pts = 0.0
        if not llm_evaluators:
            # If purely code evaluators, binary precision is naturally satisfied
            bjp_pts = 1.0
        else:
            flawed_judges = 0
            for j in llm_evaluators:
                prompt = j.get("prompt", "") + " " + j.get("rubric", "")
                prompt_lower = prompt.lower()
                # Check for Likert scale
                if re.search(r"\b(1\s*[-–]\s*5|1\s*[-–]\s*10|scale of 1|likert|rate 1-5)\b", prompt_lower):
                    bjp_feedback.append(f"Judge '{j.get('name')}' uses a Likert/multi-point scale. Must be binary Pass/Fail.")
                    flawed_judges += 1
                # Check for reasoning/critique
                if not any(k in prompt_lower for k in ["critique", "reasoning", "thought", "chain of thought", "justification"]):
                    bjp_feedback.append(f"Judge '{j.get('name')}' missing critique-before-result requirement.")
                    flawed_judges += 1
                # Check for pinned model
                model = j.get("model", "")
                if not re.search(r"(?:\d{4}-\d{2}-\d{2}|\d{8})$", model):
                    bjp_feedback.append(f"Judge '{j.get('name')}' uses unpinned model '{model}'. Pin snapshot date.")
                    flawed_judges += 1
                if not (re.search(r'\bpass\b', prompt_lower) and re.search(r'\bfail\b', prompt_lower)):
                    bjp_feedback.append('Both binary output labels Pass and Fail must be specified.')
                    flawed_judges += 1

            if flawed_judges == 0:
                bjp_pts = 1.0
            else:
                penalty = (flawed_judges / len(llm_evaluators)) * 0.8
                bjp_pts = max(0.1, 1.0 - penalty)

        domain_scores["binary_judge_design"] = EvalsRubricScore(
            name="Binary Judge Design",
            weight=0.25,
            score=min(1.0, bjp_pts),
            feedback=bjp_feedback,
        )

        # 3. Split Isolation Rigor (weight: 0.20)
        sir_feedback = []
        sir_pts = 0.0
        split = eval_spec.get("splits", {})
        partitions = [split.get(k, []) for k in ('train', 'few_shot', 'dev', 'test', 'held_out')]
        valid_ids = all(isinstance(ids, list) and all(isinstance(x, str) and x.strip() for x in ids)
                        and len(ids) == len(set(ids)) for ids in partitions)
        train_ids = set().union(*partitions[:3]) if valid_ids else set()
        test_ids = set().union(*partitions[3:]) if valid_ids else set()

        if not valid_ids or not train_ids or not test_ids:
            sir_feedback.append('Provide nonempty development and held-out sample IDs without duplicates; a boolean isolation claim is insufficient.')
            sir_pts = 0.0
        else:
            leakage = train_ids.intersection(test_ids)
            if leakage:
                sir_feedback.append(f"Data leakage detected! {len(leakage)} samples shared between train and test: {list(leakage)[:3]}.")
                sir_pts = 0.0
            else:
                sir_pts = 1.0

        domain_scores["split_isolation"] = EvalsRubricScore(
            name="Split Isolation Rigor",
            weight=0.20,
            score=min(1.0, sir_pts),
            feedback=sir_feedback,
        )

        # 4. Statistical Rigor (TPR/TNR) (weight: 0.20)
        stat_feedback = []
        stat_pts = 0.0
        calib = eval_spec.get("calibration", {})
        tpr = calib.get("tpr")
        tnr = calib.get("tnr")
        accuracy_only = calib.get("accuracy_only", False) or (calib.get("accuracy") is not None and tpr is None and tnr is None)

        if accuracy_only:
            stat_feedback.append("Only raw accuracy reported without TPR/TNR. Vulnerable to imbalanced test set bias.")
            stat_pts = 0.2
        elif all(type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 1 for x in (tpr, tnr)):
            if tpr >= 0.80 and tnr >= 0.80:
                stat_pts = 1.0
                if tpr >= 0.90 and tnr >= 0.90:
                    pass
                else:
                    stat_feedback.append(f"TPR ({tpr:.1%}) or TNR ({tnr:.1%}) meets minimum (80%) but below target (90%).")
            elif tpr >= 0.70 and tnr >= 0.70:
                stat_pts = 0.6
                stat_feedback.append(f"Sub-threshold TPR ({tpr:.1%}) or TNR ({tnr:.1%}). Below 80% minimum.")
            else:
                stat_pts = 0.3
                stat_feedback.append(f"Uncalibrated evaluator: TPR={tpr:.1%}, TNR={tnr:.1%}.")
        else:
            stat_feedback.append("Calibration metrics must be finite numbers between zero and one; missing values and booleans are not measurements.")
            stat_pts = 0.0

        domain_scores["statistical_rigor"] = EvalsRubricScore(
            name="Statistical Rigor (TPR/TNR)",
            weight=0.20,
            score=min(1.0, stat_pts),
            feedback=stat_feedback,
        )

        # 5. Rogan-Gladen Prevalence (weight: 0.15)
        rg_feedback = []
        rg_pts = 0.0
        prod = eval_spec.get("production_monitoring", {})
        if not prod:
            # Not in production monitoring phase yet
            rg_pts = 0.8
        else:
            obs = prod.get("observed_pass_rate")
            corrected = prod.get("rogan_gladen_corrected")
            claimed = prod.get("claimed_success_rate")

            if obs is not None and corrected is False and claimed == obs:
                rg_feedback.append("Naive prevalence claim: Raw observed pass rate reported as true success rate without Rogan-Gladen correction.")
                rg_pts = 0.1
            elif corrected is True or prod.get("corrected_rate") is not None:
                rate = prod.get('corrected_rate')
                ci = prod.get('ci_95')
                def finite_rate(x):
                    return type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 1
                valid = all(finite_rate(x) for x in (obs, rate, tpr, tnr))
                valid = valid and tpr + tnr > 1
                if valid:
                    expected = (obs + tnr - 1) / (tpr + tnr - 1)
                    valid = 0 <= expected <= 1 and math.isclose(rate, expected, abs_tol=1e-6)
                valid = valid and isinstance(ci, list) and len(ci) == 2 and all(finite_rate(x) for x in ci) and ci[0] <= rate <= ci[1]
                if claimed is not None:
                    valid = valid and finite_rate(claimed) and math.isclose(claimed, rate, abs_tol=1e-6)
                rg_pts = 1.0 if valid else 0.0
                if not valid:
                    rg_feedback.append('Correction needs a consistent numeric rate and interval; correction flags alone are not evidence.')
            else:
                rg_pts = 0.5
                rg_feedback.append("Production prevalence estimation lacks bias correction details.")

        domain_scores["rogan_gladen_correction"] = EvalsRubricScore(
            name="Rogan-Gladen Prevalence",
            weight=0.15,
            score=min(1.0, rg_pts),
            feedback=rg_feedback,
        )

        overall = sum(s.score * s.weight for s in domain_scores.values())
        passed = overall >= self.passing_threshold and all(
            s.score >= 0.5 for s in domain_scores.values()
        )
        status = "PASS" if passed else ("CONDITIONAL" if overall >= 0.65 else "FAIL")

        summary_notes = ['Spec lint only; supplied calibration metrics and labels are not independently verified.']
        for s in domain_scores.values():
            if s.score < 0.70:
                summary_notes.append(f"{s.name} scored low ({s.score:.2f}): " + "; ".join(s.feedback))

        return EvalsRubricReport(
            target_name=target_name,
            overall_score=overall,
            passed=passed,
            status=status,
            domain_scores=domain_scores,
            summary_notes=summary_notes,
        )


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate an AI evaluation spec or report against the L5 evals rubric.")
    parser.add_argument("--spec", "-s", type=Path, required=True, help="Path to JSON file containing eval spec/report.")
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

    evaluator = EvalsRubricEvaluator()
    report = evaluator.evaluate_eval_suite(data, target_name=args.spec.stem)

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"## 📊 L5 Evals Quality Rubric: {report.target_name}")
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
