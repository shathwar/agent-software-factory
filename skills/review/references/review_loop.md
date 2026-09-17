# Review and Fix Loop

The orchestrator runs this protocol using the host's agent tools; no shell script can dispatch reviewers portably. Load it for `review-loop`, selected through [the shared pipeline](./review_pipeline.md#invocation-mode). `review` and `review-pr` terminate after adjudication and reporting/publication without repairs. A review-only request uses discovery and adjudication once, updates the ledger, and reports without entering the repair loop.

## State

Keep one internal state record for the run. Initialise it before discovery:

```yaml
iteration: 1
max_iterations: 3
status: REVIEWING
baseline: "<starting HEAD plus staged, unstaged, and untracked snapshot>"
current_snapshot: "<snapshot being reviewed>"
findings: []
```

`iteration` counts review–adjudicate–fix–verify rounds, including failed fix attempts. Use `MAX_ITERATIONS = 3` by default; honour an explicit user limit. Do not reset the count when findings recur, agents restart, or context is compacted. Each round allows at most one Fixer handoff for the selected batch; a failed implementation requiring another repair consumes the next round. Verification and reporting still run after the final allowed repair.

Run status is one of `REVIEWING`, `JUDGING`, `FIXING`, `VERIFYING`, `COMPLETE`, `REVIEW_COMPLETE`, `HUMAN_DECISION`, `BLOCKED`, or `LIMIT_REACHED`. This is separate from a finding's lifecycle and from the reviewers' JSON `status` field.

Keep the record in orchestration context and checkpoint it with the baseline, scope, outcomes, and next action before any agent/context handoff that could lose state. If a file is needed, use a run-specific scratch path outside the reviewed repository and retain its location in the handoff. Never include the ledger in the target diff. On resume, reconcile the current source with the checkpoint; do not replay edits or create a fresh budget. If the baseline or ledger is lost, stop affected fixes rather than guessing prior state.

## Scope and validation setup

Before repairing, record the requested scope and concrete file list. At each round, reconcile it with renames, deletions, and files added by approved fixes. Keep the original comparison baseline; do not silently expand to the whole repository. Deleted code still needs impact review through its diff and callers.

Resolve build and test commands from applicable repository instructions, CI configuration, and package/task definitions. Check the working directory, package manager, and affected workspace; a marker file alone does not establish the correct command. Save each command, its scope, baseline outcome, and output location in the run record. Include focused regression checks and the repository-required final suite. If validation cannot be established, stop with the missing information rather than guessing PASS.

Reuse these commands after repairs. If configuration changes require a different command, record why and retain comparable evidence. Log exit status and relevant failure output, tied to the tested snapshot. Unexpected failures trigger the existing hard human boundary; there is no separate test-repair budget.

## Finding ledger

Store lifecycle metadata outside the unchanged 12-field finding object:

```yaml
id: FINDING-001
identity: "<logical file/symbol + violated invariant + root cause>"
state: OPEN
finding: "<12-field finding object>"
first_seen_iteration: 1
last_seen_iteration: 1
history:
  - iteration: 1
    from: null
    to: OPEN
    reason: "Candidate received; not yet adjudicated"
    snapshot: "<reviewed snapshot>"
    evidence: "<source locations or validation results>"
```

Reserve a unique run-wide ID when a candidate is first received. Keep a mapping from iteration, reviewer, and local candidate ID to this ID. Give that mapping to the Judge; it preserves existing IDs rather than renumbering each report. Match recurrences by root cause and violated invariant, not title or line number. Line shifts do not make a new finding; distinct root causes at one location remain distinct findings. Preserve source aliases and merge history when deduplicating, without leaving duplicate active entries.

Every transition records its reason, evidence, iteration, and source snapshot. Missing evidence is never a successful transition.

