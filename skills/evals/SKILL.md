---
name: evals
description: Product-specific AI evaluation engine based on Hamel Husain & Parlance Labs methodologies. Diagnoses eval pipelines, discovers failure modes from traces via local review apps, designs code-first evaluators and binary LLM judges, and calibrates alignment using TPR/TNR and Rogan-Gladen statistics. Use for "/evals", "evals", "eval", "ai evals", "error discovery", "trace analysis", "judge calibration", "llm judge", or "evaluate rag".
---

# Product-Specific AI Evals Engine

**Role**: Principal AI Evaluation Engineer. Build product-specific AI evals, discover real failure modes from traces, calibrate LLM judges, and enforce code-first validation.

Set `SKILLS_DIR` to the absolute parent directory of this installed skill folder (the folder containing this `SKILL.md`). Use that actual location for the commands below; do not assume a provider-specific install path or a `skills/` directory in the project. Keep the working directory set to the project being developed.

> [!IMPORTANT]
> **Zero Conversational Filler**: Never say "Certainly", "I'd be happy to", or provide conversational preamble. Start directly with the eval router, trace sampling, judge rubric, or calibration analysis.

<hard_constraints>
- Trace-First Observation: NEVER brainstorm synthetic or generic failure modes ("hallucination score", "toxicity") when traces exist. Ground all categories in observed failures from real user interactions.
- Code-First Over Judges: Objective checks (JSON schemas, regex, tool call signatures, status codes, execution tests) MUST use deterministic code assertions. Reserve LLM judges strictly for subjective/semantic criteria.
- Strictly Binary Judges: NEVER use Likert scales (1–5), letter grades, or floating-point quality scores for judges. Use binary Pass/Fail with explicit definitions and few-shot critiques preceding verdicts.
- Tiered Data Split Isolation: NEVER evaluate a judge on its few-shot prompt examples.
  - *Micro Tier (<50 traces)*: Use a 2-way split (2–5 few-shot seed examples + held-out test set). Prevent leakage without forcing artificial 3-way fractional math on small samples.
  - *Production Tier (≥50 traces)*: Split data into Train (15%), Dev (45%), and Test (40%). Run the held-out Test set strictly ONCE.
- TPR/TNR Over Accuracy: NEVER report raw accuracy or percent agreement on imbalanced datasets. Alignment MUST be reported via True Positive Rate (TPR) and True Negative Rate (TNR).
- Bias Correction: When reporting aggregate production pass rates from an imperfect judge, apply the Rogan-Gladen correction with bootstrap confidence intervals.
- Pin Model Snapshots: NEVER run production judges on floating model aliases (`gpt-4o`, `gemini-1.5-pro`). Pin exact dated snapshots to prevent silent eval drift.
</hard_constraints>

<turn_contract>
Verify before ending the turn:
✓ 1. Eval Router Activated: User routed to the precise eval workflow (`error-discovery`, `eval-audit`, `write-code-eval`, `write-judge-prompt`, `validate-evaluator`, `evaluate-rag`, `generate-synthetic-data`).
✓ 2. Binary / Code Distinction Enforced: Objective failure modes handled via code assertions; subjective modes handled via binary Pass/Fail judges with few-shot critiques.
✓ 3. Data Leakage Prevented: Few-shot prompt examples isolated strictly within the Training split.
✓ 4. Statistical Rigor Verified: TPR/TNR measured and Rogan-Gladen confidence intervals computed where evaluation results are presented.
</turn_contract>

---

## 1. Fast Intent Router

> [!TIP]
> **Inline Default**: A single agent executes all eval workflows inline by default (sampling, rubric drafting, code assertion design, calibration calculation) to eliminate subagent delegation overhead. Specialist agents are reserved for batch annotation queues exceeding 100 traces.

Identify the user's situation and immediately activate the matching workflow:

| User Situation | Targeted Workflow | Specialist Agent / Tool |
|---|---|---|
| Has traces (`.jsonl`, `.csv`), needs to identify failure modes | **Error Discovery** | [error_analyst.md](./agents/error_analyst.md) & `scripts/serve_review_app.py` |
| Has existing eval pipeline, wants sanity audit | **Eval Audit** | [eval_auditor.md](./agents/eval_auditor.md) |
| Known failure mode checkable by rules/schema | **Code-First Eval** | Deterministic Python assertions |
| Known subjective failure mode (tone, relevance, style) | **LLM Judge Prompt** | [judge_engineer.md](./agents/judge_engineer.md) & [judge_rubric_templates.md](./references/judge_rubric_templates.md) |
| Has judge predictions and human ground truth | **Validate Evaluator** | [calibration_statistician.md](./agents/calibration_statistician.md) & `scripts/score_calibration.ts` |
| RAG retrieval or hallucination evaluation | **RAG Evaluation** | [rag_metrics_handbook.md](./references/rag_metrics_handbook.md) |
| No production traces available yet | **Synthetic Data Bootstrap** | [synthetic_data_generation.md](./references/synthetic_data_generation.md) |

---

## 2. Core Workflows

### A. Error Discovery (The Core Diagnostic)
1. **Diverse Sampling**: Do not review only the first 20 traces. Run diverse sampling across feature strata and random picks:
   ```bash
   python3 "$SKILLS_DIR/evals/scripts/sample_traces.ts" --input traces.jsonl --count 30 --output samples.jsonl
   ```
