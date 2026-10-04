# Skills

A repository of local-first engineering skills for AI agents, covering the complete lifecycle from architectural design to post-implementation code review:

```text
                     USER REQUEST: /ship "<Feature Idea>"
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 DESIGN: SPECIFICATION & ARCHITECTURE (design)               │
│   • Persona: Senior Principal Systems Architect                             │
│   • Model: Design Tree & Frontier Algorithm (Round-based batching)          │
│   • Output: Architecture Decision Record (ADR) & OpenSpec Change Package    │
└──────────────────────┬───────────────────────────────┬──────────────────────┘
                       │                               │
                       ▼ (Ungrillable Question?)       │
        ┌─────────────────────────────┐                │
        │    SPIKE: spike             │                │
        │   • Isolated scratch sandbox│                │
        │   • Measures empirical SLIs │                │
        │   • Settles design frontier │                │
        └──────────────┬──────────────┘                │
                       │ (Verdict returned)            │
                       ▼                               ▼ (User Approves Spec)
┌─────────────────────────────────────────────────────────────────────────────┐
│          IMPLEMENTATION: TEST-FIRST DEVELOPMENT (tdd + simplify)            │
│   • Test Driver: Writes failing behavioral test (Red Phase)                 │
│   • Simplify Implementer: Climbs Laziness Ladder, stdlib-first (Green)      │
│   • Code Refactorer: Simplifies under green; adds simplify: debt markers    │
│   • Inputs: OpenSpec tasks.md & specs/ acceptance criteria                  │
│   • Output: Self-verifying, lean production implementation                  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼ (Code & Tests Complete)
┌─────────────────────────────────────────────────────────────────────────────┐
│          REVIEW: ADVERSARIAL REVIEW & AUTO-FIX (review)                       │
│   • Stage 0: Spec Alignment (Verifies code directly against ADR/Spec)       │
│   • Stages 1–9: Correctness, Concurrency, Failure, Craftsmanship, SOLID     │
│   • Review Loop: Finds critical issues and checks for regressions            │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼ (Judge Issues PASS)
┌─────────────────────────────────────────────────────────────────────────────┐
│                 DELIVERY: PR SIGN-OFF & ARCHIVING                           │
│   • Final test suite verification run                                       │
│   • Delivery Walkthrough Report & PR summary ready for review               │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Why Engineering Teams Should Use This Framework

As developers increasingly rely on AI agents, engineering teams face a growing operational challenge: **the "AI Slop" and Reviewer Burnout crisis**. AI agents generate high volumes of plausible-looking code that often introduces subtle race conditions, bloats codebases with unnecessary dependencies, skips real tests in favor of hollow mocks, and erodes architectural consistency.

This framework transforms AI from an unpredictable code generator into a **disciplined, Principal-level engineering partner**:

| Corporate / Engineering Challenge | How This Framework Solves It | Team Impact |
|---|---|---|
| **AI Dependency & Boilerplate Bloat** | [**`simplify`**](./skills/simplify/SKILL.md) enforces the *Laziness Ladder* (YAGNI, codebase reuse, stdlib built-ins, zero unrequested abstractions). Automated CI scanning via `scan_debt.py`. | **Leaner codebases, zero unneeded npm/pip dependencies, lower maintenance overhead.** |
| **Reviewer Fatigue on AI PRs** | [**`review`**](./skills/review/SKILL.md) performs a 10-stage systems review (Correctness, Concurrency, Security, WebPerf, Failure, Craftsmanship) with an evidence-based Judge that rejects hallucinations. | **Senior/Staff engineers stop wasting hours catching basic race conditions, unindexed queries, and missing timeouts.** |
| **Hollow, Backfilled Unit Tests** | [**`tdd`**](./skills/tdd/SKILL.md) enforces the *Iron Law of Test-First* and an in-flight **Doubt Cycle**. Agents are strictly forbidden from writing production code before proving a behavioral test fails. | **Real regression safety; tests verify observable behavior instead of mock configurations.** |
| **Superficial Patching & Bug Regressions** | [**`debug`**](./skills/debug/SKILL.md) enforces the *Reproduction Mandate*, backward causation tracing, boundary logging, and anti-cheat diff auditing via `verify_fix.py`. | **Root-cause permanent fixes, zero weakened tests, automated reproduction proofs.** |
| **Untracked AI & Stochastic Bugs** | [**`evals`**](./skills/evals/SKILL.md) enforces trace-grounded error discovery, zero-dependency annotation (`serve_review_app.py`), code-first assertions, binary LLM judges, and Rogan-Gladen calibration (`score_calibration.py`). | **Deterministic evaluation of stochastic outputs, calibrated LLM judges, zero reliance on noisy 1–5 scales.** |
| **Vanishing Architectural Context** | [**`design`**](./skills/design/SKILL.md) enforces the *Facts vs. Decisions Law*, audits **Capability Closure**, and compiles an **ADR** and **OpenSpec package** directly into Git. | **Local decision and evidence records that teams can review alongside their existing controls.** |
| **Multi-Agent Coordination & Crashes** | [**`ship`**](./skills/ship/SKILL.md) provides a **two-phase atomic transaction engine** (`.agentflow/archive-transaction.json`) and multi-change isolation (`--change <id>`) with automatic crash recovery. | **Recoverable archive operations and explicit change selection; parallel source editing still requires separate worktrees.** |
| **Security & Compliance Hurdles** | Local policy checks, scoped capabilities, audit records, and guarded MCP actions. | **Useful control points for a pilot. Not an OS sandbox, identity system, or compliance certification. Your host still controls permissions, secrets, and network access.** |
| **LLM Token Costs & Latency** | All core skills and agent prompts are **token-optimized ("cavemanned")**, stripping conversational fluff while retaining strict technical constraints. | **Compact prompts; measure token use and instruction adherence with your own host and model.** |

### Team Rollout Playbook

> [!TIP]
> **Recommended Starting Point**: Pilot **[`review`](./skills/review/SKILL.md) in review-only mode**. Its read-only inspection, evidence requirements, and bounded repair workflow provide an immediate, low-risk way to measure useful defect findings and false-positive rates on real pull requests.

Teams can adopt skills incrementally without changing their entire workflow:
1. **Phase 1: Pre-PR Defense ([`review`](./skills/review/SKILL.md))**: Run `/review` on pull requests before requesting senior peer review. Catch race conditions, unindexed queries, and missing error paths early.
2. **Phase 2: Anti-Bloat Coding ([`simplify`](./skills/simplify/SKILL.md))**: Use `/simplify` on everyday tasks to enforce standard-library reuse. Add `python3 skills/simplify/scripts/scan_debt.py --strict` to CI to enforce documented debt ceilings.
3. **Phase 3: Autonomous Lifecycle ([`ship`](./skills/ship/SKILL.md))**: Run `/ship "<feature>"` to drive complete features from architectural grilling (ADRs) through TDD to reviewed PRs. Configure project manifests (`.agentflow.json`) for team workflow profiles (`small-fix`, `standard`, `high-risk`).
4. **Phase 4: Headless CI Orchestration**: Pilot the GitHub Actions workflow by explicitly dispatching an approved design commit and digest using the [Headless CI Guide](./skills/ship/references/headless_ci_guide.md).

---

## Skills Catalog

| Skill Name | Command / Trigger | Lifecycle Stage | Description |
|---|---|---|---|
| [**`review`**](./skills/review/SKILL.md) | `/review`, `"review"`, `"adversarial review"` | Post-implementation | **Recommended Pilot**. 10-stage systems review covering correctness, concurrency, security hardening ([`handbook_security.md`](./skills/review/references/handbook_security.md)), web performance ([`handbook_webperf.md`](./skills/review/references/handbook_webperf.md)), architectural invariants ([`architectural_invariants.md`](./skills/review/references/architectural_invariants.md)), and production risk. |
| [**`simplify`**](./skills/simplify/SKILL.md) | `/simplify`, `"simplify"`, `"lazy senior dev"` | Simplicity & Anti-Bloat | Forces the simplest working solution: YAGNI, standard library first, zero unrequested abstractions, and automated debt auditing via `scan_debt.py`. |
| [**`tdd`**](./skills/tdd/SKILL.md) | `/tdd`, `"tdd"`, `"red-green-refactor"` | Implementation | Dual-speed TDD engine (fast fakes & ephemeral DBs), legacy characterization wrapping, in-flight **Doubt Cycle** ([`doubt_cycle.md`](./skills/tdd/references/doubt_cycle.md)), and `verify_tdd.py` CI parity auditor. |
| [**`design`**](./skills/design/SKILL.md) | `/design`, `"design"`, `"grill me on this design"` | Pre-implementation | Relentlessly stress-tests architectures using frontier rounds, enforces **Capability Closure** ([`capability_closure.md`](./skills/design/references/capability_closure.md)), detects ungrillable questions, and compiles an ADR & OpenSpec. |
| [**`spike`**](./skills/spike/SKILL.md) | `/spike`, `"spike"`, `"throwaway spike"` | Empirical Validation | Rapid disposable spikes with automated statistical benchmarking (`run_spike.py` p50/p90/p95/p99/max, RPS, RSS memory delta), ephemeral Docker sandboxes, and ADR bridge. |
| [**`ship`**](./skills/ship/SKILL.md) | `/ship`, `"ship"`, `/lifecycle` | Full Lifecycle Orchestrator | **Pilot workflow**. Chains all 5 skills into an autonomous pipeline with 4 transition gates, git checkpoints, safe rollback, team profiles, preflight doctor, and working tree fingerprinting. |
| [**`evals`**](./skills/evals/SKILL.md) | `/evals`, `"evals"`, `"error discovery"`, `"ai evals"` | AI Evaluation & Regression | Product-specific AI evaluation engine (Hamel Husain / Parlance Labs methodology). Trace-first error discovery, stdlib review app, code-first assertions, binary LLM judges, and Rogan-Gladen TPR/TNR calibration. |
| [**`debug`**](./skills/debug/SKILL.md) | `/debug`, `"debug"`, `/fix`, `"fix"`, `"bugfix"` | Root-Cause Repair & Incident | Systematic debugging engine (borrowing best of `superpowers` & `debug-skill`): reproduction test first, backward data-flow tracing, multi-layer boundary logging, anti-cheat audit (`verify_fix.py`), and 3-strike circuit breaker. |

---

## 1. `ship` (The Unified Engineering Orchestrator)

Give your agent [ship SKILL.md](./skills/ship/SKILL.md) and feature request: `/ship "Add Webhook Event Streaming"`.

- **One Command Delivery**: Drives feature from architectural grilling to tested, simplified, production-reviewed PR.
- **Tri-Tier State Engine**:
  - Authoritative multi-change ledger `.agentflow/state.json` (multi-agent isolation via `--change <id>`).
  - Deep commit evidence in Git notes (`refs/notes/ship-evidence`).
  - Standard RFC 5133 commit trailers (`Ship-Change`, `Ship-<Gate>`, `--generate-trailers`).
- **Preflight Diagnostics (`--doctor`)**: Run `python3 skills/ship/scripts/inspect_lifecycle.py --doctor` to verify runtime, git availability, 6 installed skills, versions, ledger readability, and pending recovery before starting work.
- **Team Workflow Profiles**: Configurable via `.agentflow.json` (`small-fix`, `standard`, `high-risk`) and host execution guidance (`workflow.execution: auto | sequential | parallel`) as detailed in [Local Team Rollout](./skills/ship/references/team_rollout.md).
- **Cryptographic Design Receipts**: Binds authorization to exact specification digest; any requirements amendment invalidates approval and requests re-confirmation.
- **Working Tree Fingerprinting**: SHA-256 snapshot of commit, tree hash, and uncommitted diff/untracked files; post-review modifications immediately flag `Ship-Review: STALE` and block delivery.
- **Atomic Transactions & Crash Resilience**: Two-phase commit spec archiving (`.agentflow/archive-transaction.json`) with automatic self-healing recovery from interrupted sessions.
- **Deterministic Recovery**: Crash points have explicit resume, rollback, reconcile, and abort outcomes. Recovery is recorded in the ledger.
- **Re-Entrant State Machine**: Filesystem (`openspec/`, `tasks.md`, `docs/adr/`) is persistent state machine. Resumes exact active phase instantly.
- **Scoped Authorization**: Durable approvals and capabilities bind an agent, change, operation, target, and expiry. Approvals cannot be reused across agents or changes.
- **External Action Guard**: Network read/write, secret read, cloud mutation, and GitHub write are named operations. `CapabilityGuard` and `ExternalActionAdapter` check them before a provider callback runs.
- **Tamper-Evident Events**: Append-only execution events use a hash chain and can replay change state for audit and recovery checks.
- **Resource Governor**: Tracks tokens, model calls, turns, time, cost, tools, and network operations against per-change ceilings.
- **Evaluation Harness**: Runs local regression scenarios for approvals, permissions, recovery, concurrency, budgets, and event integrity.
- **Repository Manifest (`.agentflow.json`)**: Clean domain schema validated by [`agentflow.schema.json`](./skills/ship/references/agentflow.schema.json). Configures custom test commands (`gates.implementation.test`).
- **Git Checkpoints & Safe Rollback**: Records private refs (`--checkpoint design`) and supports operator-authorized whole-checkout recovery (`--rollback design --force`); architectural revisions preserve current edits by default.
- **Zero-Loss State Migration**: Seamlessly upgrade legacy ledgers via `inspect_lifecycle.py --migrate-state` with byte-for-byte backups.
- **Modular SOLID Architecture**: Structured Python package under [`skills/ship/scripts/lifecycle/`](./skills/ship/scripts/lifecycle/) separating VCS, evidence, ledger, gate verification, and transaction journals.
- **Headless CI & GitHub Actions**: Run headlessly in CI with explicit design commit/digest approvals via [Headless CI Guide](./skills/ship/references/headless_ci_guide.md).
- **Agent Roster**: Led by [Lifecycle Orchestrator](./skills/ship/agents/lifecycle_orchestrator.md).
- **References**: [Lifecycle State Machine Guide](./skills/ship/references/lifecycle_state_machine.md), [Local Team Rollout Guide](./skills/ship/references/team_rollout.md), and [Formal JSON Schema](./skills/ship/references/agentflow.schema.json).

---

## 2. `design` (Pre-Implementation)

Give your agent the [design SKILL.md](./skills/design/SKILL.md) and your proposal or idea.

- **The Facts vs. Decisions Law**: The agent autonomously inspects the codebase for facts. User turns are reserved strictly for architectural trade-offs.
- **Frontier Rounds**: Batches unblocked questions with concrete recommended stances (`❓ Q1` + `➡️ Recommended Stance`) so you can answer rapidly by number.
- **Capability Closure Checklists**: Enforces the 4 closure checklists in [capability_closure.md](./skills/design/references/capability_closure.md) (Entity Lifecycle, State Machine, Authorization Boundaries, Failure/Integration) to eliminate "happy path myopia" before drafting implementation tasks.
- **Ungrillable Detection**: Recognizes when questions cannot be settled by talk and prompts a timeboxed spike using [spike](./skills/spike/SKILL.md).
- **Agent Roster**: Led by the [Principal Systems Architect](./skills/design/agents/principal_architect.md).
- **Output**: Generates a standard [Architecture Decision Record (ADR)](./skills/design/references/adr_template.md) under `docs/adr/` and/or an executable [OpenSpec Change Package](./skills/design/references/openspec_template.md) under `openspec/changes/`, which become the input contracts for `review`.

---

## 3. `spike` (Empirical Validation & Spikes)

Give your agent the [spike SKILL.md](./skills/spike/SKILL.md) and the empirical question or hypothesis.

- **Throwaway Mindset**: Strict isolation to `.agentflow/spikes/<spike-name>/`. Zero pollution of production source trees.
- **Ephemeral Infrastructure Sandboxing**: Isolated `docker-compose.yml` for real backend dependencies (Postgres, Redis, Kafka) on dynamic ports.
- **Automated Benchmark Runner (`run_spike.py`)**: Warmup passes, concurrent worker load, and statistical percentile distributions (p50/p90/p95/p99/max, RPS, RSS memory delta).
- **Automated ADR & OpenSpec Bridge**: Immediately exports evidenced verdicts and verified configuration snippets to `docs/adr/`.
- **Agent Roster**: Implemented by the [Spike Prototyper](./skills/spike/agents/spike_prototyper.md).
- **References**: Consult [Spike Guidelines](./skills/spike/references/spike_guidelines.md) and ready-to-use [Experiment Templates](./skills/spike/references/experiment_templates.md).

---

## 4. `tdd` (Implementation Flow & Reusable Agents)

Give your agent the [tdd SKILL.md](./skills/tdd/SKILL.md) and the task or OpenSpec package to implement.

- **The Iron Law**: No production code without a failing behavioral test first.
- **In-Flight Doubt Cycle**: Applies [doubt_cycle.md](./skills/tdd/references/doubt_cycle.md) during Green ➔ Refactor transitions to challenge assumptions (boundary probing, mutant testing, mutation resistance, invariant assertions) while changes are still cheap and isolated.
- **Dual-Speed Testing**: Fast in-memory unit tests (`< 50ms`) for domain rules; ephemeral databases (SQLite, Testcontainers) for real SQL queries and migrations. No mocking of DB engines.
- **Brownfield Characterization (Golden Master)**: Safely onboards legacy untested code by snapshotting existing behavior before applying incremental TDD.
- **Single-Context Micro-Cycles**: Fast inline Red-Green-Refactor for tasks < 150 lines, reserving multi-agent handoffs for major architectural features.
- **Deterministic Verification Tooling (`verify_tdd.py`)**: Checks git diffs for test-to-code parity, detects anti-patterns (assertless tests, whitebox spies), and trims runner logs into token-efficient receipts.
- **The Multi-Agent Implementation Roster**:
  - [**Test Driver**](./skills/tdd/agents/test_driver.md): Red Phase. Translates specs into failing behavioral tests using AAA.
  - [**Simplify Implementer**](./skills/tdd/agents/simplify_implementer.md): Green Phase. Climbs the Laziness Ladder to write the minimum passing code.
  - [**Code Refactorer**](./skills/tdd/agents/code_refactorer.md): Refactor Phase. Cleans code while tests remain green; adds debt markers.
- **Red Verification**: Must execute the test suite and confirm the test fails for the expected reason before implementing.
- **References**: Consult [TDD Patterns & Testability](./skills/tdd/references/tdd_patterns.md), [Testing Anti-Patterns Catalog](./skills/tdd/references/anti_patterns.md), and [In-Flight Doubt Cycle](./skills/tdd/references/doubt_cycle.md).

---

## 5. `simplify` (Lazy Senior Dev / Anti-Bloat)

Give your agent the [simplify SKILL.md](./skills/simplify/SKILL.md) when implementing features, refactoring, or choosing libraries.

- **The Laziness Ladder**: 1. YAGNI ➔ 2. Codebase reuse ➔ 3. Standard library ➔ 4. Platform native ➔ 5. Installed deps ➔ 6. One-liner ➔ 7. Minimum code.
- **Deep Modules & Defining Errors Out of Existence**: Narrow interfaces hiding substantial complexity (Ousterhout); boundary conditions become valid no-ops rather than exceptions.
- **Root-Cause Fixes**: Grep all callers and fix at the shared root, not symptom guards per caller.
- **Debt Tracking & Scanner**: Mark deliberate pragmatic shortcuts with `// simplify: <shortcut> | Ceiling: <limit> | Upgrade: <next step>.`. Audit with `python3 skills/simplify/scripts/scan_debt.py` or `scan_debt.py --strict` in CI.
- **References**: Consult the [Laziness Ladder Guide](./skills/simplify/references/laziness_ladder.md) and [Debt Tracking Protocol](./skills/simplify/references/debt_tracking.md).

