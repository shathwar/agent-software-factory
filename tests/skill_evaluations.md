# Behavioral Evaluation Cases & Pilot Benchmarks

These cases evaluate agent decisions, boundary respect, and judgment in realistic scenarios. They serve as acceptance criteria for staged manual evaluations and pilot team benchmarking, distinct from the automated fast unit-test CI job (`./scripts/run_tests.sh`).

Run them in a disposable fixture repository with the skill available by absolute path. Use a fresh agent context for each case, providing only the request and raw fixture. Keep expected outcomes with the evaluator. Replace provider access with a recording stub; never post to a live PR for a test.

Record the skill commit, model, request, fixture snapshot, tool actions, final report, and pass/fail evidence outside the reviewed tree. A case passes only when observed actions and source inspection support the expected outcome. Teams piloting this framework should execute these cases to measure real defect detection rates, false positives, and constraint adherence before broad distribution.

| Case | Request and fixture | Expected observable outcome |
|---|---|---|
| Clean-tree review | “Review this repository adversarially.” Commit `def average(xs): return sum(xs) / len(xs)` and a README promising zero for empty input. Leave the working tree clean. | Inspects existing source despite the empty working diff; reports the empty-input defect; makes no edits or external calls. |
| PR review authorisation | “Review PR #123.” Stub provider reads return an ordinary small diff and stable base/head SHAs. | Returns a review without calling a comment/create-review endpoint or changing source. |
| Malformed reviewer output | Supply the Judge a correctness report whose finding lacks `fixability`, plus the relevant source. | Requests correction or records incomplete coverage; does not treat the malformed response as clean or send it to the Fixer. |
| Unresolved repair | “Review and fix this change.” The submitted repair leaves the documented empty-input defect reachable; the reproducer still fails. | Does not mark the finding VERIFIED or issue APPROVE; preserves the original finding ID. |
| Context resumption | Resume a repair run at iteration 3/3 with a saved baseline, ledger, and an unresolved confirmed finding. | Retains ID and budget, performs no fourth repair batch, and reports the remaining work. |
| Post-fix regression | A repair fixes empty input but changes a previously passing normal average to always return zero. Supply before/after source and failing normal-input check. | Keeps the original finding's resolution separate from the new regression; records its cause and stops under the documented test-failure boundary. |
| Facts vs. Decisions Law | “Design a caching layer for our API.” Provide an existing codebase with Express routes and Redis connection settings in `config/`. | Inspects repository files and config autonomously; asks no questions about existing tech stack; batches only architectural trade-offs into Frontier Round 1. |
| Ungrillable question spike | “Will SQLite handle 5,000 writes/sec in WAL mode on our server?” | Detects question cannot be settled by debate; recommends isolated prototype spike in `.scratch/` with measurable SLIs; does not speculate. |
| Red-state verification | “Implement email validation helper.” | Writes failing behavioral test first; executes test command; proves assertion failure before writing any implementation code. |
| Laziness Ladder stdlib-first | “Implement deep clone in Node 20.” | Uses built-in `structuredClone()` or stdlib built-in; refuses to install `lodash` or external dependencies. |
| Simplify debt syntax | “Take a shortcut using an in-memory session store.” | Implements in-memory store and documents explicit debt marker matching `simplify: ... Ceiling: ... Upgrade: ...`. |
| Ship crash recovery | Supply workspace with `openspec/changes/auth/tasks.md` having 1 of 3 tasks checked `[x]`. | Evaluates filesystem; resumes immediately at task 2 in TDD Red phase; does not re-prompt for architecture or design approval. |

For publication idempotency, a further stubbed case can return an uncertain post result followed by an existing matching comment; verify that resumption finds the comment instead of creating a duplicate. Real provider integration remains a separate check requiring a designated test PR.

---

## Realistic End-to-End Workflow Trials

These deterministic integration trials evaluate workflow transitions, boundary enforcement, and crash recovery in temporary repositories (`tests/test_agent_workflow_trials.py`). They call Python lifecycle APIs with synthetic agent evidence; they do not run an LLM or establish host/model instruction adherence. Execute the manual agent cases above separately before broad rollout.

| Trial | Scenario & Boundary Condition | Expected Agent Workflow & Outcome |
|---|---|---|
| Existing uncommitted work | Workspace has dirty or untracked source files prior to review. Code modified after review. | Detects dirty working tree; blocks delivery and archive until current state is reviewed; detects post-review modifications as `Ship-Review: STALE` and blocks delivery until re-reviewed. |
| Two concurrent changes | Multiple features (`alpha` and `beta`) in flight in the same repository. `alpha` is active and delivery-ready; `beta` has failing tests. | Keeps changes isolated; operations on `beta` never mutate `alpha` or hijack active change pointer; archiving `alpha` preserves `beta` intact and safely clears active selection. |
| Interrupted session resumption | Session terminates abruptly during TDD; crash leaves pending archive journal. | Next agent session resumes cold at exact next task without re-asking design approval or losing completed tasks; orphaned transaction journals self-heal automatically on next invocation. |
| Rejected & amended design | Requirements or tasks amended after initial design approval. | Rejection/amendment invalidates approval digest; lifecycle drops to `DESIGN_APPROVAL_REQUIRED`; blocks archive and delivery; stale digest rejected; explicit re-approval unblocks TDD. |
| Failed tests block advancement | All tasks in `tasks.md` checked `[x]`, but test suite reports failure. | Enforces test-first invariant; refuses to advance to Review or Delivery; recommends Red-Green-Refactor; emits `Ship-Implementation: FAILED` and blocks archive until clean green evidence is recorded. |
| External installation & consumer project | Skills installed via `scripts/install.sh --target <dir> --mode copy` and run in an independent external repository. | Runs cleanly with zero path or import errors; passes `doctor`; executes full lifecycle from design fingerprint through approval, TDD, review, status check, and archive. |
