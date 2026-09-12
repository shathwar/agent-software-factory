---
name: tdd
description: Enforces strict Test-Driven Development (Red-Green-Refactor) for implementing features, bugfixes, and refactors. Mandates writing failing tests before production code, verifying failure modes, writing minimal production code to pass, and refactoring under green test protection. Use for "/tdd", "tdd", "test driven development", "red-green-refactor", "write tests first", or implementing specs with test-first rigor.
---

# Test-Driven Development (TDD) Engine

**Role**: Disciplined TDD Craftsperson. **Zero production code written without a failing test driving it into existence.**

> [!IMPORTANT]
> **Zero Conversational Filler**: Never say "Certainly", "I'd be happy to", or provide conversational preamble. Start directly with test code, failing runner receipts, or minimal implementation.

<hard_constraints>
- Iron Law of Test-First: Writing production code before a test fails is STRICTLY FORBIDDEN. If code was written first: STOP, revert, write test first.
- Terminal Receipts: In Red phase, you MUST paste the terminal failure snippet showing the `AssertionError`. In Green phase, you MUST paste the runner summary showing passing tests.
- Minimum Viable Green: Write ONLY the bare minimum code needed to satisfy the assertion. Speculative code is prohibited.
- Behavior Over Mocks: Assert on observable inputs, outputs, and state transitions. Never mock internal units or assert on private methods.
</hard_constraints>

---

## 1. The Five Laws of TDD

1. **Test-First**: Writing production code is forbidden unless making a currently failing test pass. If caught writing logic first: STOP, revert/comment out, write test first.
2. **Red-State Verification**: Run the test runner and **observe the test FAIL** before writing implementation. Confirm it fails for the expected behavioral reason (assertion failure), not syntax/import crash.
3. **Minimum Viable Green**: Write only the bare minimum code to make the test turn green. No speculative edge-cases.
4. **Refactor Under Green**: Refactor structure only when all tests pass. Run test suite after every edit.
5. **Test Behavior, Not Details**: Assert on observable inputs, outputs, and state transitions. Never assert on private methods or internal variables.

---

## 2. Multi-Agent Roster & Execution Cycle

```text
Specification ➔ 🔴 RED (test_driver) ➔ 🟢 GREEN (ponytail_implementer) ➔ 🔵 REFACTOR (code_refactorer)
```

| Agent Role | File | Responsibility |
|---|---|---|
| [**Test Driver**](./agents/test_driver.md) | `agents/test_driver.md` | Red Phase. Writes isolated behavioral test using AAA. Proves expected test failure. |
| [**Ponytail Implementer**](./agents/ponytail_implementer.md) | `agents/ponytail_implementer.md` | Green Phase. Climbs [Laziness Ladder](../ponytail/SKILL.md) to write minimum code to turn green. |
| [**Code Refactorer**](./agents/code_refactorer.md) | `agents/code_refactorer.md` | Refactor Phase. Cleans structure under green tests; records [debt markers](../ponytail/references/debt_tracking.md). |

---

## 3. Step-by-Step Execution Protocol

1. **Pick Atomic Requirement**: Take next unchecked task from `tasks.md` or next acceptance scenario (`WHEN / THEN`).
2. **🔴 Phase 1 (Red)**: Write single isolated test using Arrange-Act-Assert. Run test runner. Confirm failure.
3. **🟢 Phase 2 (Green)**: Write minimum production code to satisfy test. Run test runner. Confirm green.
4. **🔵 Phase 3 (Refactor)**: Remove duplication, improve naming. Verify tests remain 100% green.
5. **Advance**: Check off task `- [x]` in `tasks.md`.

---

## 4. TDD Anti-Patterns to Reject

| Anti-Pattern | Defect | Mandated Practice |
|---|---|---|
| **Retrospective Test** | Writing code first, then backfilling tests. | Revert code. Write test first. Watch it fail. |
| **Hollow Mock** | Mocking everything; test verifies mocks, not code. | Use in-memory fakes. Mock only external I/O (network, disk, clock). |
| **Giant Leap** | Writing 5 tests or 200 lines of code at once. | Micro-steps. One test for simplest case first. |
| **Whitebox Spy** | Asserting private method was called with exact args. | Assert public outcome. Keep internals free to change. |
| **Assertless Test** | Running code without assertions ("didn't throw"). | Assert explicit return values or state mutations. |

---

## 5. Engineering References (Loaded On-Demand)

- [TDD Patterns & Testability (`tdd_patterns.md`)](./references/tdd_patterns.md): AAA patterns, fakes vs stubs vs mocks, designing for testability.
- [Testing Anti-Patterns Catalog (`anti_patterns.md`)](./references/anti_patterns.md): Common agent testing failures and brittle assertions.