---

## 6. `review` (Post-Implementation)

Give your coding agent the [SKILL.md](./skills/review/SKILL.md) file and the change to review. Include the issue or spec if you have one.

Choose one action:

| Mode | What it does | Example request |
|---|---|---|
| `review` | Review Only. Return a report. | “Use review in review mode against main.” |
| `review-pr` | Review + PR Comment. Post the report without changing the branch. | “Use review in review-pr mode for PR #123.” |
| `review-loop` | Review + Fix Loop. Make scoped fixes, test, and re-review. | “Use review in review-loop mode against main.” |

The agent defaults to `review` (Review Only) immediately. Asking to fix code selects `review-loop`, and asking to comment on a PR selects `review-pr`. A PR link alone does not authorise commenting; choosing `review-pr` does. Choosing `review-loop` permits fixes but does not commit or push them.

All three use one pipeline. The mode changes what happens after the Judge:

```text
Inspect → Pick checks → Review → Judge
                                 ├─ review      → Report
                                 ├─ review-pr   → PR comment
                                 └─ review-loop → Fix → Test → Re-review → Report
```

These are agent instructions, not installed shell commands. PR commenting needs authenticated provider access; if posting fails, the agent returns the prepared report and the blocker.

To run just the change inspector, run this from the Git repo you want to review. Replace `/path/to/skills` with this repo's location:

