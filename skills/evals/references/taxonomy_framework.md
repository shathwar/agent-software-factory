# Failure Mode Taxonomy & Error Discovery Framework

This framework provides concrete principles for discovering, labeling, and categorizing failure modes in production AI systems, derived from the Parlance Labs AI Evals methodology.

---

## 1. Observed vs. Brainstormed Failure Modes

> **The Golden Rule**: Build evals from *observed* failures in real traces, never from *brainstormed* academic categories.

| Anti-Pattern: Brainstormed Taxonomy | Recommended: Observed Grounded Taxonomy |
|---|---|
| "Hallucination score" (vague, unactionable) | "Fabricated property feature not present in MLS context" |
| "Toxicity" (irrelevant for internal B2B app) | "Mismatched tone: casual slang sent to enterprise executive" |
| "Helpfulness rating (1-5)" (subjective noise) | "Missing constraint: recommended out-of-stock product" |
| "Coherence / Fluency" (LLMs already fluent) | "Schema failure: returned invalid JSON in tool arguments" |

---

## 2. The 5 Sampling Strategies for Error Discovery

To identify true failure modes without sampling bias, draw from multiple buckets:

1. **Random Sampling**: Always sample 30–40% purely at random. This uncovers unexpected edge cases ("unknown unknowns").
2. **Feature Stratification**: Group by structural characteristics:
   - Input/output length (very short < 50 chars, long > 2,000 chars)
   - Number of conversation turns
   - Number of tool calls or API invocations
   - Latency outliers or token counts
3. **Cluster Representatives**: Cluster embeddings or normalized features into 6–10 clusters; review 1–2 items closest to each centroid.
4. **Error & Status Markers**: Traces containing 4xx/5xx status codes, fallback completions, tool execution failures, or timeouts.
5. **Direct User Feedback**: Thumbs-down signals, customer support tickets, or explicit user complaints.

---

## 3. Human Review & Annotation Protocol

- **Target Sample Size**: Review approximately ~100 diverse traces to reach saturation (diminishing new failure types discovered).
- **Free-Text Notes Only**: During initial error discovery, **do not** force annotators into predefined dropdowns or quality scales. Allow domain experts to record free-form descriptions of what went wrong.
- **Inspect Full Traces**: Never evaluate the final output in isolation. Inspect the input prompt, retrieved context documents, tool arguments, tool responses, and intermediate reasoning turns.
- **Synthesis**: The agent clusters free-text notes into an initial taxonomy of 3–7 distinct, actionable failure categories.
