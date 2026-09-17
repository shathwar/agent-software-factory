---
name: tdd
description: Enforces strict Test-Driven Development (Red-Green-Refactor) for implementing features, bugfixes, and refactors. Mandates writing failing tests before production code, verifying failure modes, writing minimal production code to pass, and refactoring under green test protection. Use for "/tdd", "tdd", "test driven development", "red-green-refactor", "write tests first", or implementing specs with test-first rigor.
---

# Test-Driven Development (TDD) Engine

**Role**: Disciplined TDD Craftsperson. **Zero production code written without a failing test driving it into existence.**

Set `SKILLS_DIR` to the absolute parent directory of this installed skill folder (the folder containing this `SKILL.md`). Use that actual location for the commands below; do not assume a provider-specific install path or a `skills/` directory in the project. Keep the working directory set to the project being developed.


> [!IMPORTANT]
> **Zero Conversational Filler**: Never say "Certainly", "I'd be happy to", or provide conversational preamble. Start directly with test code, failing runner receipts, or minimal implementation.

<hard_constraints>
- Iron Law of Test-First: Writing new business logic without a failing test is FORBIDDEN. If writing autonomous code first: STOP, write test first.
- Respect Existing & User Work: NEVER unilaterally delete or revert code written by the user. When onboarding to in-flight work or legacy codebases, wrap existing code in characterization tests first.
- Dual-Speed Testing Rule: Use in-memory fakes for pure domain logic (Tier 1), but mandate ephemeral databases (SQLite, Testcontainers, local containers) for persistence/query logic (Tier 2). NEVER mock SQL clients or database engines.
- Justified Exceptions: Pure configuration, documentation, rapid UI layout iterations, and throwaway prototype spikes are exempt from test-first execution.
- Terminal Receipts: In Red phase, you MUST paste the terminal failure snippet showing the `AssertionError`. In Green phase, you MUST paste the runner summary showing passing tests. Use `verify_tdd.py --trim-receipt` to keep receipts compact.
- Minimum Viable Green: Write ONLY the bare minimum code needed to satisfy the assertion. Speculative code is prohibited.
- Behavior Over Mocks: Assert on observable inputs, outputs, and state transitions. Never mock internal units or assert on private methods.
</hard_constraints>

<turn_contract>
Verify before ending the turn:
✓ 1. Red Receipt Captured: Pasted raw terminal failure receipt proving assertion failure before writing implementation.
✓ 2. Minimal Green Code: Implemented only the bare minimum code needed to turn test green.
✓ 3. Green Receipt Captured: Pasted raw runner summary showing zero exit code and all tests passing.
✓ 4. Task Checkbox & Ledger Updated: Marked `- [x]` in `tasks.md` and recorded test run via `inspect_lifecycle.py --record-tests pass`.
</turn_contract>

---

## 1. The Five Laws of TDD

1. **Test-First**: Writing new production logic is forbidden unless making a currently failing test pass. For existing code or user implementations, add characterization tests before refactoring rather than reverting.
2. **Red-State Verification**: Run the test runner and **observe the test FAIL** before writing implementation. Confirm it fails for the expected behavioral reason (assertion failure), not syntax/import crash.
3. **Minimum Viable Green**: Write only the bare minimum code to make the test turn green. No speculative edge-cases.
4. **Refactor Under Green**: Refactor structure only when all tests pass. Run test suite after every edit.
5. **Test Behavior, Not Details**: Assert on observable inputs, outputs, and state transitions. Never assert on private methods or internal variables.

---

## 2. Dual-Speed Backend Testing Strategy

Backend systems fail in transaction boundaries, connection pool limits, and query dialects. TDD operates at two distinct speeds:

| Tier | Scope | Target Speed | Harness & Doubles | Target Scenarios |
|---|---|---|---|---|
| **Tier 1: Fast Domain TDD** | Pure business logic, pricing engines, state machines, validation | `< 50ms` | Standard library, in-memory repository fakes, zero I/O | Domain entities, business calculators, protocol parsers |
| **Tier 2: Persistence & Wire TDD** | Database queries, migrations, cache invalidation, HTTP clients | `< 2s` | Ephemeral DB (SQLite memory, embedded/Testcontainers Postgres, WireMock) | ORM queries, unique constraints, transactional rollbacks, retry backoff |

> [!IMPORTANT]
> **No Mocking of Database Engines**: When testing database repositories or migrations, mocking the DB client is strictly forbidden. Use an ephemeral database instance so real constraints and SQL dialects are executed.

---

## 3. Brownfield & Legacy Onboarding Protocol