```bash
bash /path/to/skills/skills/review/scripts/inspect_changes.sh --no-diff main...HEAD
```

The script lists changed files, diff stats, possible specs, review hints, matching test filenames, and possible callers. These are text and filename searches. It does not run tests or prove the code is correct. Remove `--no-diff` to print the diff too.

The inspector requires Bash 3.2+ and Git. It includes individual untracked files and their diffs without staging them, preserves rename paths, and returns a nonzero status for invalid comparisons. Automatic scope selection uses the available local or remote-tracking `main`/`master` ref; a root commit is compared with the empty tree. Test and caller searches are hints from the current checkout, even when reviewing a historical range. Keep the checkout stable while it captures context.

For a whole-repository review, ask “Review this repository adversarially.” The agent inventories the requested tree and reviews existing code even when there are no uncommitted changes. The change inspector alone is not a repository review.

## How the review works

```text
Inspect change → Pick checks → Review → Judge → Report
```

The instructions use one reviewer for diffs of 400 lines or fewer. Larger diffs, or an explicit parallel request, use the selected specialists in parallel when the host supports it. Without that support, the agent performs the passes itself.

| Role | Job |
|---|---|
| [Correctness](./skills/review/agents/correctness_reviewer.md) | Find broken behavior. Includes failure paths, migration integrity, and API compatibility. |
| [Concurrency](./skills/review/agents/concurrency_reviewer.md) | Find races, locking problems, and async lifecycle failures. |
| [Design](./skills/review/agents/design_reviewer.md) | Find needless complexity. No abstraction just because SOLID says so. |
| [Judge](./skills/review/agents/review_judge.md) | Check submitted claims against the code. Remove duplicates and false positives. Rank what remains. Find no new problems. |

