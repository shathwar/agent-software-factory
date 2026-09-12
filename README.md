# Skills

A repository of production-grade engineering skills for AI agents, covering the complete lifecycle from architectural design to post-implementation code review:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                 PRE-IMPLEMENTATION: adversarial-design                      │
│   • Persona: Senior Principal Systems Architect                             │
│   • Model: Design Tree & Frontier Algorithm (Round-based batching)          │
│   • Inquiry: State, Concurrency, Failure, Schema, Blast Radius              │
│   • Output: Architecture Decision Record (ADR) & OpenSpec Package           │
└──────────────────────┬───────────────────────────────┬──────────────────────┘
                       │                               │
                       ▼ (Ungrillable Question?)       │
        ┌─────────────────────────────┐                │
        │      SPIKE: prototype       │                │
        │   • Isolated scratch sandbox│                │
        │   • Measures empirical SLIs │                │
        │   • Settles design frontier │                │
        └──────────────┬──────────────┘                │
                       │ (Verdict returned)            │
                       ▼                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│          IMPLEMENTATION FLOW: tdd (Red-Green-Refactor) + ponytail           │
│   • Test Driver: Writes failing behavioral test (Red Phase)                 │
│   • Ponytail Implementer: Climbs Laziness Ladder, stdlib-first (Green)      │
│   • Code Refactorer: Simplifies under green; adds ponytail: debt markers    │
│   • Inputs: OpenSpec tasks.md & specs/ acceptance criteria                  │
│   • Output: Self-verifying, lean production implementation                  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼ (Code & Tests Complete)
┌─────────────────────────────────────────────────────────────────────────────┐
│                 POST-IMPLEMENTATION: adversarial-review                     │
│   • Stage 0: Spec Alignment (Verifies code directly against ADR/Spec)       │
│   • Stages 1–9: Correctness, Concurrency, Failure, Craftsmanship, SOLID     │
│   • Actions: review, review-pr, review-loop                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Skills Catalog

| Skill Name | Command / Trigger | Lifecycle Stage | Description |
|---|---|---|---|
| [**`adversarial-design`**](./skills/adversarial-design/SKILL.md) | `/adversarial-design`, `"grill me on this design"` | Pre-implementation | Relentlessly stress-tests architectures and plans using frontier rounds. Compiles an ADR & OpenSpec. |
| [**`prototype`**](./skills/prototype/SKILL.md) | `/prototype`, `"prototype"`, `"spike"` | Empirical Validation | Rapid, disposable spikes answering ungrillable design questions in isolated sandboxes. |
| [**`tdd`**](./skills/tdd/SKILL.md) | `/tdd`, `"tdd"`, `"red-green-refactor"` | Implementation | Disciplined test-driven development engine with dedicated Test Driver, Implementer, and Refactorer agents. |
| [**`ponytail`**](./skills/ponytail/SKILL.md) | `/ponytail`, `"ponytail"`, `"lazy senior dev"` | Simplicity & Anti-Bloat | Forces the simplest working solution: YAGNI, standard library first, zero unrequested abstractions. |
| [**`adversarial-review`**](./skills/adversarial-review/SKILL.md) | `/adversarial-review`, `"adversarial review"` | Post-implementation | 10-stage systems audit across correctness, concurrency, failure modes, and production risk. |

---

## 1. `adversarial-design` (Pre-Implementation)

Give your agent the [adversarial-design SKILL.md](./skills/adversarial-design/SKILL.md) and your proposal or idea.

- **The Facts vs. Decisions Law**: The agent autonomously inspects the codebase for facts. User turns are reserved strictly for architectural trade-offs.
- **Frontier Rounds**: Batches unblocked questions with concrete recommended stances (`❓ Q1` + `➡️ Recommended Stance`) so you can answer rapidly by number.
- **Ungrillable Detection**: Recognizes when questions cannot be settled by talk and prompts a timeboxed spike/prototype using [prototype](./skills/prototype/SKILL.md).
- **Output**: Generates a standard [Architecture Decision Record (ADR)](./skills/adversarial-design/references/adr_template.md) under `docs/adr/` and/or an executable [OpenSpec Change Package](./skills/adversarial-design/references/openspec_template.md) under `openspec/changes/`, which become the input contracts for `adversarial-review`.

---

## 2. `prototype` (Empirical Validation & Spikes)

Give your agent the [prototype SKILL.md](./skills/prototype/SKILL.md) and the empirical question or hypothesis.

- **Throwaway Mindset**: Strict isolation to `.scratch/<spike-name>/`. Zero pollution of production source trees.
- **Minimal Viable Harness**: Hack, don't architect. Bypass layers and mock services to measure the single variable under test.
- **Measurement Hygiene**: Warm-up passes, percentile distributions (p50/p95/p99/max), and realistic concurrency.
- **Decision Settlement**: Concludes with a structured report that settles the design frontier and feeds empirical rationale directly into the ADR.
- **References**: Consult [Spike Guidelines](./skills/prototype/references/spike_guidelines.md) and ready-to-use [Experiment Templates](./skills/prototype/references/experiment_templates.md).