| From | To | Required evidence / decision |
|---|---|---|
| New candidate | OPEN | Candidate received within review scope |
| OPEN | CONFIRMED | Judge independently validates the defect; fixability is `autonomous` |
| OPEN | REJECTED | Judge disproves or excludes the claim under the finding contract |
| OPEN | HUMAN_DECISION | Judge validates the defect but resolution is `requires-human` |
| CONFIRMED | FIXED | Fixer reports `fixed` after all Fix Safety Gate checks pass |
| FIXED | VERIFIED | Post-fix review and Judge validation establish resolution on the final snapshot; required tests pass |
| FIXED | CONFIRMED | Post-fix evidence shows the approved defect remains or the proposed fix is unacceptable |
| CONFIRMED | HUMAN_DECISION | Judge identifies a required business/architecture choice before further editing |
| HUMAN_DECISION | CONFIRMED | User supplies the decision; Judge approves an updated autonomous finding |
| VERIFIED or REJECTED | OPEN | Judge accepts materially new evidence or a source change that warrants reconsideration; retain the same ID and history |

Uncertain candidates remain OPEN with the unresolved question recorded. A failed Fixer attempt leaves a finding CONFIRMED, not REJECTED: rejecting a patch does not disprove the defect. Unavailable post-fix verification leaves it FIXED but unverified. A new regression caused by a fix gets its own OPEN entry; it cannot go directly to the Fixer.

### Frozen Classification & Fold Outcomes

In repair passes, finding classifications are **strictly frozen**:
- **Zero Severity Downgrades**: Neither the Fixer nor the orchestrator may downgrade `CRITICAL` or `HIGH` to `LOW`, reclassify an in-scope finding as "known issue", or dismiss it as "acceptable risk."
- **Zero Silent Drops**: Confirmed findings must be resolved or explicitly disputed; they cannot be omitted from subsequent reports.

Every confirmed finding processed in a repair round must produce one of four strictly evidenced outcomes:

1. **`FOLDED <commit_sha>`**:
   - The root cause is repaired in code under green test protection.
   - The test suite runs and passes.
   - An atomic commit is recorded and its commit SHA is pasted into the repair report.
2. **`DISPUTED <reason>`**:
   - Concrete code-level counter-evidence is provided proving the finding is an invalid defect or an intentional tradeoff.
   - Escalates immediately to the human user for adjudication (`HUMAN_DECISION`).
3. **`BLOCKED <missing_input>`**:
   - The fix cannot proceed due to an external limitation (e.g. missing credentials, network access, or environmental dependency).
4. **`REPLAN <phase>`**:
   - The defect reveals an architectural gap too large for an inline repair (> 150 lines or requiring schema/contract refactoring).
   - Routes to design/planning for a dedicated implementation phase rather than a hasty patch.

## Round execution

1. **REVIEWING:** In round one, run the selected review passes on the requested change. In later rounds, carry forward the validated post-fix reports and inspect only changed evidence or affected scope. Keep independent discovery passes free of other reviewers' initial conclusions.
2. **JUDGING:** The Judge adjudicates candidates and updates lifecycle decisions using the ID mapping. It does not discover defects. Repeated rejected claims without new evidence remain rejected. Apply `fixability` before selecting any fix.
3. **FIXING:** If fixing is authorised, hand only CONFIRMED findings to the Fixer with their approved objects and implementation context. Keep raw reports, rejected claims, and deliberations out of this handoff. If any hard human-boundary condition below occurs, stop the entire repair run immediately, including independent fixes. Surface HUMAN_DECISION items without editing. Map the Fixer's `fixed` result to FIXED, not VERIFIED.
4. **VERIFYING:** After any code edits, test and inspect the final combined patch against the starting snapshot, preserving pre-existing work. Ask the relevant specialists to verify claimed resolutions and inspect the fix diff plus affected callers for regressions. Supply approved findings and test evidence, but do not treat Fixer conclusions as proof. Reuse existing roles; the Fixer cannot independently verify itself. With no delegation, the orchestrator makes a separate source-inspection pass and records that limitation internally.
5. **Judge verification:** The Judge independently checks submitted resolution evidence and any regression candidates. Record per-ID outcomes in the existing `coverage` array; new or unresolved defect candidates still use the shared `findings` array. Tests passing alone, a clean specialist report without targeted verification, or a no-change diff cannot establish VERIFIED. Recheck previously verified findings only if later edits could invalidate them; unrelated findings retain verification against the unchanged code.
6. **Stop or advance:** Evaluate termination below. If another justified repair is possible and budget remains, increment `iteration` once and continue. Never bypass the cap with private Fixer retry loops, new agent tasks, or fresh IDs.

