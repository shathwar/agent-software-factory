# Architectural Invariants Contract

An **Architectural Invariant** is a non-negotiable rule of system design codified by the engineering team to protect consistency, reliability, and security across the codebase.

When a repository contains an `ARCHITECTURAL_INVARIANTS.md` file in its root or docs directory, the review engine and `/ship` orchestrator treat it as an authoritative, binding contract.

---

## 1. Structure of `ARCHITECTURAL_INVARIANTS.md`

Repositories declare invariants using this standard format:

```markdown
# Architectural Invariants

## INV-001: Transactional Persistence Boundaries
- **Rule**: All state-mutating service operations MUST execute within an atomic transaction. Direct database writes from HTTP controllers or event consumers are strictly forbidden.
- **Enforcement**: Static inspection, unit tests wrapping service calls in rollback tests.
- **Blast Radius**: Data corruption, partial writes, split-brain states.

## INV-002: Universal UTC Timestamps
- **Rule**: All timestamps stored in databases, serialized in JSON, or transmitted over network boundaries MUST use UTC (ISO 8601 `Z`).
- **Enforcement**: Serializer tests, schema validation.
- **Blast Radius**: Timezone skew, scheduling race conditions, inaccurate audit trails.

## INV-003: Idempotent External Webhooks
- **Rule**: Outbound webhooks and payment event consumers MUST supply and verify an idempotency key with minimum 24-hour TTL.
- **Enforcement**: Ephemeral database double-execution tests.
- **Blast Radius**: Duplicate charges, repeated event processing.
```

---

## 2. Review Engine Evaluation Protocol

During code review ([`review/SKILL.md`](../SKILL.md)), the orchestrator inspects the repository root for `ARCHITECTURAL_INVARIANTS.md`:

1. **Discovery**: Read `ARCHITECTURAL_INVARIANTS.md` if present. If absent, this evaluation is skipped cleanly without error.
2. **Diff & Caller Scrutiny**: For every changed file and affected caller, verify whether the diff:
   - Violates an invariant rule directly (e.g. executing a raw database insert without a transaction).
   - Bypasses an existing architectural boundary (e.g. importing internal modules across package walls).
   - Changes a contract without updating the invariant document.
3. **Adjudication & Finding Mapping**:
   - **Violation**: If code breaches an invariant without an explicit ADR authorization, file a finding with:
     - `category`: `ProductionRisk` (or `Correctness`)
     - `severity`: `CRITICAL` (P0) or `HIGH` (P1)
     - `confidence`: 1.0 (CERTAIN)
     - `problem`: Cites the specific invariant ID (e.g. `INV-001`) and the contradictory code trigger.
4. **Rollback Guard**:
   - If an invariant is broken fundamentally, the Review Judge issues a `FAIL` report, halting delivery and triggering:
     ```bash
     python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --rollback design
     ```

---

## 3. Runtime Execution Rings (Privilege Lattice)

Adapted from the **Microsoft Agent Governance Toolkit (AGT ADR 0002)**, system privilege and blast radius are structured into four runtime execution rings rather than static RBAC roles:

```text
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ Ring 0: Hypervisor & Ledger (Immutable)                                │
 │ • .ship/state.json, Git notes, private refs (refs/ship/*), receipts     │
 │ • Write Access: STRICTLY RESTRICTED to inspect_lifecycle.py & human merge│
 ├─────────────────────────────────────────────────────────────────────────┤
 │ Ring 1: Architecture & Governance (Design-Gate Locked)                  │
 │ • ARCHITECTURAL_INVARIANTS.md, .ship.json, ADRs, OpenSpec change specs  │
 │ • Write Access: ONLY during /design gate with explicit human approval   │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ Ring 2: Production Code & Tests (TDD / Ship Dev)                        │
 │ • Application source, unit tests, integration tests, configs            │
 │ • Write Access: Autonomous dev agents governed by PreTool safety hooks   │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ Ring 3: Disposable Workspace & Scratch (Sandboxed)                      │
 │ • .scratch/, build/, dist/, __pycache__, .pytest_cache, node_modules    │
 │ • Write/Delete Access: Fully disposable; approved cleanup targets       │
 └─────────────────────────────────────────────────────────────────────────┘
```

### Ring Enforcement Invariants

1. **Ring 0 Invariant**: Autonomous coding agents (`ship-dev`, `ship-fix`) MUST NEVER directly write to `.ship/state.json` or synthesize `refs/ship/*` Git notes. All state transitions must be generated deterministically by `inspect_lifecycle.py`.
2. **Ring 1 Invariant**: Invariant documents and `.ship.json` gate configs cannot be silently modified during implementation (`/tdd` or `/simplify`). Modifying an architectural invariant requires an authorized Architecture Decision Record (ADR) approved at the `/design` gate.
3. **Ring 2 Invariant**: Changes to production code must strictly adhere to TDD Red-Green-Refactor, pass all lint/type checks, and remain within approved branch boundaries.
4. **Ring 3 Invariant**: Disposable artifacts can be purged via `rm -rf` by agents, provided targets match the approved `SAFE_CLEANUP_TARGETS` allowlist.

---

## 4. The "No Orphan Agents" Invariant (Accountability Traceability)

Adapted from **Agent Guard (`docs/DESIGN.md`)**, every autonomous agent execution in the repository must adhere to the foundational security axiom:

> *"Every agent has an accountable human sponsor. No orphan agents."*

### Accountability Rules

1. **Human Sponsor Attribution**:
   - Every autonomous Pull Request, Git commit trailer, and lifecycle state record must explicitly bind to the human engineer who initiated or authorized the execution (`Sponsored-By: @<username>` or `Sponsor-Identity: <id>`).
   - Autonomous agents executing headlessly in CI derive their sponsor from the GitHub event actor (the user who created, assigned, or labeled the issue).
2. **Zero Orphan Execution**:
   - Un-sponsored or un-attributable automated actions in production repositories are strictly prohibited and fail closed.
3. **Responsibility Invariance**:
   - An autonomous agent can draft code, execute tests, and package commits, but authority and accountability remain invariant: the human sponsor is accountable for the correctness, architectural integrity, and production safety of the merged artifact.


