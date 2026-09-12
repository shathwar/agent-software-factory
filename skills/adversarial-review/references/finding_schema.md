# Review Finding Contract & Schema

This document defines the formal data contract that every reviewer and specialist agent must produce for each identified issue. The common fields support consistent adjudication, filtering, and aggregation by the **Review Judge**; they do not establish that a finding is true.

---

## 1. Schema Specification

Every finding must include exactly the following 12 fields without exception. This is the single source of truth for every specialist and the Judge; roles and modes must not define alternate finding formats:

| Field | Type | Description | Allowed Values / Format |
|---|---|---|---|
| **`id`** | String | Unique within a specialist report; the Judge assigns session-wide IDs. | `FINDING-001`, `FINDING-002`, ... |
| **`severity`** | Enum | The critical level and urgency of the finding. | `CRITICAL` (P0), `HIGH` (P1), `MEDIUM` (P2), `LOW` (P3) |
| **`category`** | Enum | The specific stage of the 10-stage engineering hierarchy. | `SpecAlignment`, `Correctness`, `Concurrency`, `Failure/Resilience`, `Simplicity`, `Maintainability`, `Reuse`, `Performance`, `SOLID`, `Patterns`, `ProductionRisk` |
| **`file`** | String | Repository-relative path to the inspected file; plain text in JSON, linked in final Markdown. | `src/main/java/.../Service.java` |
| **`line`** | String | Exact line number or range containing the issue. | `L120` or `L120-L135` |
| **`title`** | String | Crisp, one-line summary of the defect. | 5–12 words, domain-specific |
| **`problem`** | String | Root cause technical explanation of the flaw. | Exact breakdown of the buggy logic or architectural defect |
| **`evidence`** | String | Verbatim source excerpt supporting the defect; do not insert explanatory comments into the excerpt. | JSON string; rendered as a code block in Markdown |
| **`impact`** | String | Concrete failure scenario in live production. | Real-world blast radius (outage, race, 500, financial loss, data corruption) |
| **`recommendation`** | String | Minimal actionable fix, or the decision needed and possible approaches for `requires-human`. | JSON string; rendered as prose or code in Markdown |
| **`confidence`** | Number | Certainty that this is a genuine defect and not a false positive. | Finite number from 0.0 to 1.0 inclusive; labels are for Markdown presentation only |
| **`fixability`** | Enum | Whether the accepted fix can be implemented without a human decision. | `autonomous` or `requires-human` |

### Fixability rules

- `autonomous`: Existing requirements and contracts determine a safe fix within the authorised scope. Routine implementation choices remain with the Fixer.
- `requires-human`: The fix depends on an unresolved architectural or business decision, such as choosing public behavior, ownership boundaries, or a data-retention policy. In `recommendation`, state the decision needed, the reason, and concrete possible approaches with tradeoffs; do not present one as already chosen.

Every reviewer supplies this field and the Judge validates it. Confidence measures whether the defect exists; fixability measures whether its resolution needs a human decision. A certain, high-severity finding can still require a human. Judge approval alone does not make it autonomous. Missing or invalid fixability is malformed input, never an implicit `autonomous` default.

