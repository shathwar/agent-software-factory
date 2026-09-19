# Headless CI & Multi-Team Automation Guide

Commands below assume `SKILLS_DIR` is set to the absolute parent directory of the installed `ship` folder. Keep the working directory set to the consumer project.


A production guide for running the **Ship Lifecycle Engine** headlessly in CI/CD (GitHub Actions, GitLab CI) and decoupling agent execution from synchronous chat sessions.

---

## 1. The Headless Problem & Solution

In standard interactive sessions, `/ship` prompts the engineer for approval at **design (Specification Checkpoint)**. In enterprise teams with multiple squads, running long-running features inside a local IDE chat is inconvenient.

The headless workflow decouples the lifecycle gates into asynchronous CI steps:

```text
               1. Engineer files Issue: "/ship Add Stripe Webhook Idempotency"
                                      │
                                      ▼
                      GitHub Action triggers design gate
                                      │
                                      ▼
               2. Agent compiles ADR & OpenSpec Change Package
                  Posts Architecture Decision to Issue Comment
                                      │
                                      ▼
                   Tech Lead labels: "ship:approved"
                                      │
                                      ▼
                       GitHub Action triggers implementation & review gates
                   • TDD: Red-Green-Refactor tasks.md
                   • Simplify: stdlib-first anti-bloat
                   • Adversarial Review: Judge PASS review
                                       │
                                       ▼
                3. Action opens Pull Request with:
                   • Delivery Walkthrough Report
                   • Judge PASS Evidence Envelope
                   • Zero-regression terminal receipts
```

---

## 2. Architecture: Agent Runner vs. Lifecycle Inspector

> [!IMPORTANT]
> **Separation of Concerns**:
> - **The Agent Runner / Harness** (`agy run`, Claude Code CLI, Gemini CLI, or LLM agent worker) generates code, architectures ADRs, runs TDD cycles, and interacts with LLMs.
> - **The Lifecycle Inspector** (`inspect_lifecycle.py`) is an autonomous, zero-dependency state machine, gate assertion engine, and git ref recorder. It verifies that criteria for each gate are strictly satisfied before allowing transitions.

---

## 3. Configuration: `.agentflow.json`

Every repository or monorepo service can include a `.agentflow.json` at its root or service directory:

```json
{
  "$schema": "https://raw.githubusercontent.com/shathwar/skills/main/skills/ship/references/agentflow.schema.json",
  "version": 1,
  "project": {
    "name": "payment-gateway",
    "scope": "services/payment"
  },
  "gates": {
    "design": {
      "adr_dir": "docs/adr",
      "specs_dir": "openspec/specs"
    },
    "spike": {
      "timeout": 60.0,
      "concurrency": 1
    },
    "implementation": {
      "test": "pytest -q tests/unit",
      "typecheck": "mypy services/payment",
      "lint": "ruff check ."
    },
    "simplify": {
      "max_debt": 0,
      "strict": true
    },
    "review": {
      "base_branch": "main",
      "reviewers": ["correctness", "concurrency", "design", "judge"],
      "max_iterations": 3
    },
    "delivery": {
      "target_branch": "main",
      "clean_worktree": true,
      "sync_specs": true,
      "archive_packages": true
    }
  }
}
```

---

## 4. Turnkey CI/CD Templates & Integration Contract

To enable fast enterprise adoption, this repository includes turnkey, production-grade GitHub Actions workflows, issue forms, and safety hooks in `templates/ci/`:

```text
templates/ci/
├── github/
│   ├── ISSUE_TEMPLATE/
│   │   └── ship-story.yml          # Agent-parseable story specification form
│   └── workflows/
│       ├── ship-dev.yml            # Implementation agent with live checkbox telemetry
│       ├── ship-review.yml         # Read-only principal review agent (invariants & security)
│       └── ship-fix.yml            # Autonomous auto-fix loop with 5-iteration cap guardrail
└── safety/
    ├── block-destructive.sh        # PreToolUse destructive bash command blocker
    ├── pre-tool-branch-guard.sh    # PreToolUse main branch edit blocker
    └── settings.example.json       # Example configuration wiring safety hooks & deny rules
```

