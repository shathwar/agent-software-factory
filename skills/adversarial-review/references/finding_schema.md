# Review Finding Contract & Schema

This document defines the formal data contract that every reviewer and specialist agent must produce for each identified issue. Standardizing this schema guarantees high signal, eliminates hand-waving, and prepares the output for automated adjudication, filtering, and aggregation by the **Review Judge**.

---

## 1. Schema Specification

Every finding must include exactly the following 11 fields without exception. This is the single source of truth for every specialist and the Judge; roles and modes must not define alternate finding formats:

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
| **`recommendation`** | String | Minimal actionable fix, replacement code, or refactoring diff. | JSON string; rendered as prose or code in Markdown |
| **`confidence`** | Number | Certainty that this is a genuine defect and not a false positive. | Finite number from 0.0 to 1.0 inclusive; labels are for Markdown presentation only |

---

## 2. Severity Classification Rules

To prevent severity inflation and noise:

- **`CRITICAL` (P0)**:
  - Guaranteed runtime crash, data corruption, financial loss, double execution, or unhandled 500 in core trading/business paths.
  - Hard blocker: Deployment MUST be halted.
- **`HIGH` (P1)**:
  - Severe concurrency race window, leak, deadlock risk under load, broken API contract, or unhandled external failure.
  - High probability of causing degradation or incorrect state under stress.
- **`MEDIUM` (P2)**:
  - Missing validation, testing gap for critical edge cases, significant code duplication (DRY violation), or clear SOLID/maintainability regression.
- **`LOW` (P3)**:
  - Suboptimal naming, minor cognitive complexity, non-critical style or minor performance suggestion.

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

```markdown
### [FINDING-001] [CRITICAL] Race condition in order lock acquisition leading to double position exit
- **Category**: Concurrency
- **Location**: [ExistingOrderService.java:L142-L148](file:///path/to/ExistingOrderService.java#L142-L148)
- **Confidence**: CERTAIN (1.0)
- **Problem**: Keyed lock is checked with `containsKey()` and then acquired via `get()`, allowing concurrent worker threads to bypass the mutex and trigger duplicate exit orders.
- **Evidence**:
  ```java
  if (!symbolLocks.containsKey(symbol)) {
      symbolLocks.put(symbol, new ReentrantLock());
  }
  symbolLocks.get(symbol).lock();
  ```
- **Impact on Live Production**: Under rapid tick ingress, two threads process square-off simultaneously, placing duplicate broker MARKET orders and leaving the account with an unintended opposite open position.
- **Recommendation**:
  ```java
  // Use atomic computeIfAbsent:
  symbolLocks.computeIfAbsent(symbol, k -> new ReentrantLock()).lock();
  ```

### [FINDING-002] [HIGH] Missing mandatory idempotency key enforcement specified in ticket PROJ-882
- **Category**: SpecAlignment
- **Location**: [PaymentWebhookController.java:L55-L80](file:///path/to/PaymentWebhookController.java#L55-L80)
- **Confidence**: CERTAIN (1.0)
- **Problem**: Ticket acceptance criteria AC-2 in PROJ-882 explicitly mandates validating and recording the `X-Idempotency-Key` header before dispatching payout events. The implemented controller ignores the header entirely.
- **Evidence**:
  ```java
  @PostMapping("/webhooks/payout")
  public ResponseEntity<Void> handlePayout(@RequestBody PayoutPayload payload) {
      // Missing check for X-Idempotency-Key header mandated by spec
      payoutService.process(payload);
      return ResponseEntity.ok().build();
  }
  ```
- **Impact on Live Production**: Payment gateway retries or network replays will execute duplicate payouts, causing financial loss.
- **Recommendation**:
  ```java
  @PostMapping("/webhooks/payout")
  public ResponseEntity<Void> handlePayout(
          @RequestHeader("X-Idempotency-Key") String idempotencyKey,
          @RequestBody PayoutPayload payload) {
      if (!idempotencyService.recordIfAbsent(idempotencyKey)) {
          return ResponseEntity.status(HttpStatus.CONFLICT).build();
      }
      payoutService.process(payload);
      return ResponseEntity.ok().build();
  }
  ```
```

---

## 5. Required Agent Output (JSON)

This is an internal exchange format. The user-facing report retains the Phase 2 template in [SKILL.md](../SKILL.md#4-standardized-output-format) and the Markdown findings in Section 4. Do not expose agent envelopes, source IDs, or disposition logs in that report.

Every specialist and the Judge returns one JSON object with exactly these top-level fields. Do not substitute YAML, prose findings, or a role-specific structure. A single enclosing JSON code fence is acceptable.

| Field | Type | Meaning |
|---|---|---|
| `reviewer` | String enum | `correctness`, `concurrency`, `design`, or `judge` |
| `status` | String enum | `complete`, `incomplete`, or `skipped`; describes coverage, not whether findings exist |
| `findings` | Array of objects | Each object has exactly the 11 fields in Section 1 |
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
  "severity": "CRITICAL",
  "category": "Concurrency",
  "file": "src/main/java/com/panchajanya/ee/service/ExistingOrderService.java",
  "line": "L142-L148",
  "title": "Race condition in order lock acquisition leading to double position exit",
  "problem": "Keyed lock checked with containsKey() before get(), creating a TOCTOU race window.",
  "evidence": "if (!symbolLocks.containsKey(symbol)) { symbolLocks.put(symbol, new ReentrantLock()); } symbolLocks.get(symbol).lock();",
  "impact": "Concurrent worker threads place duplicate broker MARKET orders under rapid tick bursts.",
  "recommendation": "symbolLocks.computeIfAbsent(symbol, k -> new ReentrantLock()).lock();",
  "confidence": 1.0
}
```

---

## 6. Multi-Agent Protocol: Role of the Principal Judge

In multi-agent execution, the [specialist protocol](./review_modes.md#3-multi-agent-review-protocol) assigns Correctness, Concurrency, and Design reviewers their active scopes. Each returns the JSON envelope in Section 5 with candidates using this same 11-field contract. The Judge checks required keys, types, enums, confidence bounds, locations, and local ID uniqueness before adjudication. Request a corrected response for malformed output; do not silently drop it or treat it as a clean review. If correction is unavailable, record incomplete coverage. Candidate IDs are local to each specialist report; the [Judge](../agents/judge.md) independently inspects relevant source before accepting any candidate, reconciles overlaps, filters confidence below 0.70, and assigns session-wide IDs. The Judge adjudicates submitted candidates only, returning the same envelope with `reviewer: "judge"` and the unchanged 11-field findings. The orchestrator renders the final report without adding unadjudicated findings.
