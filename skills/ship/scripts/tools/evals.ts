#!/usr/bin/env node
/**
 * score_calibration.ts — Zero-dependency evaluator calibration and Rogan-Gladen statistics.
 *
 * Calculates:
 * 1. Confusion matrix (TP, FP, TN, FN)
 * 2. True Positive Rate (TPR / Sensitivity) and True Negative Rate (TNR / Specificity)
 * 3. Rogan-Gladen bias-corrected true success rate estimation
 * 4. Bootstrap 95% confidence intervals
 *
 * Zero external dependencies (Node.js 22+ / 25+ standard library).
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

export const PYDANTIC_JUDGE_TEMPLATE = `"""Zero-Dependency / Pydantic Binary Judge Scaffold.

Drop-in template for OpenAI, Anthropic, or Instructor structured outputs.
"""

from __future__ import annotations
from pydantic import BaseModel, Field

class JudgeVerdict(BaseModel):
    """Binary evaluation verdict with mandatory step-by-step reasoning."""
    reasoning: str = Field(
        ...,
        description="Step-by-step critique evaluating the candidate against operational criteria before deciding."
    )
    passed: bool = Field(
        ...,
        description="Binary verdict: True if output satisfies criteria, False if any violation occurs."
    )

JUDGE_SYSTEM_PROMPT = """You are a rigorous, deterministic AI evaluator.
Pinned Model: gpt-4o-2024-08-06 (or claude-3-5-sonnet-20241022)

CRITERIA:
[Define exactly ONE operational failure mode here]

PASS DEFINITION:
[Unambiguous condition for True]

FAIL DEFINITION:
[Unambiguous condition for False]

INSTRUCTIONS:
1. Provide a step-by-step critique in the \`reasoning\` field first.
2. Output \`passed = true\` or \`passed = false\`. Never output probabilities or Likert scores.
"""
`;

export function verifySplitIsolation(
  trainIds: Iterable<string>,
  testIds: Iterable<string>
): [boolean, string[]] {
  const setTrain = new Set(Array.from(trainIds, (x) => String(x).trim()).filter(Boolean));
  const setTest = new Set(Array.from(testIds, (x) => String(x).trim()).filter(Boolean));
  const overlap = Array.from(setTrain).filter((x) => setTest.has(x)).sort();

  if (overlap.length > 0) {
    const sample = overlap.slice(0, 5).join(", ");
    const extra = overlap.length > 5 ? ` (and ${overlap.length - 5} more)` : "";
    return [
      false,
      [
        `EVL-LEAK-001: Data leakage detected! Train/Dev and Test sets share ${overlap.length} IDs: ${sample}${extra}. ` +
          "Held-out test set must be strictly isolated to prevent inflated calibration.",
      ],
    ];
  }
  return [true, []];
}

export function auditJudgeRubric(promptText: string): [boolean, string[]] {
  const errors: string[] = [];
  const textLower = promptText.toLowerCase();

  const likertPatterns = [
    /\b(?:scale\s+of\s+1\s*(?:to|-)\s*[5|10])\b/,
    /\b(?:rate|rating|score)\s+(?:from\s+)?1\s*(?:to|-)\s*[5|10]\b/,
    /\b(?:1\s*[-–]\s*5|1\s*[-–]\s*10)\s*(?:stars?|scale|rating|points?)\b/,
    /\b(?:5-point|10-point)\s+scale\b/,
    /\blikert\b/,
    /\bscore\s+between\s+1\s+and\s+(?:5|10)\b/,
  ];
  for (const pat of likertPatterns) {
    if (pat.test(textLower)) {
      errors.push(
        `EVL-RUB-001: Likert / multi-point rating pattern detected ('${pat.source}'). ` +
          "Judge prompts must use binary Pass/Fail with explicit operational criteria, not fuzzy rating scales."
      );
      break;
    }
  }

  const reasoningMarkers = [
    "critique", "reasoning", "chain of thought", "thought",
    "justification", "step-by-step", "explanation", "analysis"
  ];
  if (!reasoningMarkers.some((m) => textLower.includes(m))) {
    errors.push(
      "EVL-RUB-002: Missing explicit critique-before-verdict requirement. " +
        "Prompts must instruct judge to articulate critique/reasoning prior to outputting Pass or Fail."
    );
  }

  const unpinnedPatterns = [
    /\b([a-zA-Z0-9_-]+-latest)\b/,
    /\b(gpt-4o)\b(?!\s*-\d{4})/,
    /\b(claude-3-5-sonnet)\b(?!\s*-\d{8})/,
    /\b(gemini-1\.5-pro)\b(?!\s*-\d{3})/,
  ];
  for (const pat of unpinnedPatterns) {
    const match = promptText.match(pat);
    if (match) {
      errors.push(
        `EVL-MOD-001: Potentially unpinned model alias detected ('${match[1]}'). ` +
          "Production LLM judges must pin exact model snapshot dates or hashes to prevent silent calibration drift."
      );
      break;
    }
  }

  return [errors.length === 0, errors];
}

export function normalizeLabel(val: any): "Pass" | "Fail" | null {
  if (val === null || val === undefined) return null;
  const s = String(val).trim().toLowerCase();
  if (["pass", "1", "true", "yes", "correct", "success"].includes(s)) return "Pass";
  if (["fail", "0", "false", "no", "incorrect", "failure", "error"].includes(s)) return "Fail";
  return null;
}

function parseCsv(content: string): Record<string, string>[] {
  const [head, ...rows] = content.trim().split(/\r?\n/).map((l) => l.split(",").map((c) => c.trim()));
  if (!head || !rows.length) return [];
  return rows.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
}

export function loadPairs(filePath: string): [string, string][] {
  const resolved = path.resolve(filePath);
  if (!fs.existsSync(resolved)) throw new Error(`File not found: ${resolved}`);

  const pairs: [string, string][] = [];
  const ext = path.extname(resolved).toLowerCase();
  const raw = fs.readFileSync(resolved, "utf-8");

  const labelFrom = (rec: Record<string, any>, ...keys: string[]): string | null => {
    for (const k of keys) {
      if (rec[k] !== undefined && rec[k] !== null && rec[k] !== "") {
        const norm = normalizeLabel(rec[k]);
        if (norm) return norm;
      }
    }
    return null;
  };

  const addIfValid = (rec: Record<string, any>) => {
    const h = labelFrom(rec, "human", "ground_truth", "label", "actual");
    const e = labelFrom(rec, "evaluator", "prediction", "pred", "judge");
    if (h && e) pairs.push([h, e]);
  };

  if (ext === ".jsonl" || ext === ".ndjson") {
    raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).forEach((l) => addIfValid(JSON.parse(l)));
  } else if (ext === ".csv") {
    parseCsv(raw).forEach(addIfValid);
  } else if (ext === ".json") {
    const data = JSON.parse(raw);
    if (Array.isArray(data)) {
      data.forEach(addIfValid);
    } else if (typeof data === "object" && data !== null) {
      const humans = data.human || data.ground_truth || data.labels || [];
      const evals = data.evaluator || data.predictions || data.preds || [];
      const len = Math.min(humans.length, evals.length);
      for (let i = 0; i < len; i++) {
        const h = normalizeLabel(humans[i]);
        const e = normalizeLabel(evals[i]);
        if (h && e) pairs.push([h, e]);
      }
    }
  }

  return pairs;
}

export interface CalibrationMetrics {
  total: number;
  tp: number;
  fn: number;
  tn: number;
  fp: number;
  tpr: number;
  tnr: number;
  accuracy: number;
  total_human_pass: number;
  total_human_fail: number;
}

export function computeMetrics(pairs: [string, string][]): CalibrationMetrics {
  let tp = 0, fn = 0, tn = 0, fp = 0;
  for (const [h, e] of pairs) {
    if (h === "Pass") (e === "Pass" ? tp++ : fn++);
    else (e === "Fail" ? tn++ : fp++);
  }

  const total = pairs.length;
  const total_human_pass = tp + fn;
  const total_human_fail = tn + fp;

  return {
    total,
    tp,
    fn,
    tn,
    fp,
    tpr: total_human_pass ? tp / total_human_pass : 0,
    tnr: total_human_fail ? tn / total_human_fail : 0,
    accuracy: total ? (tp + tn) / total : 0,
    total_human_pass,
    total_human_fail,
  };
}

export function roganGladenCorrection(pObs: number, tpr: number, tnr: number): number | null {
  const denom = tpr + tnr - 1.0;
  if (Math.abs(denom) < 1e-6) return null;
  return Math.max(0.0, Math.min(1.0, (pObs + tnr - 1.0) / denom));
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    let t = (a += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function bootstrapCi(
  pairs: [string, string][],
  pObs: number,
  nBootstrap: number = 2000,
  seed: number = 42
): [number | null, number | null] {
  if (!pairs || pairs.length < 5) return [null, null];

  const rng = mulberry32(seed);
  const n = pairs.length;
  const estimates: number[] = [];

  for (let i = 0; i < nBootstrap; i++) {
    const sample: [string, string][] = Array.from({ length: n }, () => pairs[Math.floor(rng() * n)]);
    const m = computeMetrics(sample);
    const denom = m.tpr + m.tnr - 1.0;
    if (Math.abs(denom) >= 1e-6) {
      estimates.push(Math.max(0.0, Math.min(1.0, (pObs + m.tnr - 1.0) / denom)));
    }
  }

  if (!estimates.length) return [null, null];
  estimates.sort((a, b) => a - b);
  return [estimates[Math.floor(0.025 * estimates.length)], estimates[Math.floor(0.975 * estimates.length)]];
}

export interface CalibrationResult {
  metrics: CalibrationMetrics;
  status: "PASS" | "NEEDS_TUNING";
  bias_correction?: {
    p_obs: number;
    inferred: boolean;
    corrected_rate: number | null;
    ci_95: [number, number] | null;
    warning: string | null;
  };
}

export function evaluateCalibration(
  pairs: [string, string][],
  pObs: number | null = null,
  nBootstrap: number = 2000,
  inferPObs: boolean = false
): CalibrationResult {
  const metrics = computeMetrics(pairs);
  const status = metrics.tpr >= 0.80 && metrics.tnr >= 0.80 ? "PASS" : "NEEDS_TUNING";
  const res: CalibrationResult = { metrics, status };

  let inferred = false;
  let effectivePObs = pObs;

  if (effectivePObs === null && inferPObs && pairs.length > 0) {
    effectivePObs = (metrics.tp + metrics.fp) / pairs.length;
    inferred = true;
  }

  if (effectivePObs !== null) {
    const clamped = Math.max(0.0, Math.min(1.0, effectivePObs));
    const thetaHat = roganGladenCorrection(clamped, metrics.tpr, metrics.tnr);
    const [ciLower, ciUpper] = bootstrapCi(pairs, clamped, nBootstrap);

    res.bias_correction = {
      p_obs: clamped,
      inferred,
      corrected_rate: thetaHat,
      ci_95: ciLower !== null && ciUpper !== null ? [ciLower, ciUpper] : null,
      warning:
        thetaHat === null
          ? "Evaluator is statistically uninformative (TPR + TNR ≈ 1.0; denominator near zero). Rogan-Gladen correction cannot estimate true prevalence reliably."
          : null,
    };
  }

  return res;
}

const pct = (num: number) => `${(num * 100).toFixed(2)}%`;

export function formatReport(result: CalibrationResult): string {
  const m = result.metrics;
  const lines = [
    "## 📊 LLM Judge Calibration & Alignment Report",
    "",
    `- **Total Labeled Samples**: ${m.total} (Pass: ${m.total_human_pass}, Fail: ${m.total_human_fail})`,
    `- **True Positive Rate (TPR / Pass Agreement)**: ${pct(m.tpr)}`,
    `- **True Negative Rate (TNR / Fail Agreement)**: ${pct(m.tnr)}`,
    `- **Raw Accuracy**: ${pct(m.accuracy)} *(Warning: Do not use for imbalanced test sets)*`,
    "",
    "### Confusion Matrix",
    "| | Human Pass | Human Fail |",
    "|---|---|---|",
    `| **Judge Pass** | ${m.tp} (TP) | ${m.fp} (FP - False Pass / Too Lenient) |`,
    `| **Judge Fail** | ${m.fn} (FN - False Fail / Too Strict) | ${m.tn} (TN) |`,
    "",
    "### Alignment Status",
  ];

  if (m.tpr >= 0.90 && m.tnr >= 0.90) {
    lines.push("✅ **EXCELLENT**: Both TPR and TNR exceed target threshold (90%+). Ready for production.");
  } else if (m.tpr >= 0.80 && m.tnr >= 0.80) {
    lines.push("⚠️ **ACCEPTABLE**: Meets minimum threshold (80%+), but inspect edge cases to reach 90%+.");
  } else {
    lines.push("❌ **UNALIGNED**: Below minimum operational threshold (80%).");
    if (m.tpr < 0.80) lines.push("  - **Low TPR**: Judge is too strict on passing traces. Clarify Pass definitions.");
    if (m.tnr < 0.80) lines.push("  - **Low TNR**: Judge is too lenient on failing traces. Strengthen Fail criteria.");
  }

  if (result.bias_correction) {
    const bc = result.bias_correction;
    const inferredNote = bc.inferred ? " *(inferred from test sample predictions)*" : "";
    lines.push(
      "",
      "### Rogan-Gladen Bias Correction (Production Prevalence)",
      `- **Observed Production Pass Rate (\`p_obs\`)**: ${pct(bc.p_obs)}${inferredNote}`
    );
    lines.push(
      bc.corrected_rate !== null
        ? `- **Corrected True Pass Rate (\`theta_hat\`)**: ${pct(bc.corrected_rate)}`
        : "- **Corrected True Pass Rate (`theta_hat`)**: ⚠️ Undefined (Judge TPR + TNR ≈ 1.0; performance is indistinguishable from random chance)"
    );
    if (bc.ci_95) {
      lines.push(`- **Bootstrap 95% Confidence Interval**: [${pct(bc.ci_95[0])}, ${pct(bc.ci_95[1])}]`);
    }
  }

  return lines.join("\n");
}

export function main(argv: string[] = process.argv.slice(2)): number {
  let inputPath: string | null = null;
  let pObs: number | null = null;
  let inferPObs = false;
  let bootstrap = 2000;
  let format: "markdown" | "json" = "markdown";
  let checkSplitPath: string | null = null;
  let auditRubricPath: string | null = null;
  let template = false;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--template") template = true;
    else if (arg === "--input" || arg === "-i") inputPath = argv[++i];
    else if (arg === "--p-obs") pObs = parseFloat(argv[++i]);
    else if (arg === "--infer-p-obs") inferPObs = true;
    else if (arg === "--bootstrap") bootstrap = parseInt(argv[++i], 10);
    else if (arg === "--format") {
      const f = argv[++i];
      if (f === "json" || f === "markdown") format = f;
    } else if (arg === "--check-split") checkSplitPath = argv[++i];
    else if (arg === "--audit-rubric") auditRubricPath = argv[++i];
  }

  if (template) {
    console.log(PYDANTIC_JUDGE_TEMPLATE);
    return 0;
  }

  if (checkSplitPath) {
    try {
      const splitData = JSON.parse(fs.readFileSync(path.resolve(checkSplitPath), "utf-8"));
      const trainIds = splitData.train || splitData.train_ids || splitData.few_shots || [];
      const testIds = splitData.test || splitData.test_ids || [];
      const [passed, errors] = verifySplitIsolation(trainIds, testIds);
      if (!passed) {
        errors.forEach((err) => console.error(`❌ ${err}`));
        return 1;
      }
      console.log(`✅ Split isolation verified: zero overlap between train (${trainIds.length}) and test (${testIds.length}) sets.`);
      if (!inputPath && !auditRubricPath) return 0;
    } catch (e: any) {
      console.error(`Error checking split manifest: ${e.message}`);
      return 1;
    }
  }

  if (auditRubricPath) {
    try {
      const promptContent = fs.readFileSync(path.resolve(auditRubricPath), "utf-8");
      const [passed, errors] = auditJudgeRubric(promptContent);
      if (!passed) {
        errors.forEach((err) => console.error(`❌ ${err}`));
        return 1;
      }
      console.log("✅ Judge prompt rubric passed anti-pattern audit.");
      if (!inputPath) return 0;
    } catch (e: any) {
      console.error(`Error auditing judge rubric: ${e.message}`);
      return 1;
    }
  }

  if (!inputPath) {
    console.error("Must specify --input (or --check-split / --audit-rubric)");
    return 2;
  }

  let pairs: [string, string][];
  try {
    pairs = loadPairs(inputPath);
  } catch (e: any) {
    console.error(`Error loading input file: ${e.message}`);
    return 1;
  }

  if (pairs.length === 0) {
    console.error("Error: No valid (human, evaluator) pairs found in input file.");
    return 1;
  }

  const result = evaluateCalibration(pairs, pObs, bootstrap, inferPObs);
  console.log(format === "json" ? JSON.stringify(result, null, 2) : formatReport(result));
  return 0;
}

if (process.argv[1] && import.meta.filename && process.argv[1] === import.meta.filename) {
  process.exit(main());
}
