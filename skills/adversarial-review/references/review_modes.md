# Targeted Review Modes & Intelligent Orchestration

To maintain low cognitive load and avoid wasting tokens analyzing irrelevant dimensions, the Principal Reviewer uses **Targeted Review Modes** and adaptive execution strategies. 

Instead of evaluating all 10 stages blindly on every diff, the orchestrator inspects the signals from `scripts/inspect_changes.sh` (or the user's explicit prompt) and activates **only the relevant review stages**.

---

## 1. Targeted Review Mode Matrix

| Change Profile | Detection Signal (`inspect_changes.sh` / Prompt) | Active Stages | Bypassed Stages (Preserves Low Cognition) | Handbook Chapter |
|---|---|---|---|---|
| **Standard Code Change** | Standard services, utilities, domain logic (no locks, APIs, or SQL) | **Spec (0)** + **Correctness (1)** + **Design (4 Simplicity & Smells, 5 Maintainability, 6 Reuse, 8 SOLID, 9 Patterns)** | Concurrency (2), Migrations, Public API Contracts | [`handbook_craftsmanship.md`](./handbook_craftsmanship.md) |
| **Shared State & Async** | `[!] CONCURRENCY REVIEW`<br>`[!] THREAD / ASYNC LIFECYCLE`<br>(`synchronized`, `Lock`, `ConcurrentHashMap`, `VirtualThread`, `Executor`, `asyncio`) | **Spec (0)** + **Correctness (1)** + **Concurrency / Safety (2)** + **Failure / Resilience (3)** + **Design (4–6, 8–9)** + **Performance (7, Orchestrator)** | Database Migrations, API Serialization (unless endpoints changed) | [`handbook_foundations.md`](./handbook_foundations.md) |
| **Database Migration** | `[!] MIGRATION REVIEW`<br>(`V*__*.sql`, `db/migration/`, `migrations/`, `schema.prisma`) | **Spec (0)** + **Correctness (1)** + **Migration Integrity** + **Production Risk** | Code SOLID / Patterns, Concurrency (unless table locking) | [`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Public API & Contract** | `[!] CONTRACT REVIEW`<br>(`*Controller*`, `@RestController`, `@Get`, `@Post`, `routes.py`, `proto`) | **Spec (0)** + **Correctness (1)** + **Contract & Backward Compatibility** + **Failure / Resilience (3)** | Internal Concurrency (unless async routes), DB Migrations | [`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Dependency & Build** | `[!] DEPENDENCY REVIEW`<br>(`pom.xml`, `package.json`, `requirements.txt`, `go.mod`) | **Production Risk** + **Dependency Compatibility** + **Dependency Simplicity (4)** | Code-level SOLID, Concurrency, Algorithmic performance | [`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Financial / Precision** | `[!] FINANCIAL / PRECISION REVIEW`<br>(`BigDecimal`, `stopLoss`, `trailing_sl`, `ltp`, `qty`, `pnl`) | **Spec (0)** + **Correctness (1)** + **Concurrency (2)** + **Domain/Presentation Separation** + **Design (4–6, 8–9, scoped to financial logic)** + **Production Risk** | Generic code style, speculative refactoring | [`handbook_foundations.md`](./handbook_foundations.md)<br>[`production_risk_matrix.md`](./production_risk_matrix.md) |
| **Full Adversarial Audit** | Explicit user prompt: *"do an adversarial review"*, *"full audit"*, *"zero-blindspot review"* | **All applicable stages + Production Risk Matrix** | None (Exhaustive baseline audit) | All Handbooks |

*Note on Stage 0 (Spec Alignment): If an issue key or spec document is detected, Stage 0 is evaluated in all modes. If no spec exists, Stage 0 is marked `[SKIPPED - No Spec Provided]` without blocking technical review.*

### Check the domain as well as the mode

Mode signals can miss risks in ordinary-looking changes. Add applicable checks below without expanding specialist ownership or adding agents:

| Domain | Extra focus | Owner |
|---|---|---|
| UI | Keyboard/accessibility behavior, state updates, effect cleanup | Correctness for observable behavior; Concurrency for async races; orchestrator for render cost |
| Infrastructure and scripts | Repeated execution, partial failures, rollback, privilege changes | Correctness for execution semantics; orchestrator for deployment/security risks |
| Security-sensitive boundaries | Input handling, server-side access control, secret exposure | Orchestrator's production-risk pass |

Combine checks when domains overlap. Assign each check once, mark the relevant scorecard area active, and retain the existing report and finding schema. Domain labels are routing hints, not proof of a defect.

### Phase 3 V1: Mode-to-Agent Routing

Use this table after selecting the active mode. It defines specialist passes for both execution strategies: delegate only the selected specialists in multi-agent mode; perform the same scoped passes locally in single-reviewer mode.

| Mode | Agents | Assigned focus |
|---|---|---|
| **STANDARD** | Correctness → Design | Correctness: business behavior and edge cases. Design: unnecessary complexity, Fowler smells, duplication, and coupling. |
| **SHARED STATE & ASYNC** | Correctness → Concurrency → Design | Correctness: sequential semantics and failure paths. Concurrency: shared state, interleavings, async lifecycle, blocking, cancellation, and timeouts. Design: unnecessary complexity. |
| **DATABASE MIGRATION** | Correctness | Migration integrity, data preservation, schema/consumer compatibility, idempotency, and rollback correctness remain within Correctness. |
| **PUBLIC API** | Correctness | API contracts, serialization, validation, error behavior, and backwards compatibility remain within Correctness. |
| **DEPENDENCY & BUILD** | Correctness → Design | Correctness: dependency/build compatibility. Design: unnecessary dependencies and dependency complexity only. |
| **FINANCIAL** | Correctness → Concurrency → Design | Correctness: precision, rounding, financial invariants, and domain/presentation behavior. Concurrency: concurrent updates and duplicate execution. Design: unnecessary complexity and duplication in financial logic. |
| **FULL ADVERSARIAL AUDIT** | Correctness → Concurrency → Design | All three axes, each within its strict ownership; the orchestrator covers remaining active checks. |

Arrows list selected agents, not a serial execution order. In multi-agent mode, selected agents work independently in parallel. Mark unselected specialists `SKIPPED - Mode Scope` without launching them.

For mixed changes, take the union of applicable modes and merge assignments into one task per selected specialist. Add Concurrency for migration locking/coordination hazards or async API execution. Assign those hazards only to Concurrency; Correctness retains migration integrity or contract semantics. Add Design only when another applicable mode activates complexity checks.

The orchestrator retains spec alignment, general performance (including migration query/index costs), and cross-cutting production risks such as rollout availability, security advisories, and license constraints. These checks do not expand specialist scopes. Do not create Production/Migration or Contract reviewers in V1; reconsider a split only if review testing demonstrates a coverage or ownership problem.

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
  - `ConcurrentHashMap` compound atomicity: verify compound operations use a suitable atomic primitive or consistent external locking.
  - Virtual thread pinning: verify the JDK version and blocking path before claiming pinning; monitor behavior changed in JDK 24.
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

## 3. Multi-Agent Review Protocol

For diffs exceeding 400 lines or an explicit parallel-review request, use the environment's available subagent tool to dispatch the specialists selected by the mode-to-agent routing table concurrently. Inherit the orchestrator's model settings. These Markdown files are role prompts to load into subagent tasks, not automatically registered agents.

```text
Principal Orchestrator → inspect_changes.sh → review_modes.md
                                              │
                         ┌────────────────────┼───────────────────┐
                         ↓                    ↓                   ↓
                    Correctness          Concurrency            Design
                         └────────────────────┼───────────────────┘
                                              ↓
                               Review Judge (agents/review_judge.md)
                                              ↓
                                   Structured Final Findings
```

| Specialist prompt | Ownership |
|---|---|
| [Correctness Reviewer](../agents/correctness_reviewer.md) | Stage 1; sequential failure paths and resource lifecycle (3); contracts, compatibility, migrations, and related production risks when active |
| [Concurrency Reviewer](../agents/concurrency_reviewer.md) | Stage 2; async lifecycle, blocking, cancellation, timeouts, and related resilience (3) and capacity risks |
| [Design Reviewer](../agents/design_reviewer.md) | Unnecessary complexity across Stages 4–6 and 8–9; unnecessary dependencies |

The Principal Orchestrator retains Stage 0 (spec alignment), cross-cutting production risk, and any active checks outside these assignments. Assign every active check one owner according to its root cause. The Principal retains Stage 7 algorithmic and query costs; executor capacity and starvation belong to Concurrency. Specialist ownership does not activate otherwise irrelevant stages. The orchestrator records a specialist with no active scope as `SKIPPED - Mode Scope` and does not dispatch it.

### Dispatch and handoff

Provide each specialist its role file, the finding schema, selected mode as context and only that specialist’s assigned active checks and files, the same diff/base revision, changed-file list, repository root and standards, available specs, and discovered test/caller context. Allow access to complete source files and relevant consumers; the diff alone is insufficient. Load handbooks only as needed.

The orchestrator already knows the active review mode. Never dispatch “review everything” or ask specialists to reselect the mode. Use these bounded task instructions with the assigned checks and files:

- **Correctness**: “Find correctness problems. Review sequential behavior and contracts within the assigned scope.”
- **Concurrency**: “Find concurrency problems. Review shared state, coordination, and async execution within the assigned scope.”
- **Design**: “Find unnecessary complexity. Review simplicity and maintenance cost within the assigned scope.”

For example, a standard code change assigns correctness checks to Correctness and complexity checks to Design; Concurrency is skipped. A full audit considers all axes but skips demonstrably inapplicable checks and does not broaden any specialist’s ownership. The Principal handles remaining active checks.

Specialists review independently and return the identical [JSON agent output](./finding_schema.md#5-required-agent-output-json): `reviewer`, `status`, `findings`, `coverage`, `questions`, and `routing_notes`. Each finding uses exactly the shared 12-field contract; no specialist-specific schema is allowed. Keep candidate IDs local to each report until adjudication. Missing evidence is a limitation or question, not a fabricated finding. For an incidental out-of-scope concern, return only a routing note with its location and reason, separate from candidate findings. The orchestrator assigns it to one owner based on the root cause; specialists do not investigate or report findings on another axis. Specialists must not edit source files or make final deployment decisions.

### Focused checks within each assigned scope

In post-fix passes, verify assigned repairs and inspect the changed patch for new in-scope defects. Re-evaluate mode signals for that patch; review is not limited to specialists who raised the original findings. Keep resolution evidence in `coverage` and candidate defects in `findings`, following [review_loop.md](./review_loop.md#new-findings-after-a-fix).

**Test gaps:** Connect each suggested test to a changed behavior, triggering input or interleaving, expected outcome, and the regression it would detect. Inspect existing unit and integration tests before declaring a gap; neither an unchanged test file nor a coverage percentage proves missing behavioral coverage. Skip low-value completeness tests. Record inspected coverage and justified gaps in `coverage`, and uncertainty in `questions`, using the existing envelope. The orchestrator verifies these notes before rendering the Testing Gaps section. A test gap alone is not a confirmed code defect or permission for the Fixer to edit.

**Comment accuracy:** When changed code or documentation affects a claim, verify it against the implementation: parameters, return values, errors, side effects, and stated guarantees. Route by subject: behavior to Correctness, thread safety to Concurrency, performance to the orchestrator, and maintenance clarity to Design. Quote the misleading claim and cite the contradictory code in the existing finding fields. Report a concrete consequence, not a demand for more comments or a preferred writing style. Documentation-only changes can activate the owner of the claim; do not automatically launch all reviewers.

**Types and failure paths:** Assign invariant enforcement and sequential recovery behavior to Correctness, async failure propagation to Concurrency, and the complexity of design remedies to Design. Use the foundations handbook for the detailed checks. No new specialist or scoring scale is needed.

### Parallel execution and independence

1. **Prepare once.** Establish a common reviewed snapshot, selected mode, and factual context before dispatch. Give each specialist only its role, assigned checks, shared source context, and output contract. Exclude other reviewers' findings, preliminary verdicts, and the orchestrator's suspected defects from initial prompts. Use fresh agent contexts where supported rather than forking accumulated review conclusions.
2. **Launch before waiting.** Start every selected specialist without waiting for any specialist to finish. Sequential calls to a nonblocking spawn tool are acceptable: the review work must overlap. Do not run Correctness to completion and feed its report into Concurrency or Design. While specialists work, the orchestrator can perform its retained checks independently.
3. **Keep first passes independent.** Specialists return reports to the orchestrator, not to one another. Do not broadcast early findings or ask one specialist to critique another during its initial pass. Hold incidental routing notes until initial reports are collected. If an essential factual clarification changes the shared context, provide it to all affected agents without sharing conclusions; if the reviewed source changes, restore the agreed snapshot or restart affected passes on one new snapshot.
4. **Collect all outcomes.** Wait for every selected specialist to finish or reach an explicitly recorded failed, cancelled, or unavailable outcome. One early report must not trigger the Judge or cancel other axes. Preserve completed reports and mark missing/incomplete coverage honestly. If worker capacity is limited, schedule independent passes in available slots without passing earlier findings to later agents, and record reduced parallelism internally.
5. **Join before adjudication.** Once initial outcomes and the orchestrator's retained checks are collected, handle routing notes or needed corrections through focused follow-ups. Then give the Judge the collected reports and coverage records. Evidence-based conflict clarification may occur during adjudication; it must not be represented as an independent initial finding.

Conceptual scheduling (pseudocode, not a tool API):

```text
context = prepare_common_snapshot_and_mode()
handles = []
for specialist in selected_specialists(context.mode):
    handles.append(start_nonblocking(specialist, scoped_context(context)))
retained_checks = review_orchestrator_scope(context)
outcomes = collect_all_outcomes(handles)
reports = resolve_required_followups(outcomes)
result = run_judge(context, reports, retained_checks)
```

Do not claim parallel execution when only one specialist is selected, no delegation is available, or capacity forces serial work. In those cases preserve the same scope and reporting contracts and record how the review actually ran internally; explain it truthfully if the user asks.

### Review Judge

After the parallel collection and follow-up barrier above, dispatch the [Judge](../agents/review_judge.md) with change context, reviewed snapshot, selected mode, assignments, specialist JSON reports, and explicit coverage records for skipped or incomplete work. Include any candidates from the orchestrator's retained checks as a separately identified source using the same 12-field contract. The Judge is an adjudicator, not an additional discovery specialist.

The Judge deduplicates, independently inspects relevant code to validate claims, rejects false positives, resolves conflicts, prioritises, and returns final findings using the shared JSON contract. It must not accept findings solely from specialist reports or discover additional problems. Follow `review_judge.md` for the acceptance gate and per-candidate disposition records. Apply its [disagreement rules](../agents/review_judge.md#disagreement-handling): a clean report on another axis is not counterevidence, specialist claims require independent verification, and evidence resolves actual conflicts without voting.

The orchestrator renders the unchanged [Phase 2 report template](../SKILL.md#4-standardized-output-format) from the Judge's accepted findings and coverage limitations. Agent identities, execution strategy, and adjudication records remain internal. Any new candidate must be reviewed and adjudicated before publication.

If delegation is unavailable, the Principal performs the scoped specialist passes and then a separate adjudication pass using `review_judge.md`, re-opening relevant code before acceptance and recording internally that no separate agent ran. The standard single-reviewer path remains the default for diffs of 400 lines or fewer and applies the same adjudication rules.

---

### Optional implementation after adjudication

Run requested repairs under [review_loop.md](./review_loop.md), including bounded rounds and verification of the combined patch. These loop rules govern repeated handoffs; initial review routing remains unchanged.

For a user-requested fix task, route `Judge → approved findings → [Code Fixer](../agents/code_fixer.md)`. Construct a fresh handoff containing only entries from the Judge's final `findings` array that are within the user's fix scope, their final IDs, and the source snapshot and implementation context. Do not forward the full Judge envelope or raw specialist reports. Preserve approval provenance in the handoff so the Fixer can verify the assigned set without re-evaluating candidates.

A Judge report with incomplete coverage may contain accepted findings; only accepted entries marked `autonomous` are eligible for code changes. Accepted `requires-human` entries are passed through for a decision request, with no code changed for those findings. Deferred candidates and unresolved questions are never eligible. Problems applying an accepted fix return to the orchestrator for clarification, not to the Fixer for a new verdict. Review-only requests do not launch the Fixer.

---

## 4. Scorecard Adaptation in Targeted Modes

Preserve the stage-based Phase 2 scorecard; do not replace it with agent status rows. Map internal outcomes to the presentation rules in `SKILL.md`: completed checks can support PASS, substantiated defects support FAIL, and incomplete verification requires WARN with the substantive limitation. An empty findings array or a completed Judge pass alone never establishes PASS.

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
