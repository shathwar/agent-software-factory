# Production Engineering Rules for Coding Agents

Universal high-density engineering instructions for AI coding agents. Grounded in classic systems engineering: *Designing Data-Intensive Applications* (Kleppmann), *Release It!* (Nygard), and *A Philosophy of Software Design* (Ousterhout).

---

## 1. Anti-Bloat & Simplicity (`simplify`)
- **Laziness Ladder**: 1. YAGNI ➔ 2. Codebase reuse ➔ 3. Standard library ➔ 4. Native platform ➔ 5. Installed deps ➔ 6. One-liner ➔ 7. Minimum code.
- **Deep Modules (Ousterhout)**: Narrow interfaces hiding substantial complexity. Reject shallow 5-line pass-through wrappers.
- **Define Errors Out of Existence**: Design APIs so boundary states (e.g., deleting an absent record, empty slice) are valid no-ops rather than exceptions.
- **Zero Unrequested Abstractions**: No speculative interfaces or factories for single implementations.
- **Debt Tracking**: Mark intentional shortcuts: `// simplify: <desc> | Ceiling: <limit> | Upgrade: <action>`.

---

## 2. Test-Driven Development (`tdd`)
- **Iron Law**: Zero production code written without a prior failing behavioral test.
- **Dual-Speed Testing**:
  - *Tier 1 (Fast Domain)*: Pure business rules using in-memory fakes (< 50ms).
  - *Tier 2 (Wire & Persistence)*: Real queries and transactions using ephemeral databases (SQLite memory, Testcontainers) (< 2s). Never mock SQL clients or database engines.
- **Brownfield Characterization**: For untested legacy code, snapshot input/output ("Golden Master") before applying TDD.
- **Behavior Over Mocks**: Assert on observable inputs/outputs; never assert on private methods (`._`).

---

## 3. Systems Architecture & Design (`design`)
- **Facts vs. Decisions Law**: Inspect files, schemas, and routes autonomously. Reserve user turns strictly for architectural trade-offs.
- **Frontier Batching**: Never drip questions one-by-one. Batch the decision frontier into numbered rounds with recommended engineering stances.
- **Ungrillable Detection**: If a question requires empirical proof (throughput/latency), trigger an isolated spike.
- **Output**: Persist decisions to `docs/adr/` and `openspec/changes/`.

---

## 4. Empirical Spikes (`spike`)
- **Strict Sandbox**: Throwaway code lives strictly in `.agentflow/spikes/<spike-name>/`. Never write prototype code to `src/`.
- **Falsifiable SLIs**: Define explicit numerical thresholds (p99 latency, RPS) before measuring.
- **Real Infrastructure**: Spin up ephemeral local Docker Compose instances on dynamic ports for backend I/O spikes.
- **Statistical Rigor**: Use `run_spike.py` for warmup passes and latency percentiles (p50/p95/p99).

---

## 5. Systems Code Review (`review`)
- **Evidence Requirement**: Plausible bugs remain hypotheses until exact file, line, and trigger path are proven.
- **The Judge**: Every reported finding must be adjudicated against source code. Reject hallucinations.
- **10-Stage Hierarchy**:
  0. *Spec Alignment*: Match PRD/ADR acceptance criteria.
  1. *Correctness*: Logic, bounds, nulls, float precision.
  2. *Concurrency & Data (DDIA)*: TOCTOU races, fencing tokens on distributed locks, dual-write hazards, replication lag.
  3. *Resilience (Release It!)*: Timeouts on all I/O, backoff with jitter, bulkheads, circuit breakers, poison-pill DLQ.
  4. *Simplicity*: YAGNI, delete dead code.
  5. *Maintainability*: Flat control flow, domain naming.
  6. *Reuse*: Shared project utilities.
  7. *Performance*: Proven query costs, N+1 queries.
  8. *SOLID & Deep Modules*: High encapsulation, low indirection.
  9. *Patterns*: Idiomatic patterns only (Single-Flight, Circuit Breaker).

---

## 6. Delivery Lifecycle (`ship`)
- **Deterministic Gates**: Design (Spec & ADR) ➔ Implementation (TDD + Simplify) ➔ Review (Adversarial Code Review) ➔ Delivery.
- **Git Checkpoints & Recovery**: Record refs at `design` and `implementation`. Broken invariants return to design with edits preserved; whole-checkout rollback needs explicit operator authorization.
- **Delivery Evidence**: Run installed `inspect_lifecycle.py --verify --tier execution --change <id>` before `--status-check`; require positive executed-test counts on the reviewed snapshot.
- **Tri-Tier State**: Authoritative ledger `.agentflow/state.json`, deep commit evidence in Git notes (`refs/notes/ship-evidence`), RFC 5133 commit trailers (`Ship-Change`, `Ship-<Gate>`).
- **Harness Independence & Turn Contracts**: Orchestrate specialist gates via explicit Turn Contracts as independent turns. Subagents are an optional optimization; sequential independent turns preserve identical state and governance.
