# LLM-as-a-Judge Prompt & Rubric Templates

Guidelines and templates for designing high-precision, binary LLM evaluators.

---

## 1. The Four Mandatory Components

Every LLM judge prompt must include exactly these four sections:

```markdown
# Role and Criterion
You are an expert evaluator assessing whether [specific task] meets [single criterion].
Failure Mode: [Specific observed failure mode].

# Pass / Fail Definitions
PASS: [Clear, unambiguous positive criteria].
FAIL: [Concrete failure behaviors and boundaries].

# Few-Shot Examples (With Detailed Critique First)
## Example 1 (PASS)
Input: ...
Output: ...
Critique: [Detailed reasoning explicitly identifying why it passed].
Result: Pass

## Example 2 (FAIL)
Input: ...
Output: ...
Critique: [Detailed reasoning identifying specific violating phrases or logic].
Result: Fail

## Example 3 (Borderline PASS)
Input: ...
Output: ...
Critique: [Nuanced explanation of how edge-case was handled correctly].
Result: Pass

# Output Schema
Respond strictly in JSON:
{
  "critique": "string — detailed assessment citing direct quotes before reaching verdict",
  "result": "Pass" | "Fail"
}
```

---

## 2. Why Critique-First Output Is Required

Generating the `critique` before the `result` token forces the language model to perform Chain-of-Thought reasoning. If the model outputs `{"result": "Fail", ...}`, it commits to a classification token before generating any explanatory context, drastically reducing evaluation accuracy.

---

## 3. The Anti-Pattern Checklist

- ❌ **No Likert Scales (1–5)**: Humans disagree on whether an answer is a 3 or 4. Likert scales inherit annotator noise and cannot be statistically calibrated. If severity matters, use two binary judges (e.g., `minor_formatting_issue` vs. `critical_factual_error`).
- ❌ **No Holistic Judges**: Never ask "Is this response helpful?" or "Rate the overall quality." A single score conflates tone, accuracy, length, and format into an uncorrectable number.
- ❌ **No Data Leakage**: Few-shot examples must come exclusively from the **Training** split (15%). Never borrow examples from the Dev or Test sets.
- ❌ **Pin Model Snapshots**: Never run judges against rolling aliases like `gpt-4o` or `gemini-1.5-pro`. Always pin dated model versions (e.g., `gemini-1.5-pro-002`) to prevent silent drift in eval metrics.