## New findings after a fix

Post-fix review has two obligations: verify previous repairs and search the changed patch for additional defects within the authorised scope. Re-evaluate applicable mode signals on the fix diff and affected callers; a concurrency repair can introduce design complexity, contract changes, or another failure path. Select the necessary existing specialists even if they did not report an original finding. Keep their discovery independent and their role boundaries unchanged.

The Judge compares every submitted candidate with the full ledger:

- Same root cause and invariant: retain the original ID; record persistence or evidence-backed reopening according to the lifecycle rules.
- Different root cause or invariant: reserve a new run-wide ID and OPEN entry, even in the same file or patch. Adjudicate it independently to CONFIRMED, HUMAN_DECISION, or REJECTED; uncertain evidence stays OPEN.
- Previously unreported defect exposed by the fix: record the causal link to the changed behavior. Do not include unrelated old defects outside the agreed scope.

Absence from a fresh findings list does not prove an original defect is gone; resolution requires targeted source and test evidence. Likewise, verifying every original finding does not prove the resulting patch is clean. The Judge performs this reconciliation on submitted reports, not a new discovery review of its own.

Example using the shared run-wide ID format:

```text
Before fix:
  FINDING-001 (Concurrency) → FIXED

Fresh review and Judge adjudication:
  FINDING-001 → VERIFIED (race resolved, supported by evidence)
  FINDING-002 (Design) → OPEN → CONFIRMED (new harmful complexity)

Run outcome:
  Not COMPLETE. Repair FINDING-002 in the next allowed round,
  or report the relevant blocker / iteration limit.
```

Keep the resolved entry and its history; do not overwrite it with the new defect. Send only newly confirmed autonomous findings, or confirmed unresolved findings, to the next Fixer handoff. New IDs never reset the iteration budget. Any unadjudicated new candidate prevents COMPLETE; apply the convergence gates below to all confirmed findings, including newly discovered ones.

## Attribute regressions to fixes

Before each repair batch, retain the immediate pre-fix snapshot and record relevant build/test results alongside the original run baseline. A newly discovered issue is not automatically a regression. Ask specialists to establish the before/after causal link, then have the Judge independently inspect it:

- Which fix changed the previously valid behavior or guarantee?
- Which hunk, input, or interleaving demonstrates the change?
- Does the same check fail after the fix and pass before it, or does source evidence establish the new failure path? Record test limitations honestly.

For a confirmed regression, add ledger metadata `introduced_by_iteration`, `introduced_by_findings` (IDs of the fixes responsible), and `regression_evidence` (pre/post snapshots, locations, and test results). These are ledger fields, not new fields in the shared finding schema. Keep the new defect's own stable ID. An unchanged old defect is an unresolved finding; a distinct defect created by a fix is a regression. If causality is uncertain, keep the candidate OPEN rather than calling it either safe or confirmed.

Example: a fix removes a lock to address a concurrency failure. A fresh reviewer demonstrates that two writers can now update shared state without synchronisation. The Judge records the data race as a new regression linked to the lock-removal fix, even if the original failure disappeared. It blocks approval regardless of its severity. Do not erase the historical regression record if a later repair resolves it.

## Hard human boundary

Stop all further repair activity immediately when any of these occurs:

- A business requirement is unclear.
- An architectural decision is required.
- A second attempted fix for the same root cause fails, or fixes begin undoing one another.
- Tests fail unexpectedly (new failure, changed failure signature, or previously passing coverage becomes red). A pre-fix reproducer deliberately demonstrating the approved defect is expected; do not confuse it with an unexpected failure.
- A fix requires unrelated refactoring or exceeds the authorised scope.
- Multiple valid approaches have materially different behavior or architectural tradeoffs that existing requirements do not resolve. Routine equivalent implementation choices remain autonomous.

Set run status to HUMAN_DECISION. Do not start another batch, silently retry tests until green, pick a business outcome, or continue unrelated fixes to consume remaining rounds. Retain completed results and the current patch; report any unaccepted edits. Read-only inspection needed to explain the stop is allowed. Do not automatically roll back user work or claim nothing changed when earlier repairs remain.