### The Autonomous Triad Pipeline

1. **`ship-dev.yml` (Implementation & Telemetry)**:
   - Triggers when an issue is assigned or labeled `ship:ready` (or `@ship` issue comment).
   - **Real-Time Checkbox Telemetry**: Actively mutates task checkboxes (`- [ ]` to `- [x]`) in the GitHub Issue body via `gh issue edit` as requirements pass, offering live execution visibility without checking console logs.
   - Enforces TDD Red-Green-Refactor cycles and verifies zero regressions.
   - Executes `python3 skills/ship/scripts/inspect_lifecycle.py --status-check` before opening a PR referencing `Closes #<N>`.
2. **`ship-review.yml` (Sandboxed Invariant Review)**:
   - Triggers on PR open, reopen, or synchronization.
   - Strictly sandboxed with read-only tools (`Read`, `Glob`, `Grep`, `git diff`, `git log`, `git show`). Code execution is prohibited.
   - Evaluates diffs against `ARCHITECTURAL_INVARIANTS.md`, correctness, security handbooks, and test coverage.
3. **`ship-fix.yml` (Feedback Loop with Iteration Cap)**:
   - Triggers strictly on Bot review feedback (`user.type == 'Bot'`), ignoring humans to prevent unintended feedback loops.
   - **Safety Iteration Limit (5/5)**: Inspects PR commits for headlines matching `[autofix N/5]`. If the iteration count reaches 5, the workflow posts an alert comment requiring human intervention and terminates cleanly, protecting token budgets.

### Enterprise Integration Contract

When integrating your organization's custom agent runner or CI infrastructure, adhere to the following contract:

1. **Persist the design result.** Create an issue-specific branch and commit the ADR
   and OpenSpec package. Publish its exact commit SHA. Persist the checkpoint receipt,
   checkpoint Git objects/private refs, and `.agentflow/state.json` in access-controlled
   storage. Ordinary branch pushes do not carry `refs/ship/*` or Git notes, and the
   local ledger is ignored by Git. Do not post “specification ready” until all required
   artifacts have been saved successfully.
2. **Bind approval to that result.** Record the issue ID, change ID, branch, design
   commit SHA, artifact/run ID, and approver identity. Verify the approver's current
   repository permissions through the hosting API. A label alone must not approve
   a later revision of the design or work from another issue.
3. **Restore before implementation.** Check out the approved SHA on the issue's branch,
   restore the matching ledger and checkpoint data, and verify that receipt commit
   objects exist. Reject missing or mismatched state. Pass `--change <change-id>` to
   lifecycle commands instead of relying on a fresh runner's active-change pointer.
4. **Run the configured harness.** Install the pinned skill release and run design,
   implementation, and review through your chosen agent runner. The inspector checks
   state; it does not execute those agent stages. Persist failed/interrupted runs so
   another runner can resume them without reconstructing approval from checkboxes.
5. **Serialize delivery.** Use per-repository/per-branch CI concurrency controls in
   addition to local ledger locking. Run `--status-check --change <change-id>`, archive
   the change, persist the updated ledger, commit the final files, and publish evidence
   with an explicit Git-notes fetch/merge/push policy. Validate the final delivery
   snapshot before opening the PR; avoid force-overwriting another runner's notes.

Use minimal job permissions, separate trusted approval handling from untrusted issue
text, and keep human PR review enabled during the pilot. Validate a full run across
**two separate runners**, including artifact loss, expired approval, an interrupted
implementation, and evidence-publication failure, before enabling autonomous delivery.

---

## 5. State Machine Automation Commands

| Command | Purpose in CI/CD |
|---|---|
| `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --status-check` | Exits `0` if ready for delivery, `1` if blocked, `2` if rollback required. Use in CI branch protection. |
| `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --checkpoint <gate>` | Records immutable internal git refs (`refs/ship/...`) and JSON receipts in `.agentflow/`. |
| `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --rollback design` | Safely archives untracked/modified edits to `.agentflow/backups/` and resets `tasks.md` for revision. |
| `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --archive <change>` | Syncs delta specs into `openspec/specs/` and archives completed change packages. |
| `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --generate-trailers` | Emits RFC 5133 Git commit trailers mapping to `.agentflow.json` gates. |
| `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --sync-state` | Re-synchronizes `.agentflow/state.json` authoritative ledger from workspace artifacts. |


