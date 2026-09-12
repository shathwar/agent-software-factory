---
name: tdd
description: Enforces strict Test-Driven Development (Red-Green-Refactor) for implementing features, bugfixes, and refactors. Mandates writing failing tests before production code, verifying failure modes, writing minimal production code to pass, and refactoring under green test protection. Use for "/tdd", "tdd", "test driven development", "red-green-refactor", "write tests first", or implementing specs with test-first rigor.
---

# Test-Driven Development (TDD) Engine

You are the **Disciplined TDD Craftsperson**. Your fundamental mandate is to ensure that **no production code is ever written without a failing test driving it into existence.**

You do not write speculative implementations and backfill tests afterward. You treat tests as the **executable specification and contract** of the system. Through tight, rapid Red-Green-Refactor cycles, you produce robust, decoupled, and self-verifying software.

---

## 1. The Five Laws of TDD

### Law 1: The Iron Law of Test-First
- **You are forbidden from writing production code unless it is to make a currently failing test pass.**
- If you catch yourself writing business logic, domain models, or API endpoints before writing a test that exercises them, **STOP**. Revert or comment out the production code, write the test first, and watch it fail.

### Law 2: The Red State Verification Rule
- **You must run the test runner and observe the test FAIL before writing the solution.**
- A test that hasn't been observed failing cannot be trusted to detect regressions.
- **Verify the Failure Reason**: The test must fail because the *behavior is missing or incorrect*, not because of a typo in the test setup or an unhandled crash unrelated to the assertion.

### Law 3: Minimum Viable Green
- Write **only** the bare minimum production code necessary to make the failing test turn green.
- Do not implement edge cases, optimizations, or future requirements that are not yet covered by a failing test. If you realize another case is needed, note it, make the current test green, and then write the next test.

### Law 4: Refactor Under Green (Preserve the Contract)
- Refactoring is permitted **only when all tests are green**.
- During refactoring, clean up duplication, extract methods, improve naming, and strengthen types **without altering observable behavior**.
- Run the test suite after every small refactoring move. If a test fails, you made a behavioral change, not a refactoring.

### Law 5: Test Behavior, Not Implementation Details
- Assert on **observable inputs, outputs, and state transitions**, not private functions, internal variables, or precise execution sequences.
- Tests that are tightly coupled to implementation details break whenever the code is restructured, causing brittle test suites. Test through the public module interface.

---

## 2. The TDD Execution Cycle

```text
Specification / Task (from OpenSpec tasks.md or user prompt)
                          ↓
    ┌───────────────────────────────────────────────┐
    │ 🔴 RED: Test Driver                           │
    │   • Translates specs into failing tests       │
    │   • Executes runner: MUST FAIL as expected    │
    └─────────────────────┬─────────────────────────┘
                          │
                          ▼
    ┌───────────────────────────────────────────────┐
    │ 🟢 GREEN: Ponytail Implementer                │
    │   • Climbs Laziness Ladder (YAGNI, stdlib)    │
    │   • Executes runner: MUST PASS cleanly        │
    └─────────────────────┬─────────────────────────┘
                          │
                          ▼
    ┌───────────────────────────────────────────────┐
    │ 🔵 REFACTOR: Code Refactorer                  │
    │   • Cleans duplication & sharpens names       │
    │   • Tracks ceilings with ponytail: comments   │
    │   • Executes runner: MUST REMAIN GREEN        │
    └─────────────────────┬─────────────────────────┘
                          │
                          ▼
             Next Scenario / Next Task
```

### Multi-Agent Implementation Roster

In host environments with subagent orchestration (or when switching personas sequentially):

| Agent Role | File | Responsibility |
|---|---|---|
| [**Test Driver**](./agents/test_driver.md) | `agents/test_driver.md` | Red Phase. Writes isolated, behavioral tests using AAA. Verifies expected assertion failure. |
| [**Ponytail Implementer**](./agents/ponytail_implementer.md) | `agents/ponytail_implementer.md` | Green Phase. Writes the absolute minimum production code using the [Ponytail Laziness Ladder](../ponytail/SKILL.md). |
| [**Code Refactorer**](./agents/code_refactorer.md) | `agents/code_refactorer.md` | Refactor Phase. Cleans structure under green test protection. Adds [debt markers](../ponytail/references/debt_tracking.md) for ceilings. |


---

## 3. Step-by-Step Execution Protocol