Return the following with concrete, supported options. If options cannot yet be established, identify the missing decision or evidence instead of inventing alternatives:

```text
HUMAN DECISION REQUIRED

Issue:
<finding IDs or validation failure>

Why the agent stopped:
<specific uncertainty, conflict, repeated failure, or scope boundary>

Options:
1. <approach and consequence>
2. <alternative and consequence>

Iterations: 2/3
```

This whole-run boundary overrides earlier guidance to continue independent fixes. The Fixer's per-finding no-edit rule still applies to `requires-human`. Resuming requires the user's decision and an updated approved handoff where needed; it does not reset iteration count or increase the limit.

## Convergence and termination

Approve only if all of the following are evidenced on the final combined patch:

```text
Remaining P0 = 0
Remaining P1 = 0
Build = PASS
Tests = PASS
Unresolved regression = 0
Unexplained changes = 0
```

Additionally, no OPEN candidates, unverified fixes, required coverage gaps, or human decisions may remain. The Judge must explain every patch change against an approved finding or preserved pre-existing work. For projects without a conventional build, identify the applicable validation command before editing (for example, syntax/type checks); record its actual result as the build-equivalent check. Missing, skipped, or unavailable validation is not PASS. Do not invent a test count.

A remaining P2 (or P3) may be retained only when the Judge records `optional: true` and `optional_reason` in the ledger, citing why it does not compromise required behavior, safety, or the change's acceptance criteria. Keep its severity and CONFIRMED state, list it in the final report, and do not count it as fixed or rejected. Severity alone never establishes optionality; do not downgrade a defect to force approval. An introduced regression cannot be waived as optional. Thus VERIFIED means repaired and checked; optional means disclosed and not required for approval.

- **COMPLETE / APPROVE:** All convergence gates pass; every accepted finding is VERIFIED or explicitly optional under the rule above. No minimum number of rounds is required.
- **REVIEW_COMPLETE:** Review-only adjudication and coverage have finished. Use the existing review-only report; this does not imply a clean verdict or authorise fixing.
- **HUMAN_DECISION:** A hard boundary occurs. Stop immediately and return the decision request, even if some other work could proceed.
- **BLOCKED:** Evidence or validation is unavailable, or progress stalls without a viable corrective approach. End the run with HUMAN DECISION REQUIRED, stating the actual blocker.
- **LIMIT_REACHED:** After final-round verification, required repairs remain at the iteration cap. End with HUMAN DECISION REQUIRED; do not run a fourth repair or claim convergence.

Hard boundaries take precedence over approval and further rounds. Otherwise evaluate the gates before considering another round. Preserve the ledger for an explicit continuation. No automatic commits, pushes, or deployments are added.

## Phase 5 report

For fix-loop runs, present this summary followed by the existing stage scorecard and any unresolved finding details or decision request. Review-only reports remain unchanged. Iteration count is now user-visible; agent identities and internal deliberations remain hidden.

```text
## Autonomous Review

Iterations: 2/3

Initial:
  P0: 0
  P1: 3
  P2: 2

Fixed:
  P1: 3
  P2: 1

Rejected:
  P2: 1

New issues introduced:
  Total confirmed regressions: 0
  Unresolved: 0

Remaining optional:
  None

Verification:
  Build: PASS — <command>
  Tests: 127 passed — <command>
  Regression check: PASS
  Diff check: PASS — no unexplained changes

Final verdict:
APPROVE
```

Populate counts from unique ledger IDs, not report occurrences. Initial counts are the deduplicated initial candidates before adjudication; preserve their original severity for these counts. Fixed counts include only VERIFIED entries, not the Fixer's unverified claims. Rejected counts include only REJECTED findings, not failed patches or optional items. For fixed/rejected groups use their adjudicated severity and explain any reclassification that affects reconciliation. Include P3 when present. Separately identify newly discovered findings that are not confirmed regressions. Report introduced regressions cumulatively, including those repaired, with unresolved counts separately; never hide an introduced defect behind a final zero.

If any gate fails or work cannot converge, use `Final verdict: HUMAN DECISION REQUIRED`, report the actual build/test results and remaining IDs, and include the decision request above. The sample numbers illustrate formatting only. Do not claim that a historical test pass verifies a later changed patch.
