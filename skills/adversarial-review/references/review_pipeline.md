# Review Pipeline

Execute every review through this standardized orchestrator pipeline:

```text
SKILL.md (Orchestrator)
    ↓
inspect_changes.sh (Git Scope, Linked Issues/Specs, Repo Standards, Change Triggers)
    ↓
review_modes.md (Active Stages & Execution Strategy)
  ├─ Standard Diff (≤400 lines) ──► Single Principal Reviewer
  └─ Large PR (>400 lines) / Parallel
       ──► Correctness + Concurrency + Design Agents
       ──► Review Judge (agents/review_judge.md)
    ↓
Structured Findings (Strict 12-Field Contract: finding_schema.md)
```

1. **Change & Context Discovery**: Run the [inspector](../scripts/inspect_changes.sh) by its resolved path from the target repository. Treat its output as hints, not authoritative coverage. Pin the base and reviewed snapshot first; verify the chosen Git refs resolve and inspect the actual diff. A failed diff command is an error, not an empty review. For working changes, include staged, unstaged, and relevant untracked files. If there is no change in the requested scope, report that rather than launching reviewers. Local reviews do not need a remote or PR. Identify:
   - **Spec Sources**: Linked issue numbers from commits (`#123`, `PROJ-456`), PRD/spec files under `docs/`, `specs/`, `.scratch/`, or user-supplied specs.
   - **Standards Sources**: Applicable root and path-scoped instructions (`AGENTS.md`, `CLAUDE.md`), conventions (`CODING_STANDARDS.md`, `CONTRIBUTING.md`, linter configs), and existing domain docs or ADRs. Read only documents relevant to the changed area. The repo's documented standards always override baseline heuristics; linters enforce syntax, the reviewer enforces logic and clean-code smells.
   - **Scope & Triggers**: Modified files, diff stats, test mappings, and review mode triggers.
2. **Targeted Mode Selection**: Consult [`review_modes.md`](./review_modes.md) to activate stages based on change signals before assigning work.
3. **Execution Strategy Selection**:
   - **Single Reviewer (Default, ≤400 diff lines)**: Evaluate the active stages directly, including Stage 0 when a spec exists.
   - **Multi-Agent Mode (>400 diff lines or explicit parallel request)**: Follow the specialist protocol in `review_modes.md`. Dispatch [Correctness](../agents/correctness_reviewer.md), [Concurrency](../agents/concurrency_reviewer.md), and [Design](../agents/design_reviewer.md) as selected by the active mode. Launch all selected specialists before waiting, keep their initial reports independent, and collect every outcome before starting the Judge; follow the parallel execution protocol in `review_modes.md`. The Principal Orchestrator owns Stage 0 and retained checks, then hands submitted candidates to the [Judge](../agents/review_judge.md) for adjudication. The Judge independently inspects relevant code before accepting findings and does not discover new problems. The orchestrator renders the final report from the adjudicated results. If delegation is unavailable, perform the same scoped passes sequentially and record that execution detail internally.
4. **Deep Inspection**: Read affected implementations and trace necessary callers and consumers. In diff reviews, establish how the change introduces, exposes, or worsens each reported issue; do not sweep unrelated old defects into the report. A requested repository audit may include existing defects within its agreed scope. Consult focused `git log` or `git blame` when the reason for touched code is unclear, not as a mandatory repository-wide pass. A standards finding must identify the applicable rule and source location; a smell remains a judgment call.
5. **Contract Adherence**: Format every identified issue using the strict 12-field schema defined in [`finding_schema.md`](./finding_schema.md).

---

## Optional Fix Handoff

For requested fixes, the orchestrator owns the state, stable finding IDs, three-round default, and lifecycle transitions defined in [review_loop.md](./review_loop.md). Complete its [scope and validation setup](./review_loop.md#scope-and-validation-setup) before the first repair.

When the user requests fixes, follow [code_fixer.md](../agents/code_fixer.md) after Judge adjudication. Pass only Judge-approved findings within the authorised scope, with final IDs and implementation context. Exclude raw reports, rejected/deferred candidates, and review deliberations. Preserve `fixability` in the handoff: only `autonomous` findings permit edits; `requires-human` findings return a human decision request with no code changed for that finding. The Fixer implements accepted decisions; it does not resolve reviewer disagreements. Review-only requests still end with the existing report.

---

## Fix acceptance

The Fixer applies its per-finding workflow, pre/post diff inspection, and four-part safety gate before reporting its implementation as `fixed`. This moves a ledger entry to FIXED; only subsequent source-based verification under `review_loop.md` moves it to VERIFIED. Consult [code_fixer.md](../agents/code_fixer.md) for the implementation rules. Preserve human-decision requests and report validation limits; never treat an accepted finding as proof that its fix is safe.

Phase 5 fix-loop runs apply [regression attribution, hard human boundaries, and convergence gates](./review_loop.md#attribute-regressions-to-fixes) before issuing APPROVE. Any unexpected test failure or required business/architecture decision stops all repairs; this overrides independent continuation. Use the Phase 5 summary for these runs.
