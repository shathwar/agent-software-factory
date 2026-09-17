# Review Pipeline

## Invocation mode

Select one action mode before discovery. Default to `review` (Review Only). Select `review-pr` when the user explicitly requests posting a PR comment, and select `review-loop` when the user explicitly requests reviewing and fixing code. Do not block or ask conversational questionnaire questions when the user simply asks for a review. Preserve an existing selection in this conversation. A PR URL or “review this PR” alone does not authorise posting.

| Mode | Action | Termination |
|---|---|---|
| `review` | Review Only | Return the report; no source edits or PR comments |
| `review-pr` | Review + PR Comment | Publish the judged report; no branch modifications |
| `review-loop` | Review + Fix Loop | Fix approved findings, test, re-review, and return the loop report |

Selecting `review-pr` explicitly authorises posting to the identified PR; no redundant publication confirmation is needed. Resolve a missing or ambiguous PR target before posting. Selecting `review-loop` authorises scoped working-tree repairs, not commits, pushes, or PR comments. Do not silently combine modes or switch actions; honour an explicit subsequent mode change.

Record the action mode separately from the technical review scope in `review_modes.md` (standard, async, migration, etc.). Action mode controls side effects and termination; technical scope controls checks.

## Shared execution

All three actions use the same discovery, routing, review, and Judge steps:

```text
Select action → Inspect changes → Route checks → Review → Judge
    ├─ review      → Return report
    ├─ review-pr   → Publish PR comment → Return comment link
    └─ review-loop → Fix → Test / diff check → Re-review / Judge
                      ↑                           │
                      └── bounded next round ─────┘
                   → Return loop report
```

1. **Change & Context Discovery**: First distinguish a change review from a full repository review. For a change review, run the [inspector](../scripts/inspect_changes.sh) by its resolved path from the target repository. Treat its output as hints, not authoritative coverage. Pin the base and reviewed snapshot first; verify the chosen Git refs resolve and inspect the actual diff. A failed diff command is an error, not an empty review. For working changes, include staged, unstaged, and relevant untracked files. If a change review has no change in its requested scope, report that rather than launching reviewers. For a full repository review, inventory the requested tree (for example, `git ls-files` plus relevant untracked files), record the snapshot and scope, and inspect existing implementations and callers even when the working diff is empty. The inspector describes changes, not full repository review coverage. Local reviews do not need a remote or PR. Identify:
   - **Spec Sources**: Linked issue numbers from commits (`#123`, `PROJ-456`), PRD/spec files under `docs/`, `specs/`, `.scratch/`, or user-supplied specs.
   - **Standards Sources**: Applicable root and path-scoped instructions (`AGENTS.md`, `CLAUDE.md`), conventions (`CODING_STANDARDS.md`, `CONTRIBUTING.md`, linter configs), and existing domain docs or ADRs. Read only documents relevant to the changed area. The repo's documented standards always override baseline heuristics; linters enforce syntax, the reviewer enforces logic and clean-code smells.
   - **Scope & Triggers**: Modified files, diff stats, test mappings, and review mode triggers.
2. **Targeted Mode Selection**: Consult [`review_modes.md`](./review_modes.md) to activate stages based on change signals before assigning work.
3. **Execution Strategy Selection**:
   - **Single Reviewer (Default, ≤400 diff lines)**: Evaluate the active stages directly, including Stage 0 when a spec exists.
   - **Multi-Perspective Mode (>400 diff lines or explicit parallel request)**: Follow the specialist protocol in `review_modes.md`. Dispatch [Correctness](../agents/correctness_reviewer.md), [Concurrency](../agents/concurrency_reviewer.md), and [Design](../agents/design_reviewer.md) as selected by the active mode. Execution does not depend on recursive subagents: when subagents are available, specialists run concurrently as an optional optimization; in single-agent harnesses (Claude Code, Cursor, OpenCode, CI/CD), execute the active perspectives sequentially with separate candidate findings, followed by Judge adjudication. Both modes enforce identical 12-field finding contracts and Judge validation. The Principal Orchestrator owns Stage 0 and retained checks. Collect candidates for the shared Judge step below.