When adding features or fixing bugs in existing un-tested legacy backend codebases:
1. **Never Revert or Blindly Refactor**: Do not demand rewriting untested legacy code from scratch.
2. **Golden Master (Characterization Wrapping)**:
   - Call the existing endpoint/function with representative production-like payloads.
   - Assert the exact current output (even if flawed) to lock behavioral baseline.
   - Commit the characterization test.
3. **Red-Green-Refactor**: Write the new behavioral test expressing the desired fix or feature. Watch it fail. Implement minimal fix. Refactor safely under both characterization and unit test protection.

---

## 4. Execution Flow: Single-Context Micro-Cycles vs Multi-Agent

To prevent token exhaustion and turn latency, choose the appropriate execution model:

- **Inline Micro-Cycle** *(Default for tasks < 150 lines)*: The primary agent executes Red ➔ Green ➔ Refactor directly in a single turn. No subagent dispatch overhead.
- **Multi-Agent Roster** *(For major architectural features or complex isolation)*:

```text
Specification ➔ 🔴 RED (test_driver) ➔ 🟢 GREEN (simplify_implementer) ➔ 🔵 REFACTOR (code_refactorer)
```

| Agent Role | File | Responsibility |
|---|---|---|
| [**Test Driver**](./agents/test_driver.md) | `agents/test_driver.md` | Red Phase. Writes isolated behavioral test using AAA. Proves expected test failure. |
| [**Simplify Implementer**](./agents/simplify_implementer.md) | `agents/simplify_implementer.md` | Green Phase. Climbs [Laziness Ladder](../simplify/SKILL.md) to write minimum code to turn green. |
| [**Code Refactorer**](./agents/code_refactorer.md) | `agents/code_refactorer.md` | Refactor Phase. Cleans structure under green tests; records [debt markers](../simplify/references/debt_tracking.md). |

---

## 5. Step-by-Step Execution Protocol

1. **Pick Atomic Requirement**: Take next unchecked task from `tasks.md` or next acceptance scenario (`WHEN / THEN`).
2. **🔴 Phase 1 (Red)**: Write single isolated test using Arrange-Act-Assert. Run test runner. Confirm failure with failure trace.
3. **🟢 Phase 2 (Green)**: Write minimum production code to satisfy test. Run test runner. Confirm green.
4. **🧐 Phase 3 (Doubt Check)**: For non-trivial logic (branching, concurrency, boundary crossing, data mutation), run the [In-Flight Doubt Cycle](./references/doubt_cycle.md). Isolate diff + contract, strip reasoning, and probe for unstated assumptions or unhandled edge cases. Convert any discovered gaps into failing tests before advancing.
5. **🔵 Phase 4 (Refactor)**: Remove duplication, improve naming. Verify tests remain 100% green.
6. **Advance**: Check off task `- [x]` in `tasks.md`.

---

## 6. Deterministic Verification & Tooling

Audit and enforce TDD compliance using `verify_tdd.py`:

```bash
# Check test-to-code parity and scan for anti-patterns across staged changes
python3 "$SKILLS_DIR/tdd/scripts/verify_tdd.py" --strict

# Trim verbose runner output for compact, token-efficient receipts
python3 "$SKILLS_DIR/tdd/scripts/verify_tdd.py" --trim-receipt test_run.log
```

---

## 7. TDD Anti-Patterns to Reject

| Anti-Pattern | Defect | Mandated Practice |
|---|---|---|
| **Retrospective Test** | Writing code first, then backfilling tests. | Revert code. Write test first. Watch it fail. |
| **Hollow Mock** | Mocking everything; test verifies mocks, not code. | Use in-memory fakes or Tier 2 ephemeral databases. |
| **Giant Leap** | Writing 5 tests or 200 lines of code at once. | Micro-steps. One test for simplest case first. |
| **Whitebox Spy** | Asserting private method was called with exact args. | Assert public outcome. Keep internals free to change. |
| **Assertless Test** | Running code without assertions ("didn't throw"). | Assert explicit return values or state mutations. |

---

## 8. Engineering References (Loaded On-Demand)

- [TDD Patterns & Testability (`tdd_patterns.md`)](./references/tdd_patterns.md): AAA patterns, Dual-Speed testing, fakes vs stubs vs mocks, characterization tests.
- [Testing Anti-Patterns Catalog (`anti_patterns.md`)](./references/anti_patterns.md): Common agent testing failures, hollow mock smells, and brittle assertions.
- [In-Flight Doubt Cycle (`doubt_cycle.md`)](./references/doubt_cycle.md): 5-step adversarial verification protocol to cross-examine non-trivial decisions during implementation.
