# The In-Flight Doubt Cycle: Adversarial Verification in TDD

## Overview

A confident output is not a correct one. Long coding sessions accumulate context that quietly turns unchecked assumptions into "facts" without anyone noticing. **Doubt-Driven Development** is the discipline of subjecting non-trivial implementation steps to an adversarial micro-review before marking a task complete.

This is distinct from the post-implementation **`/review`** gate:
- **`/review`**: A comprehensive, 10-stage formal audit on the complete change package before PR/delivery.
- **In-Flight Doubt**: A lightweight, in-flight adversarial posture during the Green ➔ Refactor transition. It tests non-trivial decisions while course correction is still cheap and isolated.

---

## When to Trigger a Doubt Check

Apply a Doubt Check when an implementation task introduces **non-trivial logic**:
- **Branching & State**: Introduces complex conditional branches, status transitions, or recursive algorithms.
- **Boundary Crossings**: Crosses a database, network, IPC, or third-party service boundary.
- **Unverified Invariants**: Asserts a property the compiler or type system cannot verify (thread safety, lock ordering, idempotence, atomic sequencing).
- **Data Mutations**: Modifies persistent state, database schemas, or filesystem structures.

**When NOT to trigger:**
- Routine mechanical edits (renaming, formatting, file moves, simple property getters/setters).
- Pure configuration or documentation edits.
- Straightforward one-line fixes with self-evident correctness.

---

## The 5-Step Doubt Protocol

```
┌─────────┐      ┌───────────┐      ┌─────────┐      ┌─────────────┐      ┌───────────┐
│ 1.CLAIM │ ───▶ │ 2.EXTRACT │ ───▶ │ 3.DOUBT │ ───▶ │ 4.RECONCILE │ ───▶ │ 5.ADVANCE │
└─────────┘      └───────────┘      └─────────┘      └─────────────┘      └───────────┘
```

### Step 1: CLAIM — Surface What Stands
State the hypothesis in 2–3 lines:
```text
CLAIM: "The token refresh logic handles concurrent requests without race conditions."
WHY THIS MATTERS: A race condition causes duplicate auth tokens or dropped user requests in production.
```
If you cannot express the claim compactly, you have an intuition, not a verified invariant.

### Step 2: EXTRACT — Isolate Artifact and Contract
A reviewer needs the **artifact** and the **contract**, never the author's narrative journey:
- **Artifact**: The concise diff or the specific function implementation — not the entire repository.
- **Contract**: The exact acceptance criteria, test assertions, or specification requirements it must fulfill.
- **Strip author rationale**: Never pass your internal explanations or claims to the reviewer. Handing over conclusions biases the reviewer toward agreement.

### Step 3: DOUBT — Adversarial Review
Invoke an isolated subagent (or execute a fresh mental pass with an explicit adversarial prompt):

```text
Adversarial review. Find what is wrong with this artifact.
Assume the author is overconfident. Look for:
- Unstated assumptions
- Unhandled edge cases (null, empty, negative, timeouts, out-of-order execution)
- Hidden coupling or shared mutable state
- Ways the contract could be violated
- Concurrency race conditions or missing atomic locks

Do NOT validate. Do NOT summarize. Find defects, or state explicitly that you cannot find any after thorough examination.

ARTIFACT:
<paste isolated diff or function>

CONTRACT:
<paste contract / acceptance criteria>
```

> [!IMPORTANT]
> **Pass ARTIFACT + CONTRACT only. Do NOT pass the CLAIM.**
> Handing the reviewer your claim biases it to validate your hypothesis. The reviewer must independently examine whether the artifact fulfills the contract without breaking invariants.

### Step 4: RECONCILE — Convert Findings to Failing Tests
- Evaluate each finding against the actual source code.
- If a finding identifies a genuine gap or unhandled edge case:
  - **Do NOT immediately patch the code.**
  - Write a new failing behavioral test exposing the defect (preserving the Iron Law of Test-First).
  - Observe the test fail.
  - Implement the minimal fix to satisfy the test.

### Step 5: ADVANCE — Mark Task Complete
- Once the adversarial review produces zero unresolved findings, proceed to Refactor and mark the task `- [x]` in `tasks.md`.
- Ceiling: Maximum 3 doubt iterations per task. If an architectural impasse is reached, escalate to the human user or execute a design rollback.