---

## 3. `tdd` (Implementation Flow & Reusable Agents)

Give your agent the [tdd SKILL.md](./skills/tdd/SKILL.md) and the task or OpenSpec package to implement.

- **The Multi-Agent Implementation Roster**:
  - [**Test Driver**](./skills/tdd/agents/test_driver.md): Red Phase. Translates specs into failing behavioral tests using AAA.
  - [**Ponytail Implementer**](./skills/tdd/agents/ponytail_implementer.md): Green Phase. Climbs the Laziness Ladder to write the minimum passing code.
  - [**Code Refactorer**](./skills/tdd/agents/code_refactorer.md): Refactor Phase. Cleans code while tests remain green; adds debt markers.
- **The Iron Law**: No production code without a failing test first.
- **Red Verification**: Must execute the test suite and confirm the test fails for the expected reason before implementing.
- **References**: Consult [TDD Patterns & Testability](./skills/tdd/references/tdd_patterns.md) and the [Testing Anti-Patterns Catalog](./skills/tdd/references/anti_patterns.md).

---

## 4. `ponytail` (Lazy Senior Dev / Anti-Bloat)

Give your agent the [ponytail SKILL.md](./skills/ponytail/SKILL.md) when implementing features, refactoring, or choosing libraries.

- **The Laziness Ladder**: 1. YAGNI ➔ 2. Codebase reuse ➔ 3. Standard library ➔ 4. Platform native ➔ 5. Installed deps ➔ 6. One-liner ➔ 7. Minimum code.
- **Root-Cause Fixes**: Grep all callers and fix at the shared root, not symptom guards per caller.
- **Debt Tracking**: Mark deliberate pragmatic shortcuts with `// ponytail: <shortcut>. Ceiling: <limit>. Upgrade: <next step>.`
- **References**: Consult the [Laziness Ladder Guide](./skills/ponytail/references/laziness_ladder.md) and [Debt Tracking Protocol](./skills/ponytail/references/debt_tracking.md).

---

## 5. `adversarial-review` (Post-Implementation)

Give your coding agent the [SKILL.md](./skills/adversarial-review/SKILL.md) file and the change to review. Include the issue or spec if you have one.

Choose one action:

| Mode | What it does | Example request |
|---|---|---|
| `review` | Review Only. Return a report. | “Use adversarial-review in review mode against main.” |
| `review-pr` | Review + PR Comment. Post the report without changing the branch. | “Use adversarial-review in review-pr mode for PR #123.” |
| `review-loop` | Review + Fix Loop. Make scoped fixes, test, and re-review. | “Use adversarial-review in review-loop mode against main.” |

The agent defaults to `review` (Review Only) immediately. Asking to fix code selects `review-loop`, and asking to comment on a PR selects `review-pr`. A PR link alone does not authorise commenting; choosing `review-pr` does. Choosing `review-loop` permits fixes but does not commit or push them.

All three use one pipeline. The mode changes what happens after the Judge:

```text
Inspect → Pick checks → Review → Judge
                                 ├─ review      → Report
                                 ├─ review-pr   → PR comment
                                 └─ review-loop → Fix → Test → Re-review → Report
```

These are agent instructions, not installed shell commands. PR commenting needs authenticated provider access; if posting fails, the agent returns the prepared report and the blocker.

To run just the change inspector, run this from the Git repo you want to review. Replace `/path/to/skills` with this repo's location:

```bash
bash /path/to/skills/skills/adversarial-review/scripts/inspect_changes.sh --no-diff main...HEAD
```

The script lists changed files, diff stats, possible specs, review hints, matching test filenames, and possible callers. These are text and filename searches. It does not run tests or prove the code is correct. Remove `--no-diff` to print the diff too.

The inspector requires Bash 3.2+ and Git. It includes individual untracked files and their diffs without staging them, preserves rename paths, and returns a nonzero status for invalid comparisons. Automatic scope selection uses the available local or remote-tracking `main`/`master` ref; a root commit is compared with the empty tree. Test and caller searches are hints from the current checkout, even when reviewing a historical range. Keep the checkout stable while it captures context.

For a whole-repository audit, ask “Review this repository adversarially.” The agent inventories the requested tree and reviews existing code even when there are no uncommitted changes. The change inspector alone is not a repository audit.

## How the review works

```text
Inspect change → Pick checks → Review → Judge → Report
```

The instructions use one reviewer for diffs of 400 lines or fewer. Larger diffs, or an explicit parallel request, use the selected specialists in parallel when the host supports it. Without that support, the agent performs the passes itself.

| Role | Job |
|---|---|
| [Correctness](./skills/adversarial-review/agents/correctness_reviewer.md) | Find broken behavior. Includes failure paths, migration integrity, and API compatibility. |
| [Concurrency](./skills/adversarial-review/agents/concurrency_reviewer.md) | Find races, locking problems, and async lifecycle failures. |
| [Design](./skills/adversarial-review/agents/design_reviewer.md) | Find needless complexity. No abstraction just because SOLID says so. |
| [Judge](./skills/adversarial-review/agents/review_judge.md) | Check submitted claims against the code. Remove duplicates and false positives. Rank what remains. Find no new problems. |

