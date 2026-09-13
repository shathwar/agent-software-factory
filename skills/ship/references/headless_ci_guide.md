# Headless CI & Multi-Team Automation Guide

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

## 3. Configuration: `.ship.json`

Every repository or monorepo service can include a `.ship.json` at its root or service directory:

```json
{
  "$schema": "https://raw.githubusercontent.com/shathwar/skills/main/skills/ship/references/ship.schema.json",
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

## 4. Reference Secure GitHub Action Workflow (`.github/workflows/ship_headless.yml`)

```yaml
name: Autonomous Ship Lifecycle

on:
  issues:
    types: [opened, labeled]

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  design_spec:
    # Security: Restrict execution to organization members/collaborators to prevent DoS and runner exhaustion
    if: >
      github.event_name == 'issues' &&
      github.event.action == 'opened' &&
      startsWith(github.event.issue.body, '/ship') &&
      contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.issue.author_association)
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      # Security: Sanitize title to prevent shell injection (FINDING-001)
      - name: Sanitize Change ID
        env:
          RAW_TITLE: ${{ github.event.issue.title }}
        run: |
          python3 -c '
          import os, re, sys
          raw = os.environ.get("RAW_TITLE", "")
          change = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw).strip("-").lower()[:50]
          if not change:
              print("Invalid change title: must contain alphanumeric characters", file=sys.stderr)
              sys.exit(1)
          with open(os.environ["GITHUB_ENV"], "a") as f:
              f.write(f"CHANGE={change}\n")
          '

      - name: Run Design Agent (Specification & Architecture)
        env:
          ISSUE_BODY: ${{ github.event.issue.body }}
        run: |
          echo "Executing Design agent runner for change: $CHANGE"
          # 1. Execute agent runner harness with design skill prompt
          # e.g., agy run --skill design "Design spec for: $CHANGE based on $ISSUE_BODY"
          # 2. Record and assert Design Checkpoint
          python3 skills/ship/scripts/inspect_lifecycle.py --checkpoint design --change "$CHANGE"

      - name: Post Spec Comment
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `### 📋 Specification Ready for Review\n\nPlease review the generated ADR and OpenSpec package for \`${process.env.TOPIC}\`. When approved, label this issue with \`ship:approved\` to proceed to implementation.`
            });

  implementation_and_review:
    if: >
      github.event_name == 'issues' &&
      github.event.action == 'labeled' &&
      github.event.label.name == 'ship:approved' &&
      contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.sender.author_association)
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Verify Design Checkpoint Status
        run: |
          python3 skills/ship/scripts/inspect_lifecycle.py --format json

      - name: Run Implementation (TDD) & Review (Code Review)
        run: |
          # 1. Execute agent runner harness for TDD tasks
          # e.g., agy run --skill tdd "Execute tasks in active openspec"
          python3 skills/ship/scripts/inspect_lifecycle.py --checkpoint implementation

          # 2. Execute agent runner harness for Review loop
          # e.g., agy run --skill review "Review changes in review-loop mode"

          # 3. Assert full delivery status
          python3 skills/ship/scripts/inspect_lifecycle.py --status-check

      - name: Open Pull Request
        uses: peter-evans/create-pull-request@v6
        with:
          title: "feat: ${{ github.event.issue.title }}"
          body: |
            Closes #${{ github.event.issue.number }}
            
            ### Delivery Walkthrough
            - Automated Implementation via Ship Engine
            - Verified against ADR & OpenSpec
            - Adversarial Review Judge verdict: **PASS**
          branch: "ship/${{ github.event.issue.number }}"
```

---

## 5. State Machine Automation Commands

| Command | Purpose in CI/CD |
|---|---|
| `python3 skills/ship/scripts/inspect_lifecycle.py --status-check` | Exits `0` if ready for delivery, `1` if blocked, `2` if rollback required. Use in CI branch protection. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --checkpoint <gate>` | Records immutable internal git refs (`refs/ship/...`) and JSON receipts in `.scratch/`. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --rollback design` | Safely archives untracked/modified edits to `.scratch/backups/` and resets `tasks.md` for revision. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --archive <change>` | Syncs delta specs into `openspec/specs/` and archives completed change packages. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --generate-trailers` | Emits RFC 5133 Git commit trailers mapping to `.ship.json` gates. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --sync-state` | Re-synchronizes `.ship/state.json` authoritative ledger from workspace artifacts. |


## Recovery boundaries

Rollback restores a whole checkout snapshot. Use one active change per checkout and
separate Git worktrees for parallel changes. Rollback refuses a checkout containing
other active ledger changes or OpenSpec packages, including with `--force`.
A matching checkpoint receipt and valid snapshot/base commits are required. A
checkpoint recorded before the first Git commit cannot restore files.

Rollback copies affected files, including task progress, before restoring or deleting
anything. Backups live in `.scratch/rollback_<timestamp>/`, with new files also under
`untracked_removed/`. Backup failures stop the operation. If a later Git operation
fails, the command reports failure and the backup location; inspect that backup and
Git status before retrying. The ledger is not advanced on a failed rollback.

A corrupt or unsupported `.ship/state.json` stops state operations and is left
unchanged. Restore a known-good copy. If none exists, explicitly move the damaged
file to a recovery location before running `--sync-state`, then reconcile manual
holds, test failures, and other records that workspace artifacts cannot reconstruct.
Do not automate that move or treat inferred state as restored approval evidence.

Evidence recording fails if its Git note cannot be saved; fix the Git write error
and retry before considering the ledger updated. Checkpoint snapshot failures also
return an error rather than substituting HEAD for uncommitted work.
