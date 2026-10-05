# Production Engineering Rules for Coding Agents

Universal high-density engineering instructions for AI coding agents. Grounded in classic systems and product engineering: *Designing Data-Intensive Applications* (Kleppmann), *Release It!* (Nygard), *A Philosophy of Software Design* (Ousterhout), Norman, Nielsen, and Krug.

---

## 1. Anti-Bloat & Simplicity (`simplify`)
- **Laziness Ladder**: 1. YAGNI ➔ 2. Codebase reuse ➔ 3. Standard library ➔ 4. Native platform ➔ 5. Installed deps ➔ 6. One-liner ➔ 7. Min code.
- **Deep Modules (Ousterhout)**: Narrow interfaces hiding substantial complexity. Reject shallow 5-line wrappers.
- **Define Errors Out of Existence**: Boundary states (e.g., deleting missing records) are valid no-ops rather than exceptions.
- **Zero Unrequested Abstractions**: No speculative interfaces or factories for single implementations.
- **Debt Tracking**: Mark shortcuts: `// simplify: <desc> | Ceiling: <limit> | Upgrade: <action>`.

---

## 2. Test-Driven Development (`tdd`)
- **Iron Law**: Zero production code written without a prior failing behavioral test.
- **Dual-Speed Testing**:
  - *Tier 1 (Fast Domain)*: Pure business rules using in-memory fakes (< 50ms).
  - *Tier 2 (Wire/Persistence)*: Ephemeral databases (SQLite memory, Testcontainers) (< 2s). Never mock SQL/DB engines.
- **Brownfield Characterization**: Snapshot input/output ("Golden Master") before applying TDD.
- **Behavior Over Mocks**: Assert on observable inputs/outputs; never assert on private methods (`._`).

---

## 3. Systems Architecture & Design (`design`)
- **Facts vs. Decisions Law**: Inspect files, schemas, and routes autonomously. Reserve turns for architectural forks.
- **Frontier Batching**: Never drip questions. Batch the decision frontier into numbered rounds with recommended stances.
- **Ungrillable Detection**: If a question requires empirical proof (throughput/latency), trigger an isolated spike.
- **Output**: Persist decisions to `docs/adr/` and `openspec/changes/`.

---

## 4. Empirical Spikes (`spike`)
- **Strict Sandbox**: Throwaway code lives strictly in `.agentflow/spikes/<name>/`. Never write prototype code to `src/`.
- **Falsifiable SLIs**: Define explicit numerical thresholds (p99 latency, RPS) before measuring.
- **Real Infrastructure**: Ephemeral local Docker Compose instances on dynamic ports for backend I/O spikes.
- **Statistical Rigor**: Use `run_spike.py` for warmup passes and latency percentiles (p50/p95/p99).

---

## 5. Systems Code Review (`review`)
- **Evidence Requirement**: Plausible bugs remain hypotheses until exact file, line, and trigger path are proven.
- **The Judge**: Every reported finding must be adjudicated against source code. Reject hallucinations.
- **10-Stage Hierarchy**: Spec Alignment ➔ Correctness ➔ Concurrency & Data (DDIA) ➔ Resilience (Release It!) ➔ Simplicity ➔ Maintainability ➔ Reuse ➔ Performance ➔ SOLID & Deep Modules ➔ Patterns.

---

## 6. Delivery Lifecycle (`ship`)
- **Deterministic Gates**: Design (ADR) ➔ Implementation (TDD + Simplify) ➔ Review (Adversarial Review) ➔ Delivery.
- **Checkpoints & Recovery**: Record refs at design and implementation. Broken invariants return to design.
- **Delivery Evidence**: Require positive executed-test counts on reviewed snapshot via `inspect_lifecycle.py`.
- **Tri-Tier State**: Authoritative ledger `.agentflow/state.json`, commit evidence in Git notes, RFC 5133 trailers.
- **Turn Contracts**: Orchestrate specialist gates via explicit Turn Contracts as independent turns.

---

## 7. AI Evaluations (`evals`)
- **Trace Observation**: Ground failure modes in observed production traces; zero brainstormed academic labels.
- **Code-First Over Judges**: Enforce objective checks (schemas, regex, tool signatures) with deterministic code.
- **Binary Judges**: Unambiguous Pass/Fail criteria with critique-first output; zero noisy 1–5 scales.
- **Statistical Calibration**: Isolate Train/Dev/Test splits. Use TPR/TNR; apply Rogan-Gladen correction.

---

## 8. Root-Cause Debugging (`debug`)
- **Reproduction Mandate**: Zero production code edits before an automated test reproduces the failure (Red).
- **Root Cause Over Symptom**: Trace bad state backward to origin; reject symptom masking (`if not x:`, `except: pass`).
- **Anti-Cheat Audit**: Never weaken, delete, or skip existing assertions. Audit diffs with `verify_fix.py`.
- **Circuit Breakers**: 2-strike rethink (new hypothesis); 3-strike circuit breaker (report architectural flaw).

---

## 9. Product UX & Interfaces (`ux`)
- **Prime Law (UX ≠ Styling)**: UX is not visual styling. First establish intent, flow, states, a11y, and recovery; visual styling comes afterward.
- **State Completeness Law**: Define all applicable states for interaction model: Views (Empty, Loading, Populated, Partial/Stale, Error/Recovery, Unavailable); Controls (Default, Hover, Focus, Active, Disabled, Busy; plus Selected, Checked, Expanded, Invalid, Read-only).
- **Semantics Over Div Soup**: Native HTML `<button>`, `<dialog>`, `<form>`, `<nav>` first; zero unsemantic clickable `<div>`s.
- **Accessibility (WCAG AA)**: 4.5:1 text contrast, complete keyboard tab flow, visible `:focus-visible` rings.
- **Cognitive Clarity (Krug/Norman)**: Clear visual hierarchy, no dead-end errors, explicit confirmation for destructive actions.
- **Design Tokens**: Detect & reuse existing tokens first. Avoid arbitrary values when existing tokens satisfy; permit when justified.
- **Safety & Verification (Option C)**: Read-only (`flow`, `audit`, `a11y`) vs Mutating (`spec`, `component`). `--autopilot` runs gates continuously. Run `audit_ux.py` with terminal receipts.
