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
