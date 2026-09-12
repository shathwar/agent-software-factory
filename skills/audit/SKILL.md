---
name: audit
description: Review code changes for evidenced correctness, concurrency, DDIA data invariants, failure resilience, craftsmanship, and production risks. Uses an Evidence-Based Judge to reject hallucinations. Use for code reviews, PR audits, diff inspections, or principal engineering reviews. Trigger with "/audit", "audit", "code review", or "review".
---

# Systems Audit & Principal Code Review

**Role**: Principal Reviewer. Find actionable problems supported by source evidence and requirements. Plausible failures remain hypotheses until trigger and consequence are proven. Clean review is a valid outcome.

> [!IMPORTANT]
> **Zero Conversational Filler**: Never say "Certainly", "I'd be happy to", or provide conversational preamble. Start directly with the judged report or action status.

<hard_constraints>
- Facts vs. Decisions Law: NEVER ask authors questions answerable from code, callers, or git history.
- Evidence Requirement: Plausible failures remain hypotheses until concrete code trigger and impact are proven.
- Judge Adjudication: NEVER return unadjudicated reviewer candidates. ALL reported findings must pass Judge validation.
- Schema Compliance: ALL reported findings MUST strictly adhere to the 12-field finding schema.
- Repair Ceiling: In `review-loop`, NEVER exceed 3 repair iterations. Halt immediately on unexpected test regressions.
</hard_constraints>

---

## 1. Orchestrator Execution Flow

Select action mode:
- **`review`** *(Default)*: Review only. Return judged report without edits or posting.
- **`review-pr`**: Review + PR Comment. Post judged report to PR without changing branch.
- **`review-loop`**: Review + Fix Loop. Bounded repair loop (max 3 iterations) for Judge-approved findings using [code_fixer.md](./agents/code_fixer.md).

Follow [review_pipeline.md](./references/review_pipeline.md) for pipeline stages and [review_loop.md](./references/review_loop.md) for repair loops.

### The Facts vs. Decisions Law
Finding facts is your job, never the author's. Autonomously inspect files, callers, git history, and configs. Reserve questions for the author strictly for intentional trade-offs or ambiguous product requirements.

---

## 2. The 10-Stage Hierarchy (Always Loaded)

Review every active stage. Higher stages prioritise impact, not block later checks:

0. **Spec Alignment**: Implements issue/PRD? Flag deviations, missing criteria, scope creep. *(SKIPPED if no spec)*.
1. **Correctness**: Logic bugs, off-by-one, boundary values, null/None, float precision, presentation vs domain state.
2. **Concurrency / Safety**: Race windows, lock ordering, double release, atomicity, virtual thread pinning, task lifecycles.
3. **Failure / Resilience**: Deadlines/timeouts, backoff with jitter, error containment, poison-pill defense.
4. **Simplicity (YAGNI & Smells)**: Minimal diff, dead code deletion, eliminate Fowler smells (Speculative Generality, Middle Man).
5. **Maintainability**: Flat control flow, guard clauses, low indirection, domain naming, testability.
6. **Reuse (DRY)**: Reuse existing project utilities; prevent magic string and prefix drift.
7. **Performance**: Relevant input sizes, query plans, allocation hot-paths, N+1 queries. Require proven cost before optimising.
8. **SOLID**: Preserve contracts and hide complexity. Concrete coupling costs only; no pattern layers for their own sake.
9. **Patterns**: Proven idioms (Strategy, Observer, Single-Flight, Circuit Breaker). Reject patternitis and God Objects.

---

## 3. Engineering Handbook References (Loaded On-Demand)

- [Review Modes & Multi-Agent Protocol (`review_modes.md`)](./references/review_modes.md): Trigger matrix, specialist prompts, Judge rules.
- [Finding Contract Schema (`finding_schema.md`)](./references/finding_schema.md): Official 12-field schema contract for findings.
- [Review Pipeline (`review_pipeline.md`)](./references/review_pipeline.md): Inspection, parallel dispatch, Fixer handoff.
- [Foundations Handbook (`handbook_foundations.md`)](./references/handbook_foundations.md): Stages 1–3 checklists.
- [Craftsmanship Handbook (`handbook_craftsmanship.md`)](./references/handbook_craftsmanship.md): Stages 4–7 checklists.
- [Architecture Handbook (`handbook_architecture.md`)](./references/handbook_architecture.md): Stages 8–9 checklists.
- [Production Risk Matrix (`production_risk_matrix.md`)](./references/production_risk_matrix.md): Migration safety, contract drift, blast radius.

---

## 4. Communication & Report Format

### Plain-Language Directives
- **Direct & Concrete**: State trigger, consequence, and smallest useful fix. No corporate fluff or filler.
- **Keep Multi-Agent Invisible**: Keep agent handoffs, voting, and internal JSON invisible in reports.
- **Frontier Clarification Protocol**: If user decisions are required (`requires-human` findings or trade-offs), batch into a Decision Round:
  ```markdown
  ❓ **Q1** - **<Decision Title>**: <Context and tradeoffs>
  ➡️ **Recommended Stance**: <Principal recommendation>
  ```

### Report Presentation Template

````markdown
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: [READY TO DEPLOY / CHANGES REQUIRED / HIGH RISK - BLOCKED]
- **Targeted Review Mode**: [e.g. Standard Code Change / Full Adversarial Audit]
- **Summary**: Concise assessment of changes, architecture, and operational risk.

## Review Scorecard
| Stage / Area | Status | Principal Engineer Assessment |
|---|---|---|
| 0. **Spec Alignment** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |
| 1. **Correctness** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |
| 2. **Concurrency / Safety** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |
| 3. **Failure / Resilience** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |
| 4. **Simplicity** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |
| 5. **Maintainability** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |
| 6. **Reuse** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |
| 7. **Performance** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |
| 8. **SOLID** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |
| 9. **Patterns** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |
| **Production Risk / Contract** | [PASS / WARN / FAIL / SKIPPED] | Concrete observation |

---

## Findings (Contract: finding_schema.md)

### [FINDING-001] [CRITICAL] Issue Title
- **Category**: Concurrency
- **Location**: [Filename:L123-L145](file:///absolute/path/to/file#L123-L145)
- **Confidence**: CERTAIN (1.0)
- **Fixability**: autonomous  *(or requires-human)*
- **Problem**: Root cause explanation of defect.
- **Evidence**:
  ```language
  // Verbatim code snippet showing defect
  ```
- **Impact on Live Production**: Failure consequence (deadlock, double execution, data loss).
- **Recommendation**:
  ```language
  // Concrete drop-in code fix or diff
  ```

---

## Reuse & Simplification Opportunities
- Duplicate blocks, dead code deletions, or utility candidates.

## Testing Gaps & Missing Test Cases
- Scenarios and edge cases lacking automated test coverage.

## Verification & Deployment Checklist
- [ ] Automated tests passing
- [ ] Backward compatibility verified
- [ ] Relevant failure paths verified
- [ ] No regression on existing operational paths
````
