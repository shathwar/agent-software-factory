#!/usr/bin/env python3
"""score_calibration.py — Zero-dependency evaluator calibration and Rogan-Gladen statistics.

Calculates:
1. Confusion matrix (TP, FP, TN, FN)
2. True Positive Rate (TPR / Sensitivity) and True Negative Rate (TNR / Specificity)
3. Rogan-Gladen bias-corrected true success rate estimation
4. Bootstrap 95% confidence intervals

Zero external dependencies (Python 3.10+ standard library).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import random
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


def verify_split_isolation(
    train_ids: Sequence[str] | Set[str],
    test_ids: Sequence[str] | Set[str]
) -> Tuple[bool, List[str]]:
    """Verify zero overlap between train/few-shot set and held-out test set (EVL-LEAK-001)."""
    set_train = {str(x).strip() for x in train_ids if str(x).strip()}
    set_test = {str(x).strip() for x in test_ids if str(x).strip()}
    overlap = sorted(list(set_train.intersection(set_test)))

    if overlap:
        sample = overlap[:5]
        extra = f" (and {len(overlap) - 5} more)" if len(overlap) > 5 else ""
        return False, [
            f"EVL-LEAK-001: Data leakage detected! Train/Dev and Test sets share {len(overlap)} IDs: {sample}{extra}. "
            "Held-out test set must be strictly isolated to prevent inflated calibration."
        ]
    return True, []


def audit_judge_rubric(prompt_text: str) -> Tuple[bool, List[str]]:
    """Audit judge prompt rubric for anti-patterns:
    - EVL-RUB-001: Likert scale / multi-point score instead of binary Pass/Fail.
    - EVL-RUB-002: Missing critique/reasoning step before verdict.
    - EVL-MOD-001: Unpinned model snapshot (e.g., 'latest' or unversioned aliases).
    """
    errors: List[str] = []
    text_lower = prompt_text.lower()

    # EVL-RUB-001: Detect Likert scale or non-binary rating schemes
    likert_patterns = [
        r"\b(?:scale\s+of\s+1\s*(?:to|-)\s*[5|10])\b",
        r"\b(?:rate|rating|score)\s+(?:from\s+)?1\s*(?:to|-)\s*[5|10]\b",
        r"\b(?:1\s*[-–]\s*5|1\s*[-–]\s*10)\s*(?:stars?|scale|rating|points?)\b",
        r"\b(?:5-point|10-point)\s+scale\b",
        r"\blikert\b",
        r"\bscore\s+between\s+1\s+and\s+(?:5|10)\b",
    ]
    for pat in likert_patterns:
        if re.search(pat, text_lower):
            errors.append(
                f"EVL-RUB-001: Likert / multi-point rating pattern detected ('{pat}'). "
                "Judge prompts must use binary Pass/Fail with explicit operational criteria, not fuzzy rating scales."
            )
            break

    # EVL-RUB-002: Ensure critique / reasoning before verdict
    reasoning_markers = [
        "critique", "reasoning", "chain of thought", "thought",
        "justification", "step-by-step", "explanation", "analysis"
    ]
    if not any(m in text_lower for m in reasoning_markers):
        errors.append(
            "EVL-RUB-002: Missing explicit critique-before-verdict requirement. "
            "Prompts must instruct judge to articulate critique/reasoning prior to outputting Pass or Fail."
        )

    # EVL-MOD-001: Detect unpinned model references
    unpinned_patterns = [
        r"\b([a-zA-Z0-9_-]+-latest)\b",
        r"\b(gpt-4o)\b(?!\s*-\d{4})",
        r"\b(claude-3-5-sonnet)\b(?!\s*-\d{8})",
        r"\b(gemini-1\.5-pro)\b(?!\s*-\d{3})",
    ]
    for pat in unpinned_patterns:
        match = re.search(pat, prompt_text)
        if match:
            # Check if it was followed by a snapshot identifier
            matched_str = match.group(1)
            # If matched 'latest' or unversioned model
            errors.append(
                f"EVL-MOD-001: Potentially unpinned model alias detected ('{matched_str}'). "
                "Production LLM judges must pin exact model snapshot dates or hashes to prevent silent calibration drift."
            )
            break

    return len(errors) == 0, errors


def normalize_label(val: Any) -> Optional[str]:
    """Normalize label to 'Pass' or 'Fail'."""
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in ("pass", "1", "true", "yes", "correct", "success"):
        return "Pass"
    if s in ("fail", "0", "false", "no", "incorrect", "failure", "error"):
        return "Fail"
    return None


def load_pairs(file_path: Path) -> List[Tuple[str, str]]:
    """Load (human_label, eval_label) pairs from JSON, JSONL, or CSV."""
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    pairs: List[Tuple[str, str]] = []
    suffix = file_path.suffix.lower()

    def label(record: Dict[str, Any], *keys: str) -> Optional[str]:
        return normalize_label(next((record[k] for k in keys if record.get(k) is not None and record[k] != ""), None))

    if suffix in (".jsonl", ".ndjson"):
        with open(file_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                h = label(data, "human", "ground_truth", "label", "actual")
                e = label(data, "evaluator", "prediction", "pred", "judge")
                if h is not None and e is not None:
                    pairs.append((h, e))

    elif suffix == ".csv":
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                h = label(row, "human", "ground_truth", "label", "actual")
                e = label(row, "evaluator", "prediction", "pred", "judge")
                if h is not None and e is not None:
                    pairs.append((h, e))

    elif suffix == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    h = label(item, "human", "ground_truth", "label", "actual")
                    e = label(item, "evaluator", "prediction", "pred", "judge")
                    if h is not None and e is not None:
                        pairs.append((h, e))
            elif isinstance(data, dict):
                # Check for parallel lists: {"human": [...], "evaluator": [...]}
                humans = data.get("human") or data.get("ground_truth") or data.get("labels") or []
                evals = data.get("evaluator") or data.get("predictions") or data.get("preds") or []
                for h_raw, e_raw in zip(humans, evals):
                    h = normalize_label(h_raw)
                    e = normalize_label(e_raw)
                    if h is not None and e is not None:
                        pairs.append((h, e))

    return pairs


def compute_metrics(pairs: List[Tuple[str, str]]) -> Dict[str, Any]:
    """Calculate confusion matrix, TPR, TNR, and raw accuracy."""
    tp = sum(1 for h, e in pairs if h == "Pass" and e == "Pass")
    fn = sum(1 for h, e in pairs if h == "Pass" and e == "Fail")
    tn = sum(1 for h, e in pairs if h == "Fail" and e == "Fail")
    fp = sum(1 for h, e in pairs if h == "Fail" and e == "Pass")

    total = len(pairs)
    total_human_pass = tp + fn
    total_human_fail = tn + fp

    tpr = (tp / total_human_pass) if total_human_pass > 0 else 0.0
    tnr = (tn / total_human_fail) if total_human_fail > 0 else 0.0
    accuracy = ((tp + tn) / total) if total > 0 else 0.0

    return {
        "total": total,
        "tp": tp,
        "fn": fn,
        "tn": tn,
        "fp": fp,
        "tpr": tpr,
        "tnr": tnr,
        "accuracy": accuracy,
        "total_human_pass": total_human_pass,
        "total_human_fail": total_human_fail,
    }


def rogan_gladen_correction(p_obs: float, tpr: float, tnr: float) -> Optional[float]:
    """Calculate Rogan-Gladen corrected prevalence: theta_hat = (p_obs + TNR - 1) / (TPR + TNR - 1)."""
    denominator = tpr + tnr - 1.0
    if abs(denominator) < 1e-6:
        return None
    theta = (p_obs + tnr - 1.0) / denominator
    return max(0.0, min(1.0, theta))


def bootstrap_ci(
    pairs: List[Tuple[str, str]],
    p_obs: float,
    n_bootstrap: int = 2000,
    seed: int = 42,
) -> Tuple[Optional[float], Optional[float]]:
    """Compute 95% bootstrap confidence interval for Rogan-Gladen corrected estimate."""
    if not pairs or len(pairs) < 5:
        return None, None

    rng = random.Random(seed)
    n = len(pairs)
    estimates: List[float] = []

    for _ in range(n_bootstrap):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        m = compute_metrics(sample)
        denom = m["tpr"] + m["tnr"] - 1.0
        if abs(denom) < 1e-6:
            continue
        theta = (p_obs + m["tnr"] - 1.0) / denom
        estimates.append(max(0.0, min(1.0, theta)))

    if not estimates:
        return None, None

    estimates.sort()
    lower_idx = int(0.025 * len(estimates))
    upper_idx = int(0.975 * len(estimates))
    return estimates[lower_idx], estimates[upper_idx]


def evaluate_calibration(
    pairs: List[Tuple[str, str]],
    p_obs: Optional[float] = None,
    n_bootstrap: int = 2000,
) -> Dict[str, Any]:
    """Full calibration analysis."""
    metrics = compute_metrics(pairs)
    res: Dict[str, Any] = {
        "metrics": metrics,
        "status": "PASS" if metrics["tpr"] >= 0.80 and metrics["tnr"] >= 0.80 else "NEEDS_TUNING",
    }

    if p_obs is not None:
        p_obs = max(0.0, min(1.0, p_obs))
        theta_hat = rogan_gladen_correction(p_obs, metrics["tpr"], metrics["tnr"])
        ci_lower, ci_upper = bootstrap_ci(pairs, p_obs, n_bootstrap=n_bootstrap)
        res["bias_correction"] = {
            "p_obs": p_obs,
            "corrected_rate": theta_hat,
            "ci_95": [ci_lower, ci_upper] if (ci_lower is not None and ci_upper is not None) else None,
            "warning": "Evaluator is statistically uninformative (TPR + TNR ≈ 1.0; denominator near zero). Rogan-Gladen correction cannot estimate true prevalence reliably." if theta_hat is None else None,
        }

    return res


def format_report(result: Dict[str, Any]) -> str:
    """Format markdown report."""
    m = result["metrics"]
    lines = [
        "## 📊 LLM Judge Calibration & Alignment Report",
        "",
        f"- **Total Labeled Samples**: {m['total']} (Pass: {m['total_human_pass']}, Fail: {m['total_human_fail']})",
        f"- **True Positive Rate (TPR / Pass Agreement)**: {m['tpr']:.2%}",
        f"- **True Negative Rate (TNR / Fail Agreement)**: {m['tnr']:.2%}",
        f"- **Raw Accuracy**: {m['accuracy']:.2%} *(Warning: Do not use for imbalanced test sets)*",
        "",
        "### Confusion Matrix",
        "| | Human Pass | Human Fail |",
        "|---|---|---|",
        f"| **Judge Pass** | {m['tp']} (TP) | {m['fp']} (FP - False Pass / Too Lenient) |",
        f"| **Judge Fail** | {m['fn']} (FN - False Fail / Too Strict) | {m['tn']} (TN) |",
        "",
        "### Alignment Status",
    ]

    if m["tpr"] >= 0.90 and m["tnr"] >= 0.90:
        lines.append("✅ **EXCELLENT**: Both TPR and TNR exceed target threshold (90%+). Ready for production.")
    elif m["tpr"] >= 0.80 and m["tnr"] >= 0.80:
        lines.append("⚠️ **ACCEPTABLE**: Meets minimum threshold (80%+), but inspect edge cases to reach 90%+.")
    else:
        lines.append("❌ **UNALIGNED**: Below minimum operational threshold (80%).")
        if m["tpr"] < 0.80:
            lines.append("  - **Low TPR**: Judge is too strict on passing traces. Clarify Pass definitions.")
        if m["tnr"] < 0.80:
            lines.append("  - **Low TNR**: Judge is too lenient on failing traces. Strengthen Fail criteria.")

    if "bias_correction" in result:
        bc = result["bias_correction"]
        lines.extend([
            "",
            "### Rogan-Gladen Bias Correction (Production Prevalence)",
            f"- **Observed Production Pass Rate (`p_obs`)**: {bc['p_obs']:.2%}",
        ])
        if bc["corrected_rate"] is not None:
            lines.append(f"- **Corrected True Pass Rate (`theta_hat`)**: {bc['corrected_rate']:.2%}")
        else:
            lines.append("- **Corrected True Pass Rate (`theta_hat`)**: ⚠️ Undefined (Judge TPR + TNR ≈ 1.0; performance is indistinguishable from random chance)")
        if bc.get("ci_95"):
            lines.append(f"- **Bootstrap 95% Confidence Interval**: [{bc['ci_95'][0]:.2%}, {bc['ci_95'][1]:.2%}]")

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate judge calibration and calculate Rogan-Gladen corrections.")
    parser.add_argument("--input", "-i", type=Path, default=None, help="Path to JSON, JSONL, or CSV predictions file.")
    parser.add_argument("--p-obs", type=float, default=None, help="Observed pass rate in production (0.0 to 1.0).")
    parser.add_argument("--bootstrap", type=int, default=2000, help="Number of bootstrap resamples (default: 2000).")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format.")
    parser.add_argument("--check-split", type=Path, default=None, help="Path to split manifest JSON file with train and test IDs.")
    parser.add_argument("--audit-rubric", type=Path, default=None, help="Path to judge prompt markdown/text file to audit.")

    args = parser.parse_args(argv)

    if args.check_split:
        try:
            with open(args.check_split, "r", encoding="utf-8") as f:
                split_data = json.load(f)
            train_ids = split_data.get("train", []) or split_data.get("train_ids", []) or split_data.get("few_shots", [])
            test_ids = split_data.get("test", []) or split_data.get("test_ids", [])
            passed, errors = verify_split_isolation(train_ids, test_ids)
            if not passed:
                for err in errors:
                    print(f"❌ {err}", file=sys.stderr)
                return 1
            print(f"✅ Split isolation verified: zero overlap between train ({len(train_ids)}) and test ({len(test_ids)}) sets.")
            if not args.input and not args.audit_rubric:
                return 0
        except Exception as e:
            print(f"Error checking split manifest: {e}", file=sys.stderr)
            return 1

    if args.audit_rubric:
        try:
            with open(args.audit_rubric, "r", encoding="utf-8") as f:
                prompt_content = f.read()
            passed, errors = audit_judge_rubric(prompt_content)
            if not passed:
                for err in errors:
                    print(f"❌ {err}", file=sys.stderr)
                return 1
            print("✅ Judge prompt rubric passed anti-pattern audit.")
            if not args.input:
                return 0
        except Exception as e:
            print(f"Error auditing judge rubric: {e}", file=sys.stderr)
            return 1

    if not args.input:
        parser.error("Must specify --input (or --check-split / --audit-rubric)")

    try:
        pairs = load_pairs(args.input)
    except Exception as e:
        print(f"Error loading input file: {e}", file=sys.stderr)
        return 1

    if not pairs:
        print("Error: No valid (human, evaluator) pairs found in input file.", file=sys.stderr)
        return 1

    result = evaluate_calibration(pairs, p_obs=args.p_obs, n_bootstrap=args.bootstrap)

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
