# Review Finding Contract & Schema

This document defines the formal data contract that every reviewer (and future specialist agents) must produce for each identified issue. Standardizing this schema guarantees high signal, eliminates hand-waving, and prepares the output for automated adjudication, filtering, and aggregation by a future **Judge** agent.

---

## 1. Schema Specification

Every finding must include the following 11 fields without exception:

| Field | Type | Description | Allowed Values / Format |
|---|---|---|---|
| **`id`** | String | Unique finding identifier within the review session. | `FINDING-001`, `FINDING-002`, ... |
| **`severity`** | Enum | The critical level and urgency of the finding. | `CRITICAL` (P0), `HIGH` (P1), `MEDIUM` (P2), `LOW` (P3) |
| **`category`** | Enum | The specific stage of the 10-stage engineering hierarchy. | `SpecAlignment`, `Correctness`, `Concurrency`, `Failure/Resilience`, `Simplicity`, `Maintainability`, `Reuse`, `Performance`, `SOLID`, `Patterns`, `ProductionRisk` |
| **`file`** | String | Workspace-relative path to the inspected file (with clickable link). | `src/main/java/.../Service.java` |
| **`line`** | String | Exact line number or range containing the issue. | `L120` or `L120-L135` |
| **`title`** | String | Crisp, one-line summary of the defect. | 5–12 words, domain-specific |
| **`problem`** | String | Root cause technical explanation of the flaw. | Exact breakdown of the buggy logic or architectural defect |
| **`evidence`** | Code block | Verbatim code snippet from the inspected file showing the defect. | Fenced code block with line numbers if applicable |
| **`impact`** | String | Concrete failure scenario in live production. | Real-world blast radius (outage, race, 500, financial loss, data corruption) |
| **`recommendation`** | Code / Text | Production-ready, minimal drop-in code fix or refactoring diff. | Minimal sound replacement diff |
| **`confidence`** | Enum / Float | Certainty that this is a genuine defect and not a false positive. | `CERTAIN` (1.0), `HIGH` (0.85+), `MEDIUM` (0.6+), `LOW` (<0.6) |

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

The `confidence` score enables the future **Judge** agent to filter out speculative or phantom issues:

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

## 5. Structured Data Representation (JSON / YAML)

For programmatic consumption by the **Judge** or automated CI pipelines:

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

In Parallel Dual-Agent execution:
1. **Spec Verifier Sub-Agent**: Inspects originating issue/PRD and git diff, producing findings restricted to `category: SpecAlignment`.
2. **Systems Auditor Sub-Agent**: Inspects correctness, concurrency, failure resilience, and production risk across the codebase.
3. **The Principal Judge**:
   - Ingests all structured findings from both sub-agents.
   - Deduplicates any overlapping findings (e.g. where a spec requirement bug also triggers a correctness failure).
   - Verifies evidence against full file contents.
   - Filters out phantom or speculative findings where `confidence < 0.70`.
   - Compiles the final authoritative report without allowing one axis to suppress the other.