The main agent picks the checks, handles spec alignment, general performance, and broader production risks, then writes the report. Specialist prompts do not register or launch agents by themselves.

Specialists work independently. They do not read each other's first reports. The Judge must inspect relevant code before accepting a finding. Evidence wins. Agents do not vote.

## Fixes

If you ask for fixes, the [Code Fixer](./skills/review/agents/code_fixer.md) gets only Judge-approved findings and the context needed to implement them. No raw reviewer reports. No rejected claims. It makes scoped changes for `autonomous` findings and reports validation results. For `requires-human`, it reports the decision needed and possible approaches without changing code for that finding. A review request alone does not trigger edits.

Requested fixes use a [bounded loop](./skills/review/references/review_loop.md), with at most three rounds by default. Findings keep the same IDs from review through confirmation, fixing, and verification. Relevant reviewers check the combined fix patch, then the Judge validates the results. Business or architecture decisions, repeated fix failure, unexpected test failures, unrelated refactoring, and unresolved tradeoffs stop the whole loop for a human decision. Approval needs no remaining P0/P1, passing build/tests, no unresolved regression, and no unexplained changes. Optional P2 findings must be explicitly justified. The Autonomous Review summary shows iterations, counts, and verification results.

## Which reviewers run?

Action mode controls edits and publication. Change type controls which technical checks run.

