# Targeted Review Modes & Intelligent Orchestration

To maintain low cognitive load and avoid wasting tokens analyzing irrelevant dimensions, the Principal Reviewer uses **Targeted Review Modes** and adaptive execution strategies. 

Instead of evaluating all 10 stages blindly on every diff, the orchestrator inspects the signals from `scripts/inspect_changes.sh` (or the user's explicit prompt) and activates **only the relevant review stages**.

---

## 1. Targeted Review Mode Matrix

| Change Profile | Detection Signal (`inspect_changes.sh` / Prompt) | Active Stages | Bypassed Stages (Preserves Low Cognition) | Handbook Chapter |
|---|---|---|---|---|
| **Standard Code Change** | Standard services, utilities, domain logic (no locks, APIs, or SQL) | **Spec (0)** + **Correctness (1)** + **Design (4 Simplicity & Smells, 5 Maintainability, 6 Reuse, 8 SOLID, 9 Patterns)** | Concurrency (2), Migrations, Public API Contracts | [`handbook_craftsmanship.md`](./handbook_craftsmanship.md)<br>[`handbook_architecture.md`](./handbook_architecture.md) |
| **Shared State & Async** | `[!] CONCURRENCY REVIEW`<br>`[!] THREAD / ASYNC LIFECYCLE`<br>(`synchronized`, `Lock`, `ConcurrentHashMap`, `VirtualThread`, `Executor`, `asyncio`) | **Spec (0)** + **Correctness (1)** + **Concurrency / Safety (2)** + **Failure / Resilience (3)** + **Design (4–9)** | Database Migrations, API Serialization (unless endpoints changed) | [`handbook_foundations.md`](./handbook_foundations.md) |
| **Database Migration** | `[!] MIGRATION REVIEW`<br>(`V*__*.sql`, `db/migration/`, `migrations/`, `schema.prisma`) | **Spec (0)** + **Correctness (1)** + **Migration Integrity** + **Production Risk** | Code SOLID / Patterns, Concurrency (unless table locking) | [`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Public API & Contract** | `[!] CONTRACT REVIEW`<br>(`*Controller*`, `@RestController`, `@Get`, `@Post`, `routes.py`, `proto`) | **Spec (0)** + **Correctness (1)** + **Contract & Backward Compatibility** + **Failure / Resilience (3)** | Internal Concurrency (unless async routes), DB Migrations | [`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Dependency & Build** | `[!] DEPENDENCY REVIEW`<br>(`pom.xml`, `package.json`, `requirements.txt`, `go.mod`) | **Production Risk** + **Dependency Compatibility** | Code-level SOLID, Concurrency, Algorithmic performance | [`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Financial / Precision** | `[!] FINANCIAL / PRECISION REVIEW`<br>(`BigDecimal`, `stopLoss`, `trailing_sl`, `ltp`, `qty`, `pnl`) | **Spec (0)** + **Correctness (1)** + **Concurrency (2)** + **Domain/Presentation Separation** + **Production Risk** | Generic code style, speculative refactoring | [`handbook_foundations.md`](./handbook_foundations.md)<br>[`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Full Adversarial Audit** | Explicit user prompt: *"do an adversarial review"*, *"full audit"*, *"zero-blindspot review"* | **All 10 Stages + Production Risk Matrix** | None (Exhaustive baseline audit) | All Handbooks |

*Note on Stage 0 (Spec Alignment): If an issue key or spec document is detected, Stage 0 is evaluated in all modes. If no spec exists, Stage 0 is marked `[SKIPPED - No Spec Provided]` without blocking technical review.*

---

## 2. Mode Specifications & Review Focus

### Mode A: Standard Code Change (`Spec + Correctness + Design`)
- **Primary Scrutiny**:
  - Does the implementation match the originating ticket or PRD acceptance criteria?
  - Does the new/modified business logic execute accurately for all edge cases (nulls, empty lists, boundary values)?
  - Are existing codebase helpers reused instead of reinventing wheels (DRY)?
  - Is control flow flat with low indirection (Simplicity & Maintainability)?
  - Are class/method boundaries cohesive (SOLID)?

### Mode B: Shared State & Async (`Spec + Correctness + Concurrency + Design`)
- **Primary Scrutiny**:
  - Keyed lock ordering, deadlock avoidance, double release in `finally` blocks, reentrancy.
  - `ConcurrentHashMap` compound atomicity: ensure `computeIfAbsent` / `compute` is used instead of `containsKey` + `get` + `put`.
  - Virtual thread pinning: ensure carrier threads are not pinned on blocking network calls inside `synchronized` blocks.
  - Python `asyncio`: ensure background tasks have explicit exception handlers and tasks cannot be silently cancelled in critical sections.

### Mode C: Database Migration (`Spec + Correctness + Migration + Production Risk`)
- **Primary Scrutiny**:
  - Flyway / Liquibase checksum safety: never modify historical migrations.
  - Index coverage: verify new tables/columns queried on high-cardinality filters have composite indexes.
  - Table lock hazards: verify `ADD COLUMN` or index creation will not lock production tables under high write throughput.
  - Idempotency and rollback compatibility.

### Mode D: Public API & Contract (`Spec + Correctness + Contract + Compatibility`)
- **Primary Scrutiny**:
  - Backward compatibility: do existing clients (mobile apps, web UIs, peer microservices) break if fields are added or removed?
  - HTTP status codes: verify 400 for bad input, 404 for missing entities, 401/403 for auth failures — never leak unhandled 500s.
  - Serialization: in GraalVM Native Image or Micronaut Serde, verify new DTOs are annotated with `@Serdeable` and `@Introspected`.

### Mode E: Dependency & Build (`Production Risk + Compatibility`)
- **Primary Scrutiny**:
  - Did the dependency bump introduce transitive conflicts or CVE security advisories?
  - Are new third-party libraries strictly necessary, or does the language standard library already solve the problem (Ponytail / YAGNI)?
  - License compatibility check (e.g. avoiding viral GPL in proprietary services).

---

## 3. Parallel Dual-Agent Review Protocol (Large PRs >400 Lines)

When a pull request diff exceeds 400 lines or the user specifies parallel execution (e.g., `/adversarial-review --parallel`), the Principal Orchestrator dispatches two sub-agents concurrently via `invoke_subagent`:

```text
                           Principal Reviewer (Orchestrator)
                                           │
                     ┌─────────────────────┴─────────────────────┐
                     ▼                                           ▼
         [Sub-Agent A: Spec Verifier]               [Sub-Agent B: Systems Auditor]
         • Model: inherit                           • Model: inherit
         • Input: Diff + Commit Log + Spec Source   • Input: Diff + Test Map + Callers
         • Output: Stage 0 Findings                 • Output: Stages 1–3 + Production Risk
                     │                                           │
                     └─────────────────────┬─────────────────────┘
                                           ▼
                           Principal Reviewer (Judge & Synthesis)
                           • Cross-verifies evidence against files
                           • Deduplicates overlapping findings
                           • Enforces finding_schema.md contract
                           • Assembles final scorecard & verdict
```

### Sub-Agent Prompts:

**Sub-Agent A (Spec Verifier)**:
> "You are the Spec Verifier. Compare the provided diff and commit log against the originating spec/issue. Report: (a) missing or partial acceptance criteria; (b) unrequested scope creep or premature abstractions; (c) logic that seems implemented but contradicts domain rules in the spec. Quote spec lines where applicable. Format each finding strictly according to finding_schema.md with category: SpecAlignment. Keep report concise (<400 words)."

**Sub-Agent B (Systems Auditor)**:
> "You are the Systems Auditor. Perform an adversarial technical audit on the provided diff and full file contents. Evaluate Stage 1 (Correctness), Stage 2 (Concurrency/Safety), Stage 3 (Failure Resilience), and Production Risk. Verify lock ordering, map atomicity, virtual thread pinning, timeouts, unhandled errors, and caller blast radius. Format each finding strictly according to finding_schema.md. Keep report concise (<400 words)."

---

## 4. Scorecard Adaptation in Targeted Modes

When a targeted mode is selected, the scorecard marks inactive stages as `[SKIPPED - Mode Scope]` so the review remains high-signal and uncluttered:

```markdown
## 10-Stage Hierarchy Scorecard (Targeted Mode: Shared State & Async)
| Stage | Dimension | Status | Principal Engineer Assessment |
|---|---|---|---|
| 0 | **Spec Alignment** | PASS | Implements trailing stop-loss ticket PROJ-412 requirements |
| 1 | **Correctness** | PASS | Edge cases and null checks verified in ExistingOrderService |
| 2 | **Concurrency / Safety** | WARN | Lock acquisition races with map.computeIfAbsent in TickTrailEvaluator |
| 3 | **Failure / Resilience** | PASS | Timeouts present on external broker calls |
| 4 | **Simplicity** | PASS | Minimal diff; no speculative abstractions added |
| 5 | **Maintainability** | PASS | Domain-specific naming adopted |
| 6 | **Reuse** | PASS | Reuses existing IndiaMarket timezone helpers |
| 7 | **Performance** | PASS | No allocations in tick hot-path |
| 8 | **SOLID** | PASS | TickTrailEvaluator successfully separated from ExistingOrderService |
| 9 | **Patterns** | PASS | Strategy pattern applied for dispatching |
| — | **Database Migrations** | SKIPPED | No database migrations in this change |
| — | **Public API Contract** | SKIPPED | No REST/API controller changes in this change |
```
