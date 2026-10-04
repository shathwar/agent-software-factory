# Lifecycle State Machine & Transition Rules

Commands below assume `SKILLS_DIR` is set to the absolute parent directory of the installed `ship` folder. Keep the working directory set to the consumer project.


A formal specification of the 4-gate engineering lifecycle state machine, its transition guards, and crash-recovery protocols.

---

## 1. Formal State Machine

```text
               ┌───────────────────────┐
               │   INITIAL_PROPOSAL    │
               └───────────┬───────────┘
                           │ User enters /ship <idea>
                           ▼
               ┌───────────────────────┐
        ┌─────►│    FRONTIER_ROUNDS    │◄────┐
        │      └───────────┬───────────┘     │
        │                  │                 │
        │ (Ungrillable?)   │ (Frontier Empty)│ (Spike Verdict)
        ▼                  ▼                 │
┌───────────────┐  ┌───────────────────────┐ │
│ SPIKE_ACTIVE  │  │    SPEC_CONFIRMED     │ │
│    (spike)    ├──┴───────────────────────┴─┘
└───────────────┘  │ User clicks "Proceed"
                   ▼
       ┌───────────────────────┐
┌─────►│      TDD_ACTIVE       │
│      │    (tasks.md loop)    │
│      └───────────┬───────────┘
│                  │ All tasks [x] & Tests Pass
│                  ▼
│      ┌───────────────────────┐
│      │     REVIEW_ACTIVE     │
│      │       (review)        │
│      └───────┬───────┬───────┘
│              │       │
│  (Code Bug)  │       │ (Architectural Flaw)
└─── Fix Loop ─┘       └───────────────────────┐
               │                               │
                ▼ (Judge PASS)                  ▼
                    ┌───────────────────────┐       ┌───────────────────────┐
                    │    DELIVERY_READY     │       │    FRONTIER_ROUNDS    │
                    └───────────┬───────────┘       │   (Spec Amendment)    │
                                │ inspect_lifecycle --archive
                                ▼
                    ┌───────────────────────┐
                    │       ARCHIVED        │
                    │ (Living Specs Synced) │
                    └───────────────────────┘
```

---

## 2. States & Transition Guards

### State 1: `INITIAL_PROPOSAL` ➔ `FRONTIER_ROUNDS`
- **Trigger**: User invokes `/ship "<feature or plan>"`.
- **Preconditions**: Clean Git status or explicit target branch.
- **Guard**: Agent autonomously inspects existing repository files, schemas, and endpoints before asking any user question.
- **Output**: Round 1 of the Design Frontier (`❓ Q1` with `➡️ Recommended Stance`).

### State 2: `FRONTIER_ROUNDS` ➔ `SPIKE_ACTIVE` (Optional Branch)
- **Guard**: An architectural decision depends on an unmeasured empirical variable (e.g. third-party rate limits, lock contention, library compatibility).
- **Action**: Pause grilling on that branch. Scaffold a 15-30 minute spike under `.agentflow/spikes/<spike-name>/` using [spike](../../spike/SKILL.md).
- **Return Guard**: The spike report delivers a concrete verdict (latency, throughput, or behavior), settling the open question on the design tree.

### State 3: `FRONTIER_ROUNDS` ➔ `SPEC_CONFIRMED`
- **Guard**: The Design Frontier is completely empty (zero unstated assumptions, all architectural forks settled).
- **Artifacts Generated**:
  - `docs/adr/ADR-<NNNN>-<change>.md` ([ADR Template](../../design/references/adr_template.md))
  - `openspec/changes/<change>/proposal.md`, `specs/`, and `tasks.md` ([OpenSpec Template](../../design/references/openspec_template.md))
- **Confirmation Gate**: The agent presents the Executive Synthesis. The user must approve ("Proceed") before code is modified.

### State 4: `SPEC_CONFIRMED` ➔ `TDD_ACTIVE`
- **Guard**: User explicitly approves the specification.
- **Loop**: Sequentially iterate through every unchecked task in `openspec/changes/<change>/tasks.md`:
  1. **Red**: [Test Driver](../../tdd/agents/test_driver.md) writes failing behavioral test exercising `specs/`. Verify test fails.
  2. **Green**: [Simplify Implementer](../../tdd/agents/simplify_implementer.md) climbs the Laziness Ladder to write minimum code. Verify test passes.
  3. **Refactor**: [Code Refactorer](../../tdd/agents/code_refactorer.md) removes duplication and adds [debt markers](../../simplify/references/debt_tracking.md). Verify tests stay green.
  4. Mark task completed (`- [x]`).