| Change | Reviewers |
|---|---|
| Standard code | Correctness, Design |
| Shared state or async | Correctness, Concurrency, Design |
| Database migration | Correctness |
| Public API | Correctness |
| Dependencies or build | Correctness, Design |
| Financial logic | Correctness, Concurrency, Design |
| Full review | Correctness, Concurrency, Design |

Mixed changes combine checks. Migration locks and async APIs add Concurrency. See [review modes](./skills/review/references/review_modes.md) for the full rules.

## What gets checked?

The checklist has ten stages, grounded in classical systems engineering (*DDIA*, *Release It!*, *A Philosophy of Software Design*):

0. **Spec alignment**: Verifies implementation directly against ADR invariants and OpenSpec acceptance criteria.
1. **Correctness**: Logic bugs, off-by-one, boundary cases, null dereferences, floating-point precision.
2. **Concurrency and safety**: Race conditions, TOCTOU, atomic operations, locking order, DDIA data invariants (replication lag, fencing tokens, dual-writes).
3. **Failure and resilience**: *Release It!* patterns: mandatory I/O timeouts, jittered exponential backoff, bulkheads, circuit breakers, poison-pill DLQ routing.
4. **Simplicity**: YAGNI, standard library reuse, elimination of speculative indirection, dead code removal.
5. **Maintainability**: Flat control flow, domain naming, narrow interfaces, deep modules.
6. **Reuse**: Existing codebase utilities and platform primitives.
7. **Performance**: Proven query costs, N+1 query elimination, unindexed lookups, memory leaks.
8. **SOLID & Deep Modules**: High encapsulation, low interface leakage, clean single-responsibility boundaries.
9. **Patterns**: Idiomatic system patterns (Single-Flight, Circuit Breaker, Outbox); no architectural astronautics.

### Specialist Handbooks & System Contracts

Reviewers consult authoritative domain reference guides:
- [**Security Hardening & Zero-Trust Defense**](./skills/review/references/handbook_security.md): Injection defenses (SQL, shell, XSS), authentication, authorization, cryptographic hygiene, secrets management, SSRF, and IDOR.
- [**Web Performance & Resource Optimization**](./skills/review/references/handbook_webperf.md): Core Web Vitals (LCP, INP, CLS), render blocking, bundle splitting, memory lifecycles, and caching headers.
- [**Architectural Invariants Contract**](./skills/review/references/architectural_invariants.md): Verifies repo-wide architectural invariants. Violations return to design with current edits preserved. Whole-checkout restoration requires explicit operator authorization.
- [**Production Risk Matrix**](./skills/review/references/production_risk_matrix.md): Blast radius evaluation, rollback safety, and observability gates.

## What you get

All feedback uses plain, human language, including PR comments: what breaks, why it matters, and what to do next. Short and clear, with verifiable source evidence kept intact.