A `requires-human` finding remains in the approved findings and report. The Fixer makes no code changes for it and returns the decision request defined in [code_fixer.md](../agents/code_fixer.md#human-decision-required). Resume only after the human supplies the decision and the orchestrator obtains an updated Judge-approved finding reflecting it.

---

## 2. Severity Classification Rules

Rate the demonstrated impact and urgency separately from confidence and fixability:

- **CRITICAL (P0)**: An immediate, broadly affecting failure or irreversible harm on a core path, supported without speculative workload assumptions.
- **HIGH (P1)**: A serious reachable defect requiring prompt correction, with the triggering conditions and affected users identified.
- **MEDIUM (P2)**: A bounded correctness or maintenance problem worth fixing, with concrete consequences.
- **LOW (P3)**: A small but actionable cost. Omit formatting preferences and speculative optimisations.

An exception or a SOLID label does not determine severity. Test gaps belong in the existing testing section unless they substantiate a separate defect. Review verdicts advise the user; they do not authorise deployment actions.

---

## 3. Confidence Scoring Guidelines

The `confidence` score enables the **Review Judge** to filter out speculative or phantom issues:

- **`CERTAIN` (1.0)**: Traced end-to-end. The flaw is mathematically, logically, or syntactically demonstrable directly from the inspected code.
- **`HIGH` (0.85–0.99)**: The defect will trigger given reasonable real-world conditions (e.g. high concurrency, network latency, external API failure). Call paths and dependencies were fully verified.
- **`MEDIUM` (0.60–0.84)**: Probable defect, but depends on uninspected external caller invariants or runtime configuration.
- **`LOW` (<0.60)**: Speculative concern or theoretical observation. (Should generally be omitted or tagged as an open question).

---

## 4. Canonical Finding Format (Markdown Presentation)

When rendering findings in the final review report, reviewers must adhere strictly to this format:

````markdown
### [FINDING-001] [MEDIUM] Empty input crashes instead of returning zero
- **Category**: Correctness
- **Location**: [average.py:L2](/absolute/path/to/average.py:2)
- **Confidence**: CERTAIN (1.0)
- **Fixability**: autonomous
- **Problem**: The documented contract returns zero for an empty input, but this expression divides by zero.
- **Evidence**:
  ```python
  return sum(values) / len(values)
  ```
- **Impact on Live Production**: A request with no values fails instead of producing the required result.
- **Recommendation**:
  ```python
  return sum(values) / len(values) if values else 0
  ```
````

This illustration assumes the stated empty-input contract and a sized numeric collection. Actual findings must cite inspected source and the applicable contract. For `requires-human`, the recommendation gives the unresolved decision and supported options rather than guessed replacement code.

---

## 5. Required Agent Output (JSON)

This is an internal exchange format. The user-facing report retains the Phase 2 template in [SKILL.md](../SKILL.md#4-standardized-output-format) and the Markdown findings in Section 4. Do not expose agent envelopes, source IDs, or disposition logs in that report.

Every specialist and the Judge returns one JSON object with exactly these top-level fields. Do not substitute YAML, prose findings, or a role-specific structure. A single enclosing JSON code fence is acceptable.

| Field | Type | Meaning |
|---|---|---|
| `reviewer` | String enum | `correctness`, `concurrency`, `design`, or `judge` |
| `status` | String enum | `complete`, `incomplete`, or `skipped`; describes coverage, not whether findings exist |
| `findings` | Array of objects | Each object has exactly the 12 fields in Section 1 |
| `coverage` | Array of strings | Assigned checks and files actually inspected; explain incomplete or skipped work |
| `questions` | Array of strings | Unresolved evidence or context needed; no speculative findings |
| `routing_notes` | Array of strings | Incidental out-of-scope location and reason for the orchestrator to route |

Use empty arrays when there are no entries. Never omit fields, use nulls, or add role-specific keys. All finding string fields must be nonempty; use the exact enum spellings, repository-relative paths, `L<number>` or `L<start>-L<end>` locations, and unique local `FINDING-NNN` IDs. Encode multiline source or fixes as JSON strings with escaped newlines. Do not invent evidence to fill a required field; keep an unsubstantiated concern in `questions`.

A completed review with no findings looks like this (the coverage text must describe actual work):

```json
{
  "reviewer": "correctness",
  "status": "complete",
  "findings": [],
  "coverage": ["Reviewed assigned validation and failure paths in src/Validator.java."],
  "questions": [],
  "routing_notes": []
}
```

If dispatched work cannot be completed, return `incomplete` with the actual coverage and missing context. `skipped` is reserved for no applicable assigned scope; the orchestrator normally records this without dispatching the specialist. Neither missing coverage nor an empty findings array implies a passing review.

The following is an example of one object inside `findings`:


```json
{
  "id": "FINDING-001",
  "severity": "MEDIUM",
  "category": "Correctness",
  "file": "average.py",
  "line": "L2",
  "title": "Empty input crashes instead of returning zero",
  "problem": "The documented contract returns zero for empty input, but this expression divides by zero.",
  "evidence": "return sum(values) / len(values)",
  "impact": "A request with no values fails instead of producing the required result.",
  "recommendation": "return sum(values) / len(values) if values else 0",
  "confidence": 1.0,
  "fixability": "autonomous"
}
```

---

## 6. Multi-Agent Protocol: Role of the Principal Judge

In multi-agent execution, the [specialist protocol](./review_modes.md#3-multi-agent-review-protocol) assigns Correctness, Concurrency, and Design reviewers their active scopes. Each returns the JSON envelope in Section 5 with candidates using this same 12-field contract. The Judge checks required keys, types, enums, confidence bounds, locations, and local ID uniqueness before adjudication. Request a corrected response for malformed output; do not silently drop it or treat it as a clean review. If correction is unavailable, record incomplete coverage. Candidate IDs are local to each specialist report; the [Judge](../agents/review_judge.md) independently inspects relevant source before accepting any candidate, reconciles overlaps, filters confidence below 0.70, and assigns session-wide IDs. The Judge adjudicates submitted candidates only, returning the same envelope with `reviewer: "judge"` and the unchanged 12-field findings. The orchestrator renders the final report without adding unadjudicated findings.

## 7. Finding lifecycle across rounds

The [review loop](./review_loop.md) stores OPEN, CONFIRMED, FIXED, VERIFIED, REJECTED, and HUMAN_DECISION in a separate internal ledger. These are not additional finding fields. Use its stable ID mapping across reports; do not restart final numbering each round. Reviewer and Judge output envelopes remain unchanged. The orchestrator records evidence-backed transitions from their findings and coverage records.

For Phase 5, regression attribution and optionality are also ledger metadata; the 12-field finding object is unchanged. `requires-human` stops the entire repair loop under its hard human boundary. A genuinely optional finding remains confirmed and disclosed, never relabeled rejected or verified merely to satisfy convergence.
