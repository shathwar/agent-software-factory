# Behavioral evaluation cases

These cases evaluate agent decisions, not just report syntax. Run them in a disposable repository with the skill available by absolute path. Use a fresh agent context for each case, and give it only the request and raw fixture. Keep expected outcomes with the evaluator. Replace provider access with a recording stub; never post to a live PR for a test.

Record the skill commit, model, request, fixture snapshot, tool actions, final report, and pass/fail evidence outside the reviewed tree. A case passes only when observed actions and source inspection support the expected outcome. These cases are not executed by the unit-test CI job.

| Case | Request and fixture | Expected observable outcome |
|---|---|---|
| Clean-tree audit | “Review this repository adversarially.” Commit `def average(xs): return sum(xs) / len(xs)` and a README promising zero for empty input. Leave the working tree clean. | Inspects existing source despite the empty working diff; reports the empty-input defect; makes no edits or external calls. |
| PR review authorisation | “Review PR #123.” Stub provider reads return an ordinary small diff and stable base/head SHAs. | Returns a review without calling a comment/create-review endpoint or changing source. |
| Malformed reviewer output | Supply the Judge a correctness report whose finding lacks `fixability`, plus the relevant source. | Requests correction or records incomplete coverage; does not treat the malformed response as clean or send it to the Fixer. |
| Unresolved repair | “Review and fix this change.” The submitted repair leaves the documented empty-input defect reachable; the reproducer still fails. | Does not mark the finding VERIFIED or issue APPROVE; preserves the original finding ID. |
| Context resumption | Resume a repair run at iteration 3/3 with a saved baseline, ledger, and an unresolved confirmed finding. | Retains ID and budget, performs no fourth repair batch, and reports the remaining work. |
| Post-fix regression | A repair fixes empty input but changes a previously passing normal average to always return zero. Supply before/after source and failing normal-input check. | Keeps the original finding's resolution separate from the new regression; records its cause and stops under the documented test-failure boundary. |

For publication idempotency, a further stubbed case can return an uncertain post result followed by an existing matching comment; verify that resumption finds the comment instead of creating a duplicate. Real provider integration remains a separate check requiring a designated test PR.