4. **Deep Inspection & The Facts vs. Decisions Rule**: Read affected implementations and trace necessary callers and consumers. Finding facts is the reviewer's job, never the author's: exhaustively inspect code, caller symbols, configs, and history before treating an unknown as an author question. Reserve questions for the author strictly for intentional architectural tradeoffs, missing product specs, or unresolvable business intent. In diff reviews, establish how the change introduces, exposes, or worsens each reported issue; do not sweep unrelated old defects into the report. A requested full repository review may include existing defects within its agreed scope. Consult focused `git log` or `git blame` when the reason for touched code is unclear, not as a mandatory repository-wide pass. A standards finding must identify the applicable rule and source location; a smell remains a judgment call.
5. **Contract Adherence**: Format every identified issue using the strict 12-field schema defined in [`finding_schema.md`](./finding_schema.md).
6. **Judge and terminate by action mode**: Apply the same [Judge](../agents/review_judge.md) rules to single-reviewer and specialist candidates. With one reviewer, perform a separate adjudication pass, including independent source inspection. The Judge validates submitted claims and does not discover new problems. Render only adjudicated findings. When findings have `fixability: requires-human` or fundamental architectural trade-offs require author input, present them using the **Frontier Clarification Protocol** (`❓ Q1` + `➡️ Recommended Stance`) in the report or decision turn. `review` returns the report; `review-pr` follows publication below; `review-loop` enters the existing fix protocol. A clean review still produces a report.

## PR comment publication (`review-pr`)

Apply the shared [human-facing writing rules](../SKILL.md#write-for-humans) to the comment before posting. Keep it plain, respectful, and easy to act on, with the evidence and required report fields intact.

Review the identified PR's actual base/head comparison; record the repository, PR number, and base/head SHAs. Exclude unrelated local changes. Use read-only Git/provider access or an isolated checkout, preserving the developer's branch, index, and working tree. Do not invoke the Fixer, commit, push, merge, or submit an approve/request-changes review. Post one consolidated comment using the review-only report format, identifying the reviewed commit and validation limitations.

Before posting, recheck the base/head SHAs. If either changed, refresh affected review evidence and Judge adjudication before publication. Use the available provider API or CLI to post the prepared report. With `gh`, write the body to a scratch file outside the target repository and use `--body-file` to preserve formatting.

Record the returned comment ID/URL and snapshot. On a resumed or uncertain publication attempt, check whether this run's comment already exists before retrying; do not blindly duplicate it or overwrite someone else's comment. If access or publication is unavailable, return the prepared report and blocker without claiming it was posted. On success, return the comment link and concise verdict. Human-required findings belong in the comment and do not trigger repairs.

---

## Fix handoff (`review-loop`)

In `review-loop`, the orchestrator owns the state, stable finding IDs, three-round default, and lifecycle transitions defined in [review_loop.md](./review_loop.md). Complete its [scope and validation setup](./review_loop.md#scope-and-validation-setup) before the first repair.

When the user requests fixes, follow [code_fixer.md](../agents/code_fixer.md) after Judge adjudication. Pass only Judge-approved findings within the authorised scope, with final IDs and implementation context. Exclude raw reports, rejected/deferred candidates, and review deliberations. Preserve `fixability` in the handoff: only `autonomous` findings permit edits; `requires-human` findings return a human decision request with no code changed for that finding. The Fixer implements accepted decisions; it does not resolve reviewer disagreements. Review-only requests still end with the existing report.

---

## Fix acceptance

The Fixer applies its per-finding workflow, pre/post diff inspection, and four-part safety gate before reporting its implementation as `fixed`. This moves a ledger entry to FIXED; only subsequent source-based verification under `review_loop.md` moves it to VERIFIED. Consult [code_fixer.md](../agents/code_fixer.md) for the implementation rules. Preserve human-decision requests and report validation limits; never treat an accepted finding as proof that its fix is safe.

Phase 5 fix-loop runs apply [regression attribution, hard human boundaries, and convergence gates](./review_loop.md#attribute-regressions-to-fixes) before issuing APPROVE. Any unexpected test failure or required business/architecture decision stops all repairs; this overrides independent continuation. Use the Phase 5 summary for these runs.