### State 5: `TDD_ACTIVE` ➔ `REVIEW_ACTIVE`
- **Guard**: All checkboxes in `tasks.md` are marked `[x]`, and the entire test suite passes cleanly.
- **Action**: Invoke [review](../../review/SKILL.md) in `review-loop` mode.

### State 5b: `REVIEW_ACTIVE` ➔ `FRONTIER_ROUNDS` (Spec Amendment & Rollback Gate)
- **Guard**: Stage 0 (Spec Alignment) or the Judge discovers that an ADR invariant is fundamentally broken, impossible to satisfy within existing constraints, or requires an architectural trade-off that cannot be resolved with local code fixes.
- **Action**: Halt implementation and preserve the working tree. Formulate a new Frontier Round in [design](../../design/SKILL.md) to settle the revised architecture with the user. Update the ADR and OpenSpec package before resuming implementation. Whole-checkout restoration is an explicit operator recovery operation (`--rollback design --force`), never an automatic response to review findings.

### State 6: `REVIEW_ACTIVE` ➔ `DELIVERY_READY`
- **Guard**:
  - Stage 0 confirms 100% compliance with `openspec/` and ADR invariants.
  - Stages 1–9 identify zero Critical or High production defects.
  - Review Judge issues an official `PASS` verdict report (`reviewer == "judge"`).
  - Run `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --verify --tier execution --change <change>` after the final source edit. The receipt must be `VERIFIED` with positive executed-test counts and match the reviewed snapshot; then run `--status-check --change <change>`.
- **Output**: Delivery Walkthrough, summary scorecard, and clean commit recommendation.

### State 7: `DELIVERY_READY` ➔ `ARCHIVED` (OpenSpec Apply & Archive)
- **Guard**: Delivery Walkthrough completed and signed off; all automated test suites pass.
- **Action**: Run `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --archive <change>`.
- **Output**: Delta specs in `openspec/changes/<change>/specs/` merged/synced to living truth in `openspec/specs/`. Active package moved from `openspec/changes/<change>/` to `openspec/archive/<YYYY-MM-DD>-<change>/`. Lifecycle returns to clean state for next proposal.

---

## 3. Automated State Evaluation & Tri-Tier State Management

The Ship Engine employs a tri-tier architecture combining working-tree agility with permanent Git immutability:

1. **Tier 1: Explicit State Ledger (`.agentflow/state.json`)**:
   - Authoritative workflow state tracking `change_id`, active phase (Gates 1–4), `task_status`, active `blockers`, a monotonic `revision_counter`, references to validation evidence, and a full `turns` provenance log.
   - Reconstructs turn-level history: which skill ran, against what inputs, what evidence it produced, and how the result affected workflow state (`inspect_lifecycle.py --turns`).
   - Fully supports multi-agent and multi-change isolation: distinct changes are stored under `changes[change_id]`.
   - Thread- and crash-safe atomic updates (`NamedTemporaryFile` + `os.replace`).
   - Self-healing synchronization: if `.agentflow/state.json` is missing, `inspect_lifecycle.py` automatically reconstructs it from workspace artifacts.
   - Preserved across rollbacks and excluded from Git commits via `.git/info/exclude` / `.gitignore`.

2. **Tier 2: Git Notes (`refs/notes/ship-evidence`)**:
   - Retains deep validation evidence (full JSON review reports, test runner logs, benchmark metrics) directly attached to commit objects without polluting commit messages.

3. **Tier 3: Gate Commit Trailers**:
   - RFC 5133-compliant compact commit trailers automatically generated on delivery (`inspect_lifecycle.py --generate-trailers`):
     ```text
     Ship-Change: payment-stripe
     Ship-Design: ADR-0001 (ACCEPTED)
     Ship-Spike: PASSED
     Ship-Implementation: PASSED (5/5 tasks)
     Ship-Simplify: DEBT-0
     Ship-Review: PASS (by judge)
     Ship-Delivery: ARCHIVED
     ```
   - Dynamically mapped to gate names defined in `.agentflow.json`.

```bash
# Evaluate repository state and inspect active change ledger
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py"

# Switch active change for multi-agent workflows
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --set-active-change <change_id>

# Re-synchronize state ledger from workspace artifacts
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --sync-state

# Attach review or test evidence to ledger and git notes
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --record-review .agentflow/review_report.json
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --record-tests pass

# Generate commit trailers for delivery commit
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --generate-trailers --change <change_id>
```

---