The main agent picks the checks, handles spec alignment, general performance, and broader production risks, then writes the report. Specialist prompts do not register or launch agents by themselves.

Specialists work independently. They do not read each other's first reports. The Judge must inspect relevant code before accepting a finding. Evidence wins. Agents do not vote.

## Fixes

If you ask for fixes, the [Code Fixer](./skills/adversarial-review/agents/code_fixer.md) gets only Judge-approved findings and the context needed to implement them. No raw reviewer reports. No rejected claims. It makes scoped changes for `autonomous` findings and reports validation results. For `requires-human`, it reports the decision needed and possible approaches without changing code for that finding. A review request alone does not trigger edits.

Requested fixes use a [bounded loop](./skills/adversarial-review/references/review_loop.md), with at most three rounds by default. Findings keep the same IDs from review through confirmation, fixing, and verification. Relevant reviewers check the combined fix patch, then the Judge validates the results. Business or architecture decisions, repeated fix failure, unexpected test failures, unrelated refactoring, and unresolved tradeoffs stop the whole loop for a human decision. Approval needs no remaining P0/P1, passing build/tests, no unresolved regression, and no unexplained changes. Optional P2 findings must be explicitly justified. The Autonomous Review summary shows iterations, counts, and verification results.

## Which reviewers run?

Action mode controls edits and publication. Change type controls which technical checks run.

| Change | Reviewers |
|---|---|
| Standard code | Correctness, Design |
| Shared state or async | Correctness, Concurrency, Design |
| Database migration | Correctness |
| Public API | Correctness |
| Dependencies or build | Correctness, Design |
| Financial logic | Correctness, Concurrency, Design |
| Full audit | Correctness, Concurrency, Design |

Mixed changes combine checks. Migration locks and async APIs add Concurrency. See [review modes](./skills/adversarial-review/references/review_modes.md) for the full rules.

## What gets checked?

The checklist has ten stages. Only relevant stages apply.

0. Spec alignment
1. Correctness
2. Concurrency and safety
3. Failure and resilience
4. Simplicity
5. Maintainability
6. Reuse
7. Performance
8. SOLID
9. Patterns

Fowler's code smells help the Design review. They are not another stage or automatic proof of a problem.

## What you get

All feedback uses plain, human language, including PR comments: what breaks, why it matters, and what to do next. Short and clear, with the evidence kept intact.

One report: summary, stage scorecard, prioritised findings, simplification opportunities, test gaps, and a verification checklist. Missing checks stay visible. Agent handoffs stay internal.

Each finding follows the same [12-field schema](./skills/adversarial-review/references/finding_schema.md), including its location, evidence, impact, fix, and confidence.

## Files

```text
skills/
├── adversarial-design/
│   ├── SKILL.md
│   └── references/
│       ├── interview_protocol.md
│       ├── systems_inquiry_matrix.md
│       ├── adr_template.md
│       └── openspec_template.md
├── prototype/
│   ├── SKILL.md
│   └── references/
│       ├── spike_guidelines.md
│       └── experiment_templates.md
├── tdd/
│   ├── SKILL.md
│   ├── agents/
│   │   ├── test_driver.md
│   │   ├── ponytail_implementer.md
│   │   └── code_refactorer.md
│   └── references/
│       ├── tdd_patterns.md
│       └── anti_patterns.md
├── ponytail/
│   ├── SKILL.md
│   └── references/
│       ├── laziness_ladder.md
│       └── debt_tracking.md
└── adversarial-review/
    ├── SKILL.md
    ├── agents/
    │   ├── correctness_reviewer.md
    │   ├── concurrency_reviewer.md
    │   ├── design_reviewer.md
    │   ├── review_judge.md
    │   └── code_fixer.md
    ├── scripts/
    │   ├── inspect_changes.sh
    │   └── validate_report.py
    └── references/
        ├── review_modes.md
        ├── finding_schema.md
        ├── agent_report.schema.json
        ├── handbook_foundations.md
        ├── handbook_craftsmanship.md
        ├── handbook_architecture.md
        ├── review_pipeline.md
        ├── review_loop.md
        └── production_risk_matrix.md
```


These are adapted principles, not installed dependencies.

## Validation

Run all checks from the repository root (Python 3.10+ standard library, zero pip dependencies required):

```bash
./scripts/run_tests.sh
```

The tests use disposable Git repositories and check inspector behavior, report validation, schema examples, and local Markdown link targets. CI runs them on Linux and macOS. Neither the inspector nor the report validator requires external Python packages.

Validate a saved reviewer/Judge report with:

```bash
python3 skills/adversarial-review/scripts/validate_report.py report.json
```

Validation checks the [report contract](./skills/adversarial-review/references/finding_schema.md), not the truth of findings or review completeness. [Behavioral evaluation cases](./tests/skill_evaluations.md) cover audit routing, authorisation, malformed reports, and repair-loop state. Run them separately with an agent; passing unit tests does not establish those behaviors.
