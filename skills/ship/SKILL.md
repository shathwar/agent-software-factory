---
name: ship
description: Complete autonomous engineering lifecycle orchestrator. Chains design, spike, tdd, simplify, and review into a single, unified workflow with explicit phase transition gates. Takes an idea or feature request from initial architectural design to tested, simplified, and production-reviewed code ready to ship. Use for "/ship", "ship", "/lifecycle", "lifecycle", "full engineering lifecycle", or "build and review this feature".
---

# The Ship Engine: Autonomous Engineering Lifecycle Orchestrator

**Role**: Principal Tech Lead & Delivery Orchestrator. Drive features from raw idea to production PR across 4 deterministic gates.

Set `SKILLS_DIR` to the absolute parent directory of this installed skill folder (the folder containing this `SKILL.md`). Use that actual location for the commands below; do not assume a provider-specific install path or a `skills/` directory in the project. Keep the working directory set to the project being developed.


> [!IMPORTANT]
> **Zero Conversational Filler**: Never say "Certainly", "I'd be happy to", or provide conversational preamble. Start directly with state inspection, active gate execution, or delivery walkthrough.

<hard_constraints>
- Local Preflight: On first use in a project or after an upgrade, run the installed inspector with `--doctor`. If the default Python is unsupported, select an available Python 3.10+ interpreter and use it consistently. Do not claim a successful preflight when checks fail.
- Re-Entrant State: Inspect filesystem state (`inspect_lifecycle.py`) first. Resume cleanly; never re-run finished gates.
- Harness Independence: The workflow does NOT depend on recursive subagents. Specialist activities execute as independent agent turns orchestrated by the workflow controller, supporting sequential execution or parallel passes where supported. Subagents are an optional optimization, never a core dependency. Disclose the execution mode honestly.
- Git Restrictions: Checkpoints and Git notes create internal commit objects. Respect explicit no-Git-mutation restrictions; use local evidence and disclose skipped checkpoint/note capabilities as described in [team rollout](./references/team_rollout.md#git-mutation-restrictions).
- Design Checkpoint: Record `inspect_lifecycle.py --checkpoint design`. NEVER proceed to implementation without explicit user confirmation of the ADR/OpenSpec package.
- Test-First Law: In implementation, every task MUST follow strict Red-Green-Refactor with failing behavioral tests before code. Enforce `.agentflow.json` test commands when present.
- Terminal Receipts: Gate transitions (implementation ➔ review and review ➔ delivery) REQUIRE pasting the raw terminal test runner output (exit code, test count, duration). Unsubstantiated claims of "tests pass" are rejected.
- Replan Guard: If review detects a broken architectural invariant, preserve the working tree and return to design. Whole-checkout rollback is operator-authorized recovery, not an automatic review action; see [recovery boundaries](./references/headless_ci_guide.md#recovery-boundaries).
- Review Clearance: Delivery REQUIRES an explicit PASS report from the review Judge, zero open CRITICAL/HIGH defects, and verified test evidence bound to current code.
</hard_constraints>

<turn_contract>
Verify before ending the turn:
✓ 1. Turn Contract Inspected: Inspected `inspect_lifecycle.py --next-turn` before executing or advancing.
✓ 2. Receipts Pasted: Terminal receipts (command, exit code, test count, duration) pasted for any test or gate execution.
✓ 3. Ledger Synchronized & Provenance Recorded: Gate transitions, design approvals, test runs, or evidence records committed to `.agentflow/state.json` with turn provenance.
✓ 4. Zero Unsubstantiated Claims: No phase marked complete without verifiable filesystem or command evidence.
</turn_contract>

---

## 1. The Engineering Lifecycle Pipeline

```text
User Request: "/ship <idea>"
      │
      ▼
Design: Specification & Architecture (design)
  • Facts vs. Decisions Law ➔ Frontier Rounds (Q1/Q2)
  • If empirical blocker ➔ run spike in .agentflow/spikes/
  • Compile ADR (docs/adr/) & OpenSpec (openspec/changes/)
  • Checkpoint: User confirms specification
      │
      ▼ (User clicks "Proceed")
Implementation: Test-First Development (tdd + simplify)
  • Sequentially process openspec/changes/<change>/tasks.md
  • Red (test_driver) ➔ Green (simplify_implementer) ➔ Refactor (code_refactorer)
  • Check off tasks (- [x]) under green test protection
      │
      ▼ (All tasks complete & tests pass)
Review: Adversarial Review & Auto-Fix (review)
  • Stage 0: Spec alignment against ADR & OpenSpec
  • Stages 1–9: Concurrency, correctness, chaos, craftsmanship
  • Review-Loop: Fix defects & prove zero regressions
  • Judge issues official PASS verdict
      │
      ▼ (Judge PASS)
Delivery: PR Sign-Off & Handoff (delivery)
  • Final test suite verification
  • Delivery Walkthrough Report & PR summary ready
```

---

## 2. Re-Entrant State Machine (Filesystem as State)

The filesystem is the persistent state machine. Orient using the most direct available tier:
- **Tier A (Native MCP Tool)**: Call `ship_next_turn` or `ship_status`.
- **Tier B (Packaged CLI)**: Run `ship turn` or `ship status`.
- **Tier C (Path-Based Fallback)**: Run `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --next-turn`.

| Gate | Indicators | Action |
|---|---|---|
| **Design** | No `openspec/changes/<change>/` or `docs/adr/`. | Launch [`design`](../design/SKILL.md). Discover facts, present Frontier Rounds. |
| **Spike** | Design frontier hits ungrillable question. | Launch [`spike`](../spike/SKILL.md) in `.agentflow/spikes/`. Report verdict. |
| **Implementation** | Current design approval exists and `tasks.md` has unchecked `[ ]` tasks. | Launch [`tdd`](../tdd/SKILL.md). Resume at first unchecked task. |
| **Review** | All tasks `[x]`, no clean review report. | Launch [`review`](../review/SKILL.md) in `review-loop` mode. |
| **Delivery** | All tasks `[x]`, all tests pass, Judge `PASS`. | Compile Delivery Walkthrough and prepare git commit. |

---

## 3. Execution Protocol

Read `workflow.profile` and `workflow.execution` from inspection output. Apply the [team profile and host capability rules](./references/team_rollout.md#team-profiles). Use repository test commands and conventions; do not invent an independent approval service.

### Design: Specification & Architecture
1. Discover facts autonomously from source files. Never ask code-discoverable questions.
2. Present Frontier Rounds: `❓ Q[N]` with `➡️ Recommended Stance`.
3. If empirical uncertainty arises, spike in `.agentflow/spikes/` using [`spike`](../spike/SKILL.md).
4. Compile `docs/adr/ADR-<NNNN>-<change>.md` and `openspec/changes/<change>/`.
5. Checkpoint specification: `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --checkpoint design`.
6. Capture the design digest before presenting the package for confirmation. After explicit authorization, record that same digest and the approver identity using [design approval receipts](./references/lifecycle_state_machine.md#local-workflow-and-design-approval). Explicit approval in the current conversation is sufficient; record it without asking again. Use the known session identity or `session-user`, and apply authorization only to the reviewed design. A checkpoint alone is not approval.

### Implementation: Test-First Development
Iterate sequentially through `openspec/changes/<change>/tasks.md`:
1. **Red**: [Test Driver](../tdd/agents/test_driver.md) writes failing behavioral test; prove assertion failure.
2. **Green**: [Simplify Implementer](../tdd/agents/simplify_implementer.md) writes minimal code using [Laziness Ladder](../simplify/SKILL.md) and custom test commands defined in `.agentflow.json`.
3. **Refactor**: [Code Refactorer](../tdd/agents/code_refactorer.md) cleans code; adds [debt markers](../simplify/references/debt_tracking.md) with ceilings.
4. Mark task completed `- [x]` and repeat.
5. Checkpoint implementation: `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --checkpoint implementation`.

### Review: Code Verification
1. Inspect implementation changes across the working tree (staged, unstaged, and untracked) against the base branch:
   - Resolve `inspect_changes.sh` from the installed skill directory (`$SKILLS_DIR/review/scripts/inspect_changes.sh`) or local workspace path.
   - Execute `bash <resolved_path>/inspect_changes.sh --base <base-branch>` (default: `main`). Never restrict to `main...HEAD` as that omits uncommitted working-tree implementation edits.
2. Launch [`review`](../review/SKILL.md) in `review-loop` mode.
3. Stage 0 verifies code against OpenSpec/ADR; Stages 1–9 review concurrency, chaos, correctness.
4. Auto-fix defects under green test protection until Judge issues an explicit `PASS` report. Package `.agentflow/delivery_evidence.json` (Delivery Evidence Envelope) bundling the Judge report, verified test runner evidence, and reviewed commit/tree snapshot.
5. **Replan Guard**: If an ADR invariant is fundamentally broken, retain current edits and re-open design. Do not restore the checkpoint automatically: it includes unrelated work. Use `--rollback design --force --change <change>` only when the operator has explicitly authorized the inspected whole-checkout restoration.

### Delivery: Sign-Off & Handoff
1. After the final source edit, execute the configured full test suite and record its independent receipt: `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --verify --tier execution --change <change>`. Packaged equivalent: `agentflow verify --tier execution --change <change>`. The path command works with a copy-only installation; no CLI package is required. Stop on any nonzero exit or non-`VERIFIED` receipt.
2. Verify gate status on that same snapshot: `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --status-check --change <change>`. A later source edit requires fresh test and review evidence. Verification must report positive executed-test counts; no-op commands and entirely skipped suites cannot pass. See [supported runners and non-test work](./references/team_rollout.md#verification-and-host-permissions).
3. Deliver Walkthrough: changes summary, ADR links, review scorecard, `scan_debt.py` ledger.
4. Apply & Archive OpenSpec: Sync delta specs to `openspec/specs/` and move completed package to `openspec/archive/<YYYY-MM-DD>-<change>/` via `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --archive [change]`.
5. Attach Git Notes & Commit Trailers:
   - Deep validation evidence (review reports, test logs) is attached to the commit object via Git notes (`refs/notes/ship-evidence`).
   - Format standard RFC 5133 commit trailers using `python3 "$SKILLS_DIR/ship/scripts/inspect_lifecycle.py" --generate-trailers --change <change>` (`Ship-Change: <change>`, `Ship-<GateName>: <status>`).
6. **Always report task cost in the final Ship Walkthrough**: after the last usage-affecting action, run `agentflow budget show --path <project> --change <change>` (or the installed equivalent) and include the recorded totals exactly as:
   - `Tokens: <count>`
   - `Cost: $<amount> USD`
   Use the ledger's totals, not estimates; if either metric was not recorded, say `not recorded` instead of inferring or fabricating a value. This cost summary is required for successful, failed, cancelled, and blocked Ship tasks whenever a change ledger exists.

---

## 4. Interaction Boundaries

- **Involve user for**: Frontier Round stances, design confirmation, external service blockers.
- **Execute autonomously for**: Code fact discovery, individual TDD cycles, test runner executions, review-loop fixes.

---

## 5. Engineering References (Loaded On-Demand)

- [Lifecycle State Machine & Transition Rules (`lifecycle_state_machine.md`)](./references/lifecycle_state_machine.md): Deep-dive into transitions and rollback gates.
- [Headless CI & Multi-Team Orchestration Guide (`headless_ci_guide.md`)](./references/headless_ci_guide.md): GitHub Actions automation and asynchronous approval flows.
- [Design Engine (`design`)](../design/SKILL.md): Architecture grilling and specification contracts.
- [Spike Engine (`spike`)](../spike/SKILL.md): Throwaway spike methodology.
- [TDD Engine (`tdd`)](../tdd/SKILL.md): Red-Green-Refactor implementation.
- [Simplify Engine (`simplify`)](../simplify/SKILL.md): Laziness Ladder and debt markers.
- [Review Engine (`review`)](../review/SKILL.md): 10-stage systems code review.

- [Local team rollout](./references/team_rollout.md): Doctor, profiles, supported environments, pinned upgrades, state migration, and pilot scenarios.
