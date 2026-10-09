# Headless CI integration

The package-layout and archive instructions in this document describe `sdd.provider: legacy`.
For external SDD skills, use [SDD integration](./sdd.md); Ship retains its approval,
test, review, and delivery gates, while the provider owns its artifacts. Existing
CI templates must be adapted and validated before use with an external provider.


These are pilot templates for an explicitly approved design, not an issue-to-production
service. Local approval receipts do not authenticate people or sandbox agents. Keep
human PR review and the repository's protected merge checks.

## Configure the templates

1. Copy `templates/ci/github/workflows/ship-dev.yml` and, optionally, `ship-fix.yml`
   into the consumer repository's `.github/workflows/` directory. Keep these workflow
   files on the protected default branch. `ship-review.yml` remains a separate review
   example; validate its host permissions before enabling it.
2. Set repository variable `SHIP_SKILLS_SHA` to a reviewed **full commit SHA** of this
   skills repository containing `scripts/verify/ci_gate.py`. Missing or non-SHA values stop
   the workflow. The tools are checked out separately under `.agentflow/toolchain`.
3. Configure the `ship-approved` GitHub environment with required reviewers and
   protected deployment branches. Configure the chosen agent provider secret. Review
   action versions and pin them according to your organization's supply-chain policy.
4. Configure `.agentflow.json` in the consumer repository, including
   `gates.implementation.test`, to run its real full test suite. Supply dependencies
   and services through the consumer's normal CI setup; the template only sets up
   Python for the lifecycle tools. Run project commands with your host's sandbox and
   credential restrictions. Tool allowlists are not an OS sandbox.

## Approve an exact design

Prepare and review the ADR and `openspec/changes/<change>/` package first. Commit the
reviewed package on a branch and obtain its full SHA. From that exact checkout, get
its digest with the installed inspector:

```bash
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --design-fingerprint --change <change>
```

Dispatch **Ship Dev Agent** with the issue number, change ID, full design commit SHA,
and the reviewed digest. The workflow checks the initiating operator's current write,
maintain, or admin permission through GitHub's API. The environment reviewer must
verify these inputs before allowing the job. A label, issue assignment, issue body,
or bot comment is never approval. Requirements changed after approval need a new
review and dispatch; task checkbox completion alone does not change the design digest.

## Execution and publication

The workflow checks out the approved commit and pinned toolchain, then calls
`scripts/verify/ci_gate.py prepare` **before** starting the agent. This independently checks
the supplied digest, creates the checkpoint, and records approval for that design.
Missing or mismatched design artifacts stop execution. The runner gets one selected
change and bounded turns; it leaves the reviewed change package active.

After the agent finishes, the workflow restores the pinned toolchain and calls
`scripts/verify/ci_gate.py delivery` as a normal workflow step. It rechecks the original
digest, executes the configured test command, requires a `VERIFIED` execution receipt
with positive test counts, and checks full lifecycle readiness, including Judge PASS.
No script-exists condition or agent decision can skip this step. An absent toolchain,
no-op command, stale review, failed test, or changed design prevents publication.

Only the next workflow step commits, pushes a fresh branch, and opens a **draft** PR.
Git credentials are not persisted in the checkout during agent execution. The PR
records the design SHA/digest and sponsor; its evidence describes the snapshot checked
before the publishing commit. The template does not archive the package or merge the PR.
Keep normal independent tests on the final PR commit as protected merge checks.

**Ship Repair Proposal** delegates to exactly the same workflow and gates. It is
manually dispatched against a reviewed repair package and creates a new draft PR.
Automatic bot-triggered edits/pushes and the commit-message-based five-iteration loop
have been removed; there is no implicit authorization or recurring feedback loop.

Evidence artifacts are retained on success or failure. They are diagnostic records,
not a complete resumable checkout: they do not include Git checkpoint objects or
unpublished source edits. Use a persistent isolated worktree or an organization-owned
artifact mechanism when interruption recovery is required. Validate two-runner recovery,
permission failures, artifact loss, and publication failures before enabling that use.

## Local delivery and recovery

Commands run from the consumer project; `SKILLS_DIR` is the absolute installed parent
of `ship`. Copy-only installations support the same verification prerequisite:

```bash
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --verify --tier execution --change <change>
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --status-check --change <change>
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --archive <change>
```

Stop after any failing command. Source changes after verification require fresh test
and review evidence. See [supported runners](./team_rollout.md#verification-and-host-permissions).

## Recovery boundaries

A broken architectural invariant returns the agent to design **without changing the
working tree**. Rollback is a separate, whole-checkout restoration operation; it cannot
infer which post-checkpoint edits belong to the agent. The CLI and MCP refuse it by
default. Inspect the checkpoint diff, untracked files, and any HEAD movement; preserve
unrelated user work before authorizing `--rollback design --force --change <change>`
(or MCP `force: true`). Agents must not add this flag merely to unblock themselves.

Use one active change per checkout and separate worktrees for parallel changes.
Even with `--force`, competing active changes, missing checkpoint commits, or a
mismatched receipt stop restoration. A checkpoint made before the first commit cannot
restore files. Backups are written under `.agentflow/backups/rollback_<timestamp>/`
before restoration. Backup failures stop the operation. A later Git failure reports
the backup location and leaves the ledger unadvanced; inspect the working tree before
retrying. Backup availability is not permission to remove unrelated edits.

A corrupt or unsupported ledger stops operations and is preserved. Restore a known-good
copy or explicitly reconcile it; never infer approval from completed task checkboxes.

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
