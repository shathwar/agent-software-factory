---
name: ship
description: Coordinate specification-driven delivery through a configured external SDD skill, test-first implementation, simplification, engineering review, and evidence-backed handoff. Use for "/ship", "/lifecycle", "full engineering lifecycle", or "build and review this feature".
---

# Ship

Ship owns delivery gates. A configured external specification-driven development
(SDD) skill owns specifications, task representation, spec verification, and
finalization. Do not impose a provider's directories, filenames, or archive format.

Resolve `SKILLS_DIR` to the absolute directory containing this installed `ship`
folder. Run project commands from the consumer project.

## Start or resume

1. On first use or upgrade, run `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --doctor`
   with Python 3.10+. Doctor installs the pinned default OpenSpec dependency when
   it is absent and initializes a new project with `sdd.provider: openspec`.
   Resolve failed checks before claiming preflight success. Existing explicit SDD
   configuration remains authoritative.
2. Read `.agentflow.json` and [SDD integration](./references/sdd.md). For new
   integrations configure `sdd.provider` and the external skill operations. Read
   only the selected provider's instructions. Missing skills block their operation;
   do not silently replace them with locally invented specification templates.
3. Refresh the handoff using the configured `inspect` skill before inspecting
   lifecycle state. Run `ship turn --change <id>`, `ship_next_turn`, or
   `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --next-turn --change <id>`.
   Select the intended change explicitly when more than one is active.
4. Resume the required gate. Finished work remains valid only while its scope and
   evidence remain current. Apply the configured [team profile](./references/team_rollout.md#team-profiles).

## Prepare and approve

- Invoke the configured `prepare` skill. Use [`design`](../design/SKILL.md) for
  unresolved architectural decisions and [`spike`](../spike/SKILL.md) for empirical
  uncertainty. Feed decisions back to the SDD skill; create a separate ADR only
  when repository conventions require one.
- Refresh the provider handoff, including all specification/design artifacts and
  task scope. Compute the design digest and record `--checkpoint design`.
- Present the actual specification and tasks for explicit approval before
  implementation. Record existing authorization without asking again:
  `--approve-design <digest> --approved-by <identity> --change <id>`.
  A checkpoint alone is not approval. Changed scope requires renewed approval.
- Once approved, record it and begin the first pending task in the same turn.

## Implement

- Take pending tasks from the provider's handoff. Execute [`tdd`](../tdd/SKILL.md)
  and [`simplify`](../simplify/SKILL.md): demonstrate a failing behavioral test,
  implement the minimum change, then refactor under passing tests.
- Use repository test commands, including `gates.implementation.test` when set.
  Capture command, raw result, exit code, executed-test count, and duration.
- Update task progress through the provider's workflow and refresh its handoff.
  Ship must not edit provider task files or invent a second task representation.
- Record test evidence, turn provenance, and the implementation checkpoint.

## Verify and review

- Invoke the configured `verify` skill to check implementation against the approved
  specification. Retain its findings/report and bind the result to the current
  design and working-tree fingerprints in the handoff.
- Run [`review`](../review/SKILL.md) in `review-loop` mode against the full working
  tree, including staged, unstaged, and untracked changes. Provider spec verification
  feeds Stage 0; engineering review adds correctness and applicable risk checks.
- Fix adjudicated defects within the configured repair limit. Broken design
  invariants return to preparation while preserving existing edits.
- Require Judge PASS, zero open CRITICAL/HIGH defects, and current evidence.
  Disclose sequential or parallel execution honestly; subagents are optional.

## Deliver

1. After the last source edit, run `--verify --tier execution --change <id>` and
   `--status-check --change <id>` using the installed inspector. Require VERIFIED,
   positive executed-test counts, and a ready status. Missing, failed, or stale
   evidence blocks delivery; provider verification cannot replace executed tests.
2. Invoke the configured `finalize` skill, then refresh the handoff with its
   finalization report and current artifact locations. The provider owns syncing,
   archiving, and recovery of its artifacts. If it changes the working tree,
   refresh provider verification, test receipts, and review before recording delivery.
3. Run `--archive <id>` to record the external finalization in Ship's ledger. In
   external mode this command validates gates and records delivery; it never moves
   or merges provider files. Interrupted finalization resumes through the provider.
4. Deliver a concise walkthrough: changes, specification links, review findings,
   test receipts, and remaining operational considerations. Generate commit
   trailers with `--generate-trailers --change <id>` when useful. Report tracked
   tokens/cost using `agentflow budget show`, or `not recorded` if unavailable.

Respect [Git mutation restrictions](./references/team_rollout.md#git-mutation-restrictions).
Whole-checkout rollback is unavailable in external SDD mode; use provider recovery
and explicit operator authorization for any separate restoration. Local handoffs
and approval receipts are workflow records, not authenticated attestations.

For headless execution, see [CI guidance](./references/headless_ci_guide.md). For optional local step observations, see [step tracing](./references/step_tracing.md).

<turn_contract>
✓ 1. Refresh provider state and inspect the selected change's next turn before work.
✓ 2. Retain terminal receipts for executed tests and gate checks.
✓ 3. Record approvals, evidence, and turn provenance in the Ship ledger.
✓ 4. Claim completion only when current artifact and execution evidence supports it.
</turn_contract>
