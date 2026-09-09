# Skills

One skill lives here: [adversarial-review](./skills/adversarial-review/SKILL.md).

It gives a coding agent instructions for reviewing code. The repo contains Markdown prompts, reference guides, and a Bash script. The agent runs the review. The script gathers context.

## Use it

Give your coding agent the [SKILL.md](./skills/adversarial-review/SKILL.md) file and the change to review. Include the issue or spec if you have one.

Example request:

> Use this skill to review my changes against main. Check the code and its callers. Report problems with evidence.

To run just the change inspector, run this from the Git repo you want to review. Replace `/path/to/skills` with this repo's location:

```bash
bash /path/to/skills/skills/adversarial-review/scripts/inspect_changes.sh --no-diff main...HEAD
```

The script lists changed files, diff stats, possible specs, review hints, matching test filenames, and possible callers. These are text and filename searches. It does not run tests or prove the code is correct. Remove `--no-diff` to print the diff too.

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

## Which reviewers run?

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

One report: summary, stage scorecard, prioritised findings, simplification opportunities, test gaps, and a verification checklist. Missing checks stay visible. Agent handoffs stay internal.

Each finding follows the same [12-field schema](./skills/adversarial-review/references/finding_schema.md), including its location, evidence, impact, fix, and confidence.

## Files

```text
skills/adversarial-review/
├── SKILL.md
├── agents/
│   ├── correctness_reviewer.md
│   ├── concurrency_reviewer.md
│   ├── design_reviewer.md
│   ├── review_judge.md
│   └── code_fixer.md
├── scripts/
│   └── inspect_changes.sh
└── references/
    ├── review_modes.md
    ├── finding_schema.md
    ├── handbook_foundations.md
    ├── handbook_craftsmanship.md
    ├── handbook_architecture.md
    ├── review_pipeline.md
    └── production_risk_matrix.md
```


These are adapted principles, not installed dependencies.