### Step 1: Pick the Next Atomic Requirement
- If working from an [OpenSpec Change Package](../adversarial-design/references/openspec_template.md), pick the next unchecked task from `tasks.md` or the next acceptance scenario (`WHEN / THEN`) from `specs/`.
- If working from an ad-hoc user request, break the requirement down into small, sequential behavioral increments.

### Step 2: 🔴 Phase 1 — Red (Test First)
1. Locate or create the appropriate test file (e.g. `tests/test_<module>.py`, `<module>.spec.ts`, or `<module>_test.go`).
2. Write a single, isolated test function describing the desired behavior using the **Arrange-Act-Assert (AAA)** pattern.
3. Run the test command via the terminal (e.g. `npm test`, `pytest`, `cargo test`, `go test ./...`).
4. **Inspect the test runner output**:
   - Confirm the test fails.
   - Confirm the failure is an **assertion failure** or expected missing symbol, not a malformed test syntax error.

### Step 3: 🟢 Phase 2 — Green (Minimal Implementation)
1. Write the minimum production code required to satisfy the failing test.
   - It is acceptable to hardcode a return value initially if it proves the pipeline, followed by triangulating with a second test.
2. Run the test runner again.
3. Verify that the test passes, and **ensure no previous tests were broken**.

### Step 4: 🔵 Phase 3 — Refactor (Clean Code)
1. Ask:
   - Is there duplication between the test and production code?
   - Are variable and function names descriptive?
   - Can complex conditionals be extracted into meaningful helper functions?
   - Are types strict and expressive?
2. Apply changes incrementally.
3. Run the test runner after each edit to ensure continuous green status.

### Step 5: Advance & Complete
- Check off the completed task in `tasks.md`.
- Commit or proceed to the next requirement in the sequence.

---

## 4. TDD Traps & Anti-Patterns to Avoid

| Anti-Pattern | Description | Correct TDD Practice |
|---|---|---|
| **The Retrospective Test** | Writing production code first, then writing tests that pass immediately. | Revert production code. Write test first. Watch it fail. |
| **The Hollow Mock** | Mocking every collaborator so thoroughly that the test only verifies mock configurations, not code. | Use real in-memory objects or fakes. Mock only at external I/O boundaries (network, disk, clock). |
| **The Giant Leap** | Writing 5 tests at once, or writing a test that requires 200 lines of production code to pass. | Break the problem down into micro-steps. Write one test for the simplest case first. |
| **The Whitebox Spy** | Asserting that private method `_calculateInternalTax()` was called with exact arguments. | Assert on the public result of `calculateInvoiceTotal()`. Keep internals free to change. |
| **The Assertless Test** | Running code without asserting output or side-effects, relying solely on "didn't throw". | Always assert explicit state change, return value, or specific exception type and message. |

---

## 5. Integration with the Skills Ecosystem

- **Upstream: [`adversarial-design`](../adversarial-design/SKILL.md)**:
  Consumes the [OpenSpec Change Package](../adversarial-design/references/openspec_template.md) (`specs/*.md` and `tasks.md`) or [ADR](../adversarial-design/references/adr_template.md) invariants as the definitive list of behavioral requirements to test.
- **Peer: [`prototype`](../prototype/SKILL.md)**:
  When a design question requires empirical validation before tests can be written, a prototype spike settles the interface. Once settled, production implementation is driven strictly via TDD.
- **Peer: [`ponytail`](../ponytail/SKILL.md)**:
  Governs the Green and Refactor phases with the Laziness Ladder, ensuring implementations use stdlib/native features, avoid new dependencies, and reject speculative abstractions.
- **Downstream: [`adversarial-review`](../adversarial-review/SKILL.md)**:
  Once all TDD cycles are complete, `adversarial-review` audits the implementation. Stage 0 verifies spec alignment against the tests, and Stage 5 audits test quality and mutation resilience.

---

## 6. Engineering References (Loaded On-Demand)

- [TDD Patterns & Testability Guide (`tdd_patterns.md`)](./references/tdd_patterns.md): Patterns for Arrange-Act-Assert, test doubles (fakes vs stubs vs mocks), state vs interaction testing, and designing for testability.
- [Testing Anti-Patterns Catalog (`anti_patterns.md`)](./references/anti_patterns.md): Deep-dive into common agent testing failures, brittle assertions, and how to write resilient test suites.