## 4. Manual Resume Protocol (If running without tooling)
If an agent run is aborted, timed out, or restarted in a new session:

1. **Step 1: Check State Ledger & OpenSpec**:
   - Check `.agentflow/state.json` for active change ID and phase.
   - Inspect `openspec/changes/` for the active feature directory.
   - If not found or if changes are already archived under `openspec/archive/`, resume at `INITIAL_PROPOSAL`.
2. **Step 2: Inspect `tasks.md`**:
   - If `tasks.md` has unchecked tasks (`- [ ]`), find the first unchecked item and resume `TDD_ACTIVE`.
   - Run the test suite once before writing code to verify the baseline state.
3. **Step 3: Inspect Git Diff**:
   - If all tasks in `tasks.md` are checked `[x]`, inspect changes across the working tree against the base branch (`inspect_changes.sh --base main`).
   - If changes are unreviewed, resume at `REVIEW_ACTIVE`.
4. **Step 4: Inspect Review Report**:
   - If a report exists with Judge adjudication, `PASS` verdict, zero open Critical/High defects, and verified test evidence, resume at `DELIVERY_READY`.
5. **Step 5: Apply, Archive, and Commit with Trailers**:
   - Sync delta specs to `openspec/specs/`, archive change package to `openspec/archive/`, attach evidence to Git notes, and append `Ship-*` trailers to the delivery commit.


## Local workflow and design approval

Local interactive use is the default. No CI service, remote approval system, or
separate identity service is required. The agent runs the configured tests locally,
keeps the terminal output, records the results, and uses the ledger to resume work.
Git notes and trailers provide evidence alongside the code when Git is available.

A user’s explicit approval in the current conversation authorizes the agent to
record the design receipt for the package they reviewed. The agent handles the
digest and CLI commands; the user does not need to copy hashes or run commands.
Use an identity already provided by the session, or the descriptive label
`session-user` when no named identity is available. This label records conversational
authorization and does not claim verified identity. Do not ask for another approval
when the current design is already explicitly authorized. If approval predates
digest capture, record it only when the agent can establish that the design has not
changed since the user reviewed it.

### Design approval receipts

The inspector requires an explicit receipt before routing a change to implementation
or delivery. Existing changes with no receipt return `DESIGN_APPROVAL_REQUIRED`;
workspace sync does not infer approval from ADR status, completed tasks, or review
reports. Deleting the ledger loses the approval and requires it to be recorded again.

Before presenting a package for approval, capture its digest:

```bash
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --change CHANGE --design-fingerprint
```

After the user or authorized reviewer approves that exact package, record the
captured digest (do not recompute it to silently accept intervening changes):

```bash
python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --change CHANGE --approve-design REVIEWED_SHA256 --approved-by REVIEWER_ID
```

The receipt lives under `changes[CHANGE].evidence.design.approval` in the ledger.
It binds the change ID, approver, timestamp, and digest. The digest includes every
file in that change package and `docs/adr/`, including file names. Adding, removing,
or editing those files invalidates approval. All ADRs are included conservatively;
unrelated ADR edits also require reapproval. Task checkbox completion is normalized,
so ticking tasks does not invalidate approval; changing task wording does. Source
code changes do not alter the design digest and remain subject to review freshness.
Unsafe symlinks are rejected. The implementation currently uses the conventional
`openspec/changes/` and `docs/adr/` paths.

Inspection, ledger reconciliation, normal archive, and trailer generation use the
same approval rule. `--force` remains an explicit archive override, not proof that
gates passed. Use it only when the user explicitly authorizes bypassing those checks.


### Local test evidence

Run the project’s test command before recording its result. Prefer a structured
summary with `passed`, integer `exit_code`, positive integer `tests_run`, zero
integer failure counts, and `command`, backed by the actual terminal output.
`--record-tests` records the result; it does not execute tests. Local evidence checks
catch contradictions and stale results, but assume the user and agent operate in
a trusted checkout. Independently authenticated evidence is an optional CI concern,
not a prerequisite for local use. See the [headless CI guide](./headless_ci_guide.md)
only when setting up that integration.


### Archived receipts and configuration errors

After archive, pass `--change <change_id>` to `--generate-trailers`. The active
pointer is cleared on archive, and the command returns the saved trailer receipt
instead of revalidating files that have moved. Without an active change or explicit
ID, trailer generation fails visibly. Design approval preserves the active pointer.

An absent `.agentflow.json` uses defaults. An unreadable, malformed, non-object, or
incorrectly typed configuration raises an error; an explicit `--config` path must
exist. Fix the configuration before resuming workflow commands.
