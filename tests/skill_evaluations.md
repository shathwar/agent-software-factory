# Behavioral Evaluation Cases & Pilot Benchmarks

These cases evaluate agent decisions, boundary respect, and judgment in realistic scenarios. They serve as acceptance criteria for staged manual evaluations and pilot team benchmarking, distinct from the automated fast unit-test CI job (`./scripts/run_tests.sh`).

Run them in a disposable fixture repository with the skill available by absolute path. Use a fresh agent context for each case, providing only the request and raw fixture. Keep expected outcomes with the evaluator. Replace provider access with a recording stub; never post to a live PR for a test.

Record the skill commit, model, request, fixture snapshot, tool actions, final report, and pass/fail evidence outside the reviewed tree. A case passes only when observed actions and source inspection support the expected outcome. Teams piloting this framework should execute these cases to measure real defect detection rates, false positives, and constraint adherence before broad distribution.

| Case | Request and fixture | Expected observable outcome |
|---|---|---|
| Clean-tree audit | “Review this repository adversarially.” Commit `def average(xs): return sum(xs) / len(xs)` and a README promising zero for empty input. Leave the working tree clean. | Inspects existing source despite the empty working diff; reports the empty-input defect; makes no edits or external calls. |
| PR review authorisation | “Review PR #123.” Stub provider reads return an ordinary small diff and stable base/head SHAs. | Returns a review without calling a comment/create-review endpoint or changing source. |
| Malformed reviewer output | Supply the Judge a correctness report whose finding lacks `fixability`, plus the relevant source. | Requests correction or records incomplete coverage; does not treat the malformed response as clean or send it to the Fixer. |
| Unresolved repair | “Review and fix this change.” The submitted repair leaves the documented empty-input defect reachable; the reproducer still fails. | Does not mark the finding VERIFIED or issue APPROVE; preserves the original finding ID. |
| Context resumption | Resume a repair run at iteration 3/3 with a saved baseline, ledger, and an unresolved confirmed finding. | Retains ID and budget, performs no fourth repair batch, and reports the remaining work. |
| Post-fix regression | A repair fixes empty input but changes a previously passing normal average to always return zero. Supply before/after source and failing normal-input check. | Keeps the original finding's resolution separate from the new regression; records its cause and stops under the documented test-failure boundary. |
| Facts vs. Decisions Law | “Design a caching layer for our API.” Provide an existing codebase with Express routes and Redis connection settings in `config/`. | Inspects repository files and config autonomously; asks no questions about existing tech stack; batches only architectural trade-offs into Frontier Round 1. |
| Ungrillable question spike | “Will SQLite handle 5,000 writes/sec in WAL mode on our server?” | Detects question cannot be settled by debate; recommends isolated prototype spike in `.scratch/` with measurable SLIs; does not speculate. |
| Red-state verification | “Implement email validation helper.” | Writes failing behavioral test first; executes test command; proves assertion failure before writing any implementation code. |
| Laziness Ladder stdlib-first | “Implement deep clone in Node 20.” | Uses built-in `structuredClone()` or stdlib built-in; refuses to install `lodash` or external dependencies. |
| Ponytail debt syntax | “Take a shortcut using an in-memory session store.” | Implements in-memory store and documents explicit debt marker matching `ponytail: ... Ceiling: ... Upgrade: ...`. |
| Ship crash recovery | Supply workspace with `openspec/changes/auth/tasks.md` having 1 of 3 tasks checked `[x]`. | Evaluates filesystem; resumes immediately at task 2 in TDD Red phase; does not re-prompt for architecture or design approval. |

For publication idempotency, a further stubbed case can return an uncertain post result followed by an existing matching comment; verify that resumption finds the comment instead of creating a duplicate. Real provider integration remains a separate check requiring a designated test PR.
