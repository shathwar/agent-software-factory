# OpenSpec Change Package Template

This document defines the OpenSpec specification format supported by `/adversarial-design`. When selected at the confirmation gate, the skill generates an executable OpenSpec change package under `openspec/changes/<change-name>/`.

This package complements the Architecture Decision Record (ADR) by providing **formal behavioral requirements (RFC 2119 `SHALL`)**, **executable Gherkin scenarios (`WHEN/THEN`)**, and a **decomposed task list (`tasks.md`)** for implementation agents and [`adversarial-review`](../../adversarial-review/SKILL.md) Stage 0 verification.

---

## 1. Directory Structure

```text
openspec/changes/<change-name>/
├── proposal.md       # Purpose, problem statement, and scope
├── specs/            # Behavioral requirements and concrete scenarios
│   └── <feature>.md
├── design.md         # Technical architecture and invariants (from the ADR)
└── tasks.md          # Implementation checklist for developers and agents
```

---

## 2. File Specifications

### `proposal.md`
```markdown
# Change Proposal: [Feature Name]

## 1. Problem Statement
[Describe the problem from the user/system perspective.]

## 2. Proposed Changes
- [High-level summary of additions, modifications, and removals]

## 3. Capabilities
- **Added**: [New capabilities introduced]
- **Modified**: [Existing capabilities altered]
- **Removed**: [Capabilities deprecated or deleted]

## 4. Non-Goals / Out of Scope
- [Explicitly state what is NOT included to prevent scope creep]
```

---

### `specs/<feature>.md`
```markdown
# Specification: [Capability Name]

## ADDED Requirements

### Requirement: [Concise Requirement Title]
The system SHALL [formal statement of requirement using RFC 2119 keyword SHALL / MUST].

#### Scenario: [Happy Path Scenario Name]
- **GIVEN** [Initial system state or preconditions]
- **WHEN** [Action or event triggers the behavior]
- **THEN** [Expected observable outcome or state change]
- **AND** [Additional outcome]

#### Scenario: [Failure / Edge Case Scenario Name]
- **GIVEN** [Initial state]
- **WHEN** [Error, network timeout, or invalid input occurs]
- **THEN** [Expected containment, error code, or fallback behavior]
- **AND** [State remains consistent with zero data corruption]
```

---

### `design.md`
```markdown
# Technical Design: [Feature Name]

## 1. Architecture Overview
[High-level component flow and data pipelines settled during the interview.]

## 2. Invariants & Critical Guarantees
- **State & Consistency**: [Single source of truth, atomic boundaries]
- **Concurrency & Locking**: [Lock granularity, TOCTOU defense, idempotency key TTL]
- **Resilience & Timeouts**: [Exact socket/connection timeouts, backoff with jitter, circuit breakers]
- **Data & Migration**: [Zero-downtime migration steps, index coverage]

## 3. Reference Architecture Decision Record
- Links to or embeds the authoritative ADR: `docs/adr/ADR-<NNNN>-<topic>.md`
```

---

### `tasks.md`
```markdown
# Implementation Tasks

## 1. Foundations & Data Models
- [ ] 1.1 Create database migration script with composite index on filter columns
- [ ] 1.2 Define domain entity and immutable value objects

## 2. Core Business Logic & Concurrency
- [ ] 2.1 Implement evaluation engine with atomic `computeIfAbsent`
- [ ] 2.2 Add idempotency key validation and deduplication filter

## 3. Network Boundaries & Failure Handling
- [ ] 3.1 Configure explicit 500ms connection and 2000ms read timeouts on HTTP/RPC client
- [ ] 3.2 Add exponential backoff retry handler with full jitter

## 4. Verification & Testing
- [ ] 4.1 Unit tests for boundary edge cases (nulls, zero, overflow)
- [ ] 4.2 Concurrent stress test validating mutual exclusion
```

---

## 3. Integration with `adversarial-review`

When the feature implementation is complete, [`adversarial-review`](../../adversarial-review/SKILL.md) automatically inspects `openspec/changes/<change-name>/specs/`:
1. **Missing Requirements**: If any `SHALL` statement or `Scenario` in `specs/` is not implemented in code, it is flagged as a **`[HIGH] SpecAlignment` defect**.
2. **Scope Creep**: If code introduces capabilities or APIs not specified in `proposal.md`, it is flagged as **`[MEDIUM] SpecAlignment (Scope Creep)`**.
3. **Behavioral Divergence**: If code behaves differently than the `WHEN/THEN` outcome, it is flagged as a **`[CRITICAL] Correctness / SpecAlignment` defect**.
