# Targeted Review Modes & Intelligent Orchestration

To maintain low cognitive load and avoid wasting tokens analyzing irrelevant dimensions, the Principal Reviewer uses **Targeted Review Modes**. 

Instead of evaluating all 9 stages blindly on every diff, the orchestrator inspects the signals from `scripts/inspect_changes.sh` (or the user's explicit prompt) and activates **only the relevant review stages**.

---

## 1. Targeted Review Mode Matrix

| Change Profile | Detection Signal (`inspect_changes.sh` / Prompt) | Active Stages | Bypassed Stages (Preserves Low Cognition) | Handbook Chapter |
|---|---|---|---|---|
| **Standard Code Change** | Standard services, utilities, domain logic (no locks, APIs, or SQL) | **Correctness (1)** + **Design (4 Simplicity, 5 Maintainability, 6 Reuse, 8 SOLID, 9 Patterns)** | Concurrency (2), Migrations, Public API Contracts | [`handbook_craftsmanship.md`](./handbook_craftsmanship.md)<br>[`handbook_architecture.md`](./handbook_architecture.md) |
| **Shared State & Async** | `[!] CONCURRENCY REVIEW`<br>`[!] THREAD / ASYNC LIFECYCLE`<br>(`synchronized`, `Lock`, `ConcurrentHashMap`, `VirtualThread`, `Executor`, `asyncio`) | **Correctness (1)** + **Concurrency / Safety (2)** + **Failure / Resilience (3)** + **Design (4–9)** | Database Migrations, API Serialization (unless endpoints changed) | [`handbook_foundations.md`](./handbook_foundations.md) |
| **Database Migration** | `[!] MIGRATION REVIEW`<br>(`V*__*.sql`, `db/migration/`, `migrations/`, `schema.prisma`) | **Correctness (1)** + **Migration Integrity** + **Production Risk** | Code SOLID / Patterns, Concurrency (unless table locking) | [`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Public API & Contract** | `[!] CONTRACT REVIEW`<br>(`*Controller*`, `@RestController`, `@Get`, `@Post`, `routes.py`, `proto`) | **Correctness (1)** + **Contract & Backward Compatibility** + **Failure / Resilience (3)** | Internal Concurrency (unless async routes), DB Migrations | [`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Dependency & Build** | `[!] DEPENDENCY REVIEW`<br>(`pom.xml`, `package.json`, `requirements.txt`, `go.mod`) | **Production Risk** + **Dependency Compatibility** | Code-level SOLID, Concurrency, Algorithmic performance | [`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Financial / Precision** | `[!] FINANCIAL / PRECISION REVIEW`<br>(`BigDecimal`, `stopLoss`, `trailing_sl`, `ltp`, `qty`, `pnl`) | **Correctness (1)** + **Concurrency (2)** + **Domain/Presentation Separation** + **Production Risk** | Generic code style, speculative refactoring | [`handbook_foundations.md`](./handbook_foundations.md)<br>[`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Full Adversarial Audit** | Explicit user prompt: *"do an adversarial review"*, *"full audit"*, *"zero-blindspot review"* | **All 9 Stages + Production Risk Matrix** | None (Exhaustive baseline audit) | All Handbooks |

---

## 2. Mode Specifications & Review Focus

### Mode A: Standard Code Change (`Correctness + Design`)
- **Primary Scrutiny**:
  - Does the new/modified business logic execute accurately for all edge cases (nulls, empty lists, boundary values)?
  - Are existing codebase helpers reused instead of reinventing wheels (DRY)?
  - Is control flow flat with low indirection (Simplicity & Maintainability)?
  - Are class/method boundaries cohesive (SOLID)?

### Mode B: Shared State & Async (`Correctness + Concurrency + Design`)
- **Primary Scrutiny**:
  - Keyed lock ordering, deadlock avoidance, double release in `finally` blocks, reentrancy.
  - `ConcurrentHashMap` compound atomicity: ensure `computeIfAbsent` / `compute` is used instead of `containsKey` + `get` + `put`.
  - Virtual thread pinning: ensure carrier threads are not pinned on blocking network calls inside `synchronized` blocks.
  - Python `asyncio`: ensure background tasks have explicit exception handlers and tasks cannot be silently cancelled in critical sections.

### Mode C: Database Migration (`Correctness + Migration + Production Risk`)
- **Primary Scrutiny**:
  - Flyway / Liquibase checksum safety: never modify historical migrations.
  - Index coverage: verify new tables/columns queried on high-cardinality filters have composite indexes.
  - Table lock hazards: verify `ADD COLUMN` or index creation will not lock production tables under high write throughput.
  - Idempotency and rollback compatibility.

### Mode D: Public API & Contract (`Correctness + Contract + Compatibility`)
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

## 3. Scorecard Adaptation in Targeted Modes

When a targeted mode is selected, the scorecard marks inactive stages as `[SKIPPED - Mode Scope]` so the review remains high-signal and uncluttered:

```markdown
## 9-Stage Hierarchy Scorecard (Targeted Mode: Shared State & Async)
| Stage | Dimension | Status | Principal Engineer Assessment |
|---|---|---|---|
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