- **Unified Review Report**: Executive summary, 10-stage scorecard, prioritized findings, simplification opportunities, test gaps, and verification checklist. Missing checks stay visible; agent handoffs stay internal.
- **12-Field Finding Schema**: Each finding adheres to the formal [12-field schema](./skills/review/references/finding_schema.md) (`id`, `severity`, `category`, `file`, `line`, `title`, `problem`, `evidence`, `impact`, `recommendation`, `confidence`, `fixability`).
- **Autonomous vs. Human Decision Separation**: Findings marked `autonomous` are fixed by the Code Fixer in the bounded review loop. Findings marked `requires-human` surface concrete trade-offs formatted as Frontier Clarifications (`❓ Q1` + `➡️ Recommended Stance`).
- **Delivery Evidence Envelope**: For lifecycle delivery, bundles the Judge PASS report, verified test runner metrics (command, exit code `0`, duration, test count, zero failures), and SHA-256 working tree fingerprint into [`.agentflow/reviews/delivery_evidence.json`](./skills/review/references/finding_schema.md#6-delivery-evidence-envelope-agentflowreviewsdelivery_evidencejson).

---

## 7. `evals` (Product-Specific AI Evals)

Give your agent the [evals SKILL.md](./skills/evals/SKILL.md) when evaluating AI, LLM, or agent features: `/evals "help me analyze traces.jsonl"`.

- **Observation Over Brainstorming**: Ground evals in real traces. No generic academic tags ("hallucination score", "toxicity"); define concrete, application-specific failure modes.
- **Zero-Dependency Trace Reviewer (`serve_review_app.py`)**: Local stdlib Python server hosting an interactive single-page app. Inspects full traces (inputs, intermediate turns, tool calls, outputs) with role-colored formatting and margin notes.
- **Diverse Trace Sampling (`sample_traces.py`)**: Stratifies traces by length, tool calls, and error flags combined with random sampling to uncover unexpected edge cases without sampling bias.
- **Code-First Before Judges**: Enforce objective criteria (JSON schemas, regex, tool signatures, execution outputs) with deterministic Python code. Reserve LLM judges strictly for subjective semantic criteria.
- **Strictly Binary Judges**: Unambiguous Pass/Fail rubrics with mandatory critique-first structured JSON output. Zero noisy 1–5 Likert scales.
- **Statistical Calibration (`score_calibration.py`)**: Strict Train (15%), Dev (45%), and Test (40%) split isolation with zero prompt leakage. Evaluates True Positive Rate (TPR) and True Negative Rate (TNR), rejecting raw accuracy on imbalanced datasets.
- **Rogan-Gladen Bias Correction**: Calculates unbiased true production success rates $\hat{\theta} = \frac{p_{\text{obs}} + \text{TNR} - 1}{\text{TPR} + \text{TNR} - 1}$ and bootstrap 95% confidence intervals from held-out test calibration.
- **RAG & Synthetic Bootstrapping**: Decomposed retrieval (Hit@K, MRR, Context Relevance) and generation (Faithfulness, Answer Relevance) metrics, alongside dimension-tuple combinatorial test generation.
- **Agent Roster**: [Error Analyst](./skills/evals/agents/error_analyst.md), [Eval Auditor](./skills/evals/agents/eval_auditor.md), [Judge Engineer](./skills/evals/agents/judge_engineer.md), and [Calibration Statistician](./skills/evals/agents/calibration_statistician.md).
- **References**: [Taxonomy Framework](./skills/evals/references/taxonomy_framework.md), [Judge Rubric Templates](./skills/evals/references/judge_rubric_templates.md), [Calibration Math](./skills/evals/references/calibration_math.md), [RAG Metrics Handbook](./skills/evals/references/rag_metrics_handbook.md), and [Synthetic Data Generation](./skills/evals/references/synthetic_data_generation.md).

---

## 8. `debug` (Systematic Root-Cause Debugging)

Give your agent the [debug SKILL.md](./skills/debug/SKILL.md) when diagnosing crashes, broken tests, or regressions: `/debug "Fix test failure in payment_service"`.

- **The Reproduction Mandate**: Zero production code edits before writing an isolated reproduction test that fails on current code for the reported reason.
- **Backward Causation Tracing**: Trace data flow and state mutations backward from the crash site (Frame 0) to where state first diverged from invariants ([`root_cause_tracing.md`](./skills/debug/references/root_cause_tracing.md)).
- **Multi-Component Boundary Logging**: Diagnostic instrumentation across system layers (CI, API, worker, DB) to isolate the failing boundary instead of guessing ([`multi_component_logging.md`](./skills/debug/references/multi_component_logging.md)).
- **Root Cause Over Symptom**: Rejects symptom patching (bare `except: pass`, empty null guards, swallowed exceptions) that leaves corrupted state upstream ([`defensive_masking_antipatterns.md`](./skills/debug/references/defensive_masking_antipatterns.md)).
- **Anti-Cheat Audit (`verify_fix.py`)**: Automated verification that repro tests exist, test assertions were not deleted or weakened (`@pytest.mark.skip`, `xit`), and all test runs pass.
- **Two Strikes, Rethink**: If 2 hypotheses fail at the same location, the mental model is wrong. Stop patching, re-read code from scratch, and form a fundamentally new hypothesis.
- **Three-Strike Circuit Breaker**: If 3 distinct fixes fail or reveal new breakage across other subsystems, stop. Surface to the human that the problem is architectural.
- **Agent Roster**: [Root Cause Investigator](./skills/debug/agents/root_cause_investigator.md), [Reproduction Specialist](./skills/debug/agents/reproduction_specialist.md), and [Surgical Fixer](./skills/debug/agents/surgical_fixer.md).
- **References**: [Root Cause Tracing](./skills/debug/references/root_cause_tracing.md), [Multi-Component Logging](./skills/debug/references/multi_component_logging.md), and [Defensive Masking Anti-Patterns](./skills/debug/references/defensive_masking_antipatterns.md).

---

## Files

```text
.codex-plugin/
└── plugin.json                 # OpenAI Codex native skill manifest
.cursor/rules/
└── ship.mdc                    # Cursor IDE native lifecycle rule
.github/
└── copilot-instructions.md     # GitHub Copilot engineering instructions
nano/                           # High-density, ultra-compact (<50 lines) rules for Cursor/Claude Code
├── AGENTS.md                   # Universal drop-in rule file (<100 lines) combining all 8 skills
├── review.nano.md
├── design.nano.md
├── ship.nano.md
├── simplify.nano.md
├── spike.nano.md
├── tdd.nano.md
├── evals.nano.md
└── debug.nano.md

scripts/
├── install.sh                  # Portable skill installer (symlink/copy to target environments)
└── run_tests.sh                # Standard-library validation and regression runner

skills/
├── ship/
│   ├── SKILL.md
│   ├── VERSION
│   ├── agents/
│   │   └── lifecycle_orchestrator.md
│   ├── scripts/
│   │   ├── inspect_lifecycle.py
│   │   └── lifecycle/          # Modularized SOLID lifecycle engine package
│   │       ├── checkpoints.py
│   │       ├── config.py
│   │       ├── engine.py
│   │       ├── evidence.py
│   │       ├── gates.py
│   │       ├── ledger.py
│   │       ├── models.py
│   │       ├── operations.py
│   │       ├── paths.py
│   │       ├── protocols.py
│   │       ├── specs.py
│   │       ├── trailers.py
│   │       ├── transactions.py
│   │       └── vcs.py
│   └── references/
│       ├── lifecycle_state_machine.md
│       ├── team_rollout.md
│       ├── headless_ci_guide.md
│       └── agentflow.schema.json
├── design/
│   ├── SKILL.md
│   ├── VERSION
│   ├── agents/
│   │   └── principal_architect.md
│   └── references/
│       ├── interview_protocol.md
│       ├── systems_inquiry_matrix.md
│       ├── capability_closure.md
│       ├── adr_template.md
│       └── openspec_template.md
├── spike/
│   ├── SKILL.md
│   ├── VERSION
│   ├── agents/
│   │   └── spike_prototyper.md
│   ├── scripts/
│   │   └── run_spike.py
│   └── references/
│       ├── spike_guidelines.md
│       └── experiment_templates.md
├── tdd/
│   ├── SKILL.md
│   ├── VERSION
│   ├── agents/
│   │   ├── test_driver.md
│   │   ├── simplify_implementer.md
│   │   └── code_refactorer.md
│   ├── scripts/
│   │   └── verify_tdd.py
│   └── references/
│       ├── doubt_cycle.md
│       ├── tdd_patterns.md
│       └── anti_patterns.md
├── simplify/
│   ├── SKILL.md
│   ├── VERSION
│   ├── scripts/
│   │   └── scan_debt.py
│   └── references/
│       ├── laziness_ladder.md
│       └── debt_tracking.md
├── review/
│   ├── SKILL.md
│   ├── VERSION
│   ├── agents/
│   │   ├── correctness_reviewer.md
│   │   ├── concurrency_reviewer.md
│   │   ├── design_reviewer.md
│   │   ├── review_judge.md
│   │   └── code_fixer.md
│   ├── scripts/
│   │   ├── inspect_changes.sh
│   │   └── validate_report.py
│   └── references/
│       ├── review_modes.md
│       ├── finding_schema.md
│       ├── agent_report.schema.json
│       ├── handbook_foundations.md
│       ├── handbook_craftsmanship.md
│       ├── handbook_architecture.md
│       ├── handbook_security.md
│       ├── handbook_webperf.md
│       ├── architectural_invariants.md
│       ├── review_pipeline.md
│       ├── review_loop.md
│       └── production_risk_matrix.md
├── evals/
│   ├── SKILL.md
│   ├── VERSION
│   ├── agents/
│   │   ├── eval_auditor.md
│   │   ├── error_analyst.md
│   │   ├── judge_engineer.md
│   │   └── calibration_statistician.md
│   ├── scripts/
│   │   ├── serve_review_app.py
│   │   ├── sample_traces.py
│   │   └── score_calibration.py
│   └── references/
│       ├── taxonomy_framework.md
│       ├── judge_rubric_templates.md
│       ├── calibration_math.md
│       ├── rag_metrics_handbook.md
│       └── synthetic_data_generation.md
└── debug/
    ├── SKILL.md
    ├── VERSION
    ├── agents/
    │   ├── root_cause_investigator.md
    │   ├── reproduction_specialist.md
    │   └── surgical_fixer.md
    ├── scripts/
    │   └── verify_fix.py
    └── references/
        ├── root_cause_tracing.md
        ├── multi_component_logging.md
        └── defensive_masking_antipatterns.md
```

## Installation

To install skills into your environment's skill directory (defaults to `~/.gemini/config/skills/`):

```bash
./scripts/install.sh
```

### Multi-Agent & Cross-IDE Installation

Install into any AI agent or IDE with native manifests or one-command installers:

- **Vercel Skills CLI (70+ Agents)**:
  ```bash
  npx skills add shathwar/skills
  ```
- **OpenAI Codex**: Native plugin manifest configured in [`.codex-plugin/plugin.json`](./.codex-plugin/plugin.json).
- **Cursor IDE**: Project-wide lifecycle rule ready in [`.cursor/rules/ship.mdc`](./.cursor/rules/ship.mdc).
- **GitHub Copilot**: Context instructions ready in [`.github/copilot-instructions.md`](./.github/copilot-instructions.md).
- **Claude Code**:
  ```bash
  ./scripts/install.sh --target-claude
  ```

### Safety & Team Customisation Flags
The installer defaults to preserving existing non-symlink directories to avoid overwriting team configurations:
- **`--target-claude`**: Install directly to Claude Code skills directory (`~/.claude/skills`).
- **`--target-cursor`**: Install directly to Cursor skills directory (`~/.cursor/skills`).
- **`--target-antigravity` / `--target-gemini`**: Install to Antigravity global directory (`~/.gemini/config/skills`).
- **`--backup`**: Safely back up existing directories to timestamped `.bak.<timestamp>` paths before installing.
- **`--overwrite`**: Explicitly permit replacing existing non-symlink directories.
- **`--dry-run`**: Preview all link/copy actions without touching the filesystem.
- **`--mode <symlink|copy>`**: Choose between symbolic links (default on Unix) or copied files (auto-selected on Windows).

```bash
# Safe update with timestamped backup of existing directories
./scripts/install.sh --backup

# Install to Claude Code or Cursor
./scripts/install.sh --target-claude
./scripts/install.sh --target-cursor

# Preview installation
./scripts/install.sh --dry-run --target /path/to/custom/skills
```

### Portable Rules for Cursor, Claude Code, and Windsurf (`nano/`)

For teams operating across multiple AI coding tools with tight context budgets:
- **Universal Root Rules ([`nano/AGENTS.md`](./nano/AGENTS.md))**: A complete, high-density distillation of all 6 skills (< 100 lines) ready to copy to `AGENTS.md`, `.cursorrules`, or `CLAUDE.md`.
- **Scoped Nano Rules**: Standalone files under [`nano/`](./nano/) (`review.nano.md`, `simplify.nano.md`, `tdd.nano.md`, etc.) under 50 lines each for targeted task injection.


---

## Supported Environments & Maintenance

- **Operating Systems**: macOS (Ventura+), Linux (Ubuntu 20.04+, RHEL 8+, Debian 11+).
- **Runtimes**: Python 3.10+ (standard library only; zero external pip dependencies) and POSIX Bash (`bash 4.0+`).
- **VCS**: Git 2.25+.
- **Maintainer & Repository**: Maintained by Sumanth (`shathwar/skills`).
- **Release Versioning**: Release tags follow Semantic Versioning (`vMAJOR.MINOR.PATCH`). Production adoption should pin against specific tagged releases.

---

## Validation & Verification Suite

Run all checks from the repository root (100% Python 3.10+ standard library, zero external pip dependencies required):

```bash
./scripts/run_tests.sh
```

The test runner reports the current test count and includes nested adversarial policy tests, verifying:
- **Operational Boundary Trials ([`test_agent_workflow_trials.py`](./tests/test_agent_workflow_trials.py))**: Simulated agent workflows across dirty trees, concurrent multi-change development, crash recovery, amended designs, and external installations.
- **Atomic Transactions & Crash Recovery ([`test_archive_recovery.py`](./tests/test_archive_recovery.py))**: Two-phase commit spec archiving, orphan journal recovery, and atomic ledger transitions.
- **Evidence Gates & Cryptographic Invariants ([`test_evidence_gates.py`](./tests/test_evidence_gates.py))**: Specification digest binding, contradictory result rejection, and post-review modification invalidation.
- **Permissions & External Actions ([`test_network_secret_governance.py`](./tests/permissions/test_network_secret_governance.py), [`test_external_action_adapter.py`](./tests/test_external_action_adapter.py))**: Scoped network, secret, cloud, GitHub, and provider-callback checks.
- **Durable Approvals & Identity ([`test_durable_approvals.py`](./tests/permissions/test_durable_approvals.py), [`test_identity_attacks.py`](./tests/identity/test_identity_attacks.py))**: Scope, expiry, revocation, non-transferability, and maker/checker rules.
- **Resource & Evaluation Controls ([`test_resource_governance.py`](./tests/convergence/test_resource_governance.py), [`test_evaluation_harness.py`](./tests/evaluation/test_evaluation_harness.py))**: Seven resource ceilings and local regression scenarios.
- **Event Replay & Integrity ([`test_event_stream.py`](./tests/verification/test_event_stream.py), [`test_deterministic_replay.py`](./tests/production/test_deterministic_replay.py))**: Hash-chain verification and deterministic state replay.
- **Team Operations & Diagnostics ([`test_team_operations.py`](./tests/test_team_operations.py))**: Preflight doctor checks, workflow profile deep-merging, and zero-loss state migrations.
- **Core Engine Mechanics ([`test_inspect_lifecycle.py`](./tests/test_inspect_lifecycle.py))**: Git checkpoints, safe rollback on renames, Git notes attachment, and RFC 5133 trailer generation.
- **Document Integrity ([`test_documents.py`](./tests/test_documents.py))**: Validates that all relative Markdown link targets exist on disk and that schema document examples adhere to contract.

### CLI Inspection & Auditing Tools

Preflight health diagnosis across runtime, git, skills, and configuration:
```bash
python3 skills/ship/scripts/inspect_lifecycle.py --doctor
```

Evaluate active engineering lifecycle state and verify gate readiness:
```bash
python3 skills/ship/scripts/inspect_lifecycle.py --status-check
```

Generate standard RFC 5133 Git commit trailers:
```bash
python3 skills/ship/scripts/inspect_lifecycle.py --generate-trailers --change <change>
```

Safely migrate legacy ledgers with an automatic byte-for-byte backup:
```bash
python3 skills/ship/scripts/inspect_lifecycle.py --migrate-state
```

Audit codebase technical debt markers and enforce documented limits in CI:
```bash
python3 skills/simplify/scripts/scan_debt.py --strict
```

Audit TDD test-to-code parity and detect assertless tests / whitebox spies:
```bash
python3 skills/tdd/scripts/verify_tdd.py --strict
```

Validate a reviewer or Judge report against the formal 12-field schema:
```bash
python3 skills/review/scripts/validate_report.py report.json
```

Inspect the new AgentFlow control surfaces:
```bash
agentflow events verify --path .
agentflow budget check --change <change>
agentflow benchmark --suite all
agentflow capability check <agent> --op NETWORK_READ --target "https://example.com/*"
```

These commands inspect or evaluate local state. They do not grant an agent access to
the operating system, a secret store, a cloud account, or a remote API.

Benchmark an empirical spike with warmup passes and latency percentiles (p50/p90/p95/p99):
```bash
python3 skills/spike/scripts/run_spike.py --cmd "python3 -c 'pass'" --iterations 100
```

Sample diverse and stratified traces for error discovery:
```bash
python3 skills/evals/scripts/sample_traces.py --input traces.jsonl --count 30 --output samples.jsonl
```

Launch the local zero-dependency trace review app:
```bash
python3 skills/evals/scripts/serve_review_app.py --samples samples.jsonl --port 8000
```

Calibrate LLM judges against human labels and calculate Rogan-Gladen corrections:
```bash
python3 skills/evals/scripts/score_calibration.py --input test_results.jsonl --p-obs 0.80
```

Audit a bugfix diff for reproduction tests, test weakening, and symptom masking:
```bash
python3 skills/debug/scripts/verify_fix.py --strict --test-cmd "pytest"
```

---

## Team Rollout

Start small. Run the skills locally on a few real tasks. Keep normal code review and host controls in place.

- **Local Team Rollout Guide ([`team_rollout.md`](./skills/ship/references/team_rollout.md))**: Detailed guide covering `--doctor` preflight, workflow profiles (`small-fix`, `standard`, `high-risk`), host capability adaptations (`auto`, `sequential`, `parallel`), pinned distributions (`install.sh --mode copy --backup`), and zero-loss ledger migration.
- **Behavioral Evaluation Cases & Pilot Benchmarks ([`skill_evaluations.md`](./tests/skill_evaluations.md))**: 12 realistic evaluation fixtures and acceptance criteria for benchmarking agent decisions, boundary respect, and defect detection before organizational distribution.
- **Headless CI & Asynchronous Automation ([`headless_ci_guide.md`](./skills/ship/references/headless_ci_guide.md))**: Pilot GitHub Actions templates with explicit design commit/digest approval and mandatory checks outside agent prompts. Repair proposals reuse the same gated workflow.
- **Local by default**: Ledgers, evidence, and logs stay on the machine or in the repository unless a host, command, or provider sends them elsewhere.

## Trust and execution boundaries

AgentFlow is a local workflow coordinator. The local user controls the ledger, identities,
approvals, and capabilities. Hashes detect changed content. They do not authenticate an
agent or create an immutable compliance log.

`agentflow capability check` evaluates policy and records a decision. A trusted host must
enforce it. The check does not stop a program that can ignore it. Use host permissions,
OS sandboxing, secret managers, and network policy for real containment. CLI commands run
with the user's permissions. Do not give untrusted agents direct access to the CLI or
writable ledger.

MCP tools that change state or run shell benchmarks are disabled by default. To enable
them, a trusted operator must set
`AGENTFLOW_MCP_ALLOW_MUTATIONS=1` in the server environment. This grants the connected
client those operations; it is not a sandbox. Shell benchmarks also require an agent,
operation, and target that pass the capability guard. Project test commands and
benchmarks still run with server/user privileges.

Install the CLI before `scripts/install.sh --mcp`, or use `--pip --mcp`. Registration
stores the resolved executable path and preserves malformed existing configuration
by failing without overwriting it. Pin a reviewed commit for a team pilot.

Delivery requires an independent execution receipt with verdict `VERIFIED`, matching
the current Git working-tree fingerprint. Run `agentflow verify --tier execution`
after source changes and before delivery. An empty or inconclusive receipt cannot pass.
Mutation verification is currently advisory and cannot claim success without execution.

Run the full suite with `PYTHON=python3.12 ./scripts/run_tests.sh` (or another supported
Python interpreter). Packaging and source imports are separate validation surfaces.