## Recovery boundaries

Rollback restores a whole checkout snapshot. Use one active change per checkout and
separate Git worktrees for parallel changes. Rollback refuses a checkout containing
other active ledger changes or OpenSpec packages, including with `--force`.
A matching checkpoint receipt and valid snapshot/base commits are required. A
checkpoint recorded before the first Git commit cannot restore files.

Rollback copies affected files, including task progress, before restoring or deleting
anything. Backups live in `.agentflow/rollback_<timestamp>/`, with new files also under
`untracked_removed/`. Backup failures stop the operation. If a later Git operation
fails, the command reports failure and the backup location; inspect that backup and
Git status before retrying. The ledger is not advanced on a failed rollback.

A corrupt or unsupported `.agentflow/state.json` stops state operations and is left
unchanged. Restore a known-good copy. If none exists, explicitly move the damaged
file to a recovery location before running `--sync-state`, then reconcile manual
holds, test failures, and other records that workspace artifacts cannot reconstruct.
Do not automate that move or treat inferred state as restored approval evidence.

Evidence recording fails if its Git note cannot be saved; fix the Git write error
and retry before considering the ledger updated. Checkpoint snapshot failures also
return an error rather than substituting HEAD for uncommitted work.


### Archive restart recovery and path boundaries

Archive runs under the ledger lock and writes `.agentflow/archive-transaction.json`
before changing specs or moving the package. The journal holds an operation ID,
original spec bytes, the prior ledger bytes, destination paths, and progress markers.
Spec writes and ledger writes use atomic replacement; writes and directory updates
are flushed to disk. Archive requires source and destination on the same filesystem.

An `archive_operation_id` in the final ledger record is the commit decision. On the
next state operation or repository evaluation, an interrupted operation without that
marker is rolled back; a committed operation is verified and its journal removed.
Recovery can itself be interrupted and retried. Missing, corrupt, or contradictory
recovery data stops further operations and preserves the journal. Changes made outside
the interrupted transaction are not overwritten automatically. Keep the journal and
backups while reconciling such a failure; do not delete them merely to unblock a run.

Change IDs are identifiers such as `payments-v2`, never filesystem paths. Archive,
inspection, checkpoint, rollback, and active-change selection reject absolute paths,
separators, traversal, and unsafe managed symlinks. `--force` can bypass workflow
approval requirements but cannot bypass these filesystem boundaries. These checks
assume a trusted checkout; do not allow an untrusted local process to replace paths
while the runner operates.


## Optional CI enforcement

Local skill use does not require CI. Follow the [local workflow and approval receipts](./lifecycle_state_machine.md#local-workflow-and-design-approval) for normal interactive sessions. The following applies only when adding a protected CI merge gate.


These receipts record authorization; they do not authenticate the supplied identity.
The local checkout, ledger, Git notes, report JSON, and CLI are writable by the same
operator. They are workflow records, not tamper-proof attestations. Boolean or textual
legacy test reports remain accepted as self-reported evidence. Structured reports
are checked for contradictory exit codes, failure counts, flags, and nested results;
malformed results cannot count as passing. `--record-tests` does not execute tests.

For an enforced organizational gate, use the existing CI and review platform as the
trust authority. A protected job must authenticate the approval event, retain the
reviewed digest, and run required tests independently on the candidate commit. Let
that job generate the structured test summary (`passed`, integer `exit_code`, positive
integer `tests_run`, zero integer failure counts, and `command`) and retain its logs
with the commit SHA. Only the trusted job should publish the required merge check;
an agent-generated report or trailer must not substitute for it. Use trusted workflow
code and policy when evaluating a candidate that can itself modify scripts or config.
This repository supplies the local checks and receipt interface; the organization’s
runner must provide that identity and execution integration.