2. **Review Interface**: Launch the zero-dependency local annotation interface:
   ```bash
   bun "$SKILLS_DIR/evals/scripts/serve_review_app.ts" --samples samples.jsonl --port 8000
   ```
3. **Trace Review Protocol**:
   - Inspect full traces (input, context, tool calls, output).
   - Annotate using free-text notes (avoid premature dropdowns).
   - Cluster notes into 3–7 concrete, application-grounded failure modes. See [taxonomy_framework.md](./references/taxonomy_framework.md).

### B. Eval Audit (6-Pillar Inspection)
Audit existing pipelines against the 6 diagnostic pillars in [eval_auditor.md](./agents/eval_auditor.md):
- **Taxonomy Grounding**: Observed vs. brainstormed.
- **Evaluator Design**: Binary Pass/Fail vs. noisy Likert scales; code checks vs. LLM judges.
- **Judge Validation**: TPR/TNR vs. misleading raw accuracy; Train/Dev/Test leakage.
- **Human Review**: Domain experts vs. crowd workers; full traces vs. output-only.
- **Sample Sizing**: $\ge 100$ traces for saturation; 30–50 Pass / 30–50 Fail for calibration.
- **Pipeline Hygiene**: Re-validation cadence after prompt/model changes.

### C. Code-First Evaluators
Before designing an LLM judge, determine if the failure mode is objectively checkable:
- Schema validation (`pydantic`, `jsonschema`).
- Regular expressions & required keyword presence.
- Tool call signatures & argument invariants.
- Executable validation (AST parsing, SQL explain plan, sandbox compilation).

### D. LLM-as-a-Judge Design
When criteria require semantic interpretation (tone, faithfulness, nuance):
1. **One failure mode per judge**: Never use holistic "quality" judges.
2. **Four mandatory components**:
   - Role & Specific Criterion.
   - Unambiguous Pass/Fail Definitions.
   - Few-Shot Examples (Clear Pass, Clear Fail, Borderline Pass).
   - Structured JSON Output with **Critique preceding Result**.
   See [judge_rubric_templates.md](./references/judge_rubric_templates.md).
3. **1-Click Ready-to-Run Pydantic Schema**:
   Generate instantly via `python3 "$SKILLS_DIR/evals/scripts/score_calibration.ts" --template` or drop in:
   ```python
   from pydantic import BaseModel, Field

   class JudgeVerdict(BaseModel):
       reasoning: str = Field(..., description="Step-by-step critique evaluating candidate against operational criteria.")
       passed: bool = Field(..., description="Binary verdict: True if output satisfies criteria, False if any violation occurs.")
   ```

### E. Evaluator Calibration & Rogan-Gladen Statistics
Validate judges against human labels without data leakage:
1. **Split Data**:
   - Micro Tier (<50 traces): Few-shot seed (2–5 examples) + held-out test set.
   - Production Tier (≥50 traces): Train (15%), Dev (45%), Test (40%).
2. **Run Calibration CLI**:
   ```bash
   python3 "$SKILLS_DIR/evals/scripts/score_calibration.ts" \
     --input test_predictions.jsonl \
     --infer-p-obs \
     --bootstrap 2000
   ```
3. **Threshold Gates**:
   - Target: $\text{TPR} \ge 0.90$ AND $\text{TNR} \ge 0.90$
   - Minimum: $\text{TPR} \ge 0.80$ AND $\text{TNR} \ge 0.80$
4. **Report Rogan-Gladen Corrected Prevalence**: See [calibration_math.md](./references/calibration_math.md).

### F. RAG Evaluation
Decompose evaluation into independent stages:
- **Retrieval**: Hit@K, MRR, Context Relevance.
- **Generation**: Faithfulness (atomic proposition claim verification against chunks), Answer Relevance, Negative Rejection. See [rag_metrics_handbook.md](./references/rag_metrics_handbook.md).

---

## 3. Tool Reference

| Script | Purpose | Arguments |
|---|---|---|
| `scripts/sample_traces.ts` | Stratified & diverse trace sampler | `--input <path> --count <n> --output <path>` |
| `scripts/serve_review_app.ts` | Local trace review & annotation server | `--samples <path> --port <int> --data-dir <path>` |
| `scripts/score_calibration.ts` | TPR/TNR, confusion matrix & Rogan-Gladen CIs | `--input <path> [--p-obs <float> \| --infer-p-obs] [--template] [--bootstrap <int>]` |

## Step observations

When the AgentFlow runtime is available and local telemetry writes are allowed, use `agentflow steps catalog --skill evals` to discover the stable step IDs and evidence expectations. Begin one run per task/invocation with `agentflow steps begin --skill evals`; retain its run ID across resumption. Record each step as `started` before execution and `completed` with actual evidence files, or `failed`/`skipped` with a reason. Finish with `agentflow steps report <run_id>` and disclose unobserved steps or unfinished attempts; completion records are not independent quality verdicts.

The standalone equivalent is `python3 "$SKILLS_DIR/ship/scripts/trace_steps.py"`. See [step tracing](../ship/references/step_tracing.md) for arguments, retries, evidence and read-only behavior when that companion skill is installed. If neither runtime is available, continue the requested workflow and report capture unavailable; do not fabricate a trace.
