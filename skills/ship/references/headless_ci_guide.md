# Headless CI & Multi-Team Automation Guide

A production guide for running the **Ship Lifecycle Engine** headlessly in CI/CD (GitHub Actions, GitLab CI) and decoupling agent execution from synchronous chat sessions.

---

## 1. The Headless Problem & Solution

In standard interactive sessions, `/ship` prompts the engineer for approval at **Gate 1 (Specification Checkpoint)**. In enterprise teams with multiple squads, running long-running features inside a local IDE chat is inconvenient.

The headless workflow decouples the 4 gates into asynchronous CI steps:

```text
               1. Engineer files Issue: "/ship Add Stripe Webhook Idempotency"
                                      │
                                      ▼
                      GitHub Action triggers Gate 1
                                      │
                                      ▼
               2. Agent compiles ADR & OpenSpec Change Package
                  Posts Architecture Decision to Issue Comment
                                      │
                                      ▼
                   Tech Lead labels: "ship:approved"
                                      │
                                      ▼
                      GitHub Action triggers Gate 2 & 3
                  • TDD: Red-Green-Refactor tasks.md
                  • Simplify: stdlib-first anti-bloat
                  • Adversarial Review: Judge PASS audit
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

Every repository or monorepo service can include a `.ship.json` (or `.ship.yaml`) at its root or service directory:

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
    "audit": {
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
  },
  "telemetry": {
    "sink": ".scratch/lifecycle_events.jsonl"
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
  gate1_spec:
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
      - name: Sanitize Topic Title
        env:
          RAW_TITLE: ${{ github.event.issue.title }}
        run: |
          python3 -c '
          import os, re, sys
          raw = os.environ.get("RAW_TITLE", "")
          topic = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw).strip("-").lower()[:50]
          if not topic:
              print("Invalid topic: must contain alphanumeric characters", file=sys.stderr)
              sys.exit(1)
          with open(os.environ["GITHUB_ENV"], "a") as f:
              f.write(f"TOPIC={topic}\n")
          '

      - name: Run Gate 1 Agent (Design & Specification)
        env:
          ISSUE_BODY: ${{ github.event.issue.body }}
        run: |
          echo "Executing Gate 1 agent runner for topic: $TOPIC"
          # 1. Execute agent runner harness with design skill prompt
          # e.g., agy run --skill design "Design spec for: $TOPIC based on $ISSUE_BODY"
          # 2. Record and assert Gate 1 Checkpoint
          python3 skills/ship/scripts/inspect_lifecycle.py --checkpoint gate-1-spec --topic "$TOPIC"

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

  gate2_and_3_implementation:
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

      - name: Verify Gate 1 Checkpoint Status
        run: |
          python3 skills/ship/scripts/inspect_lifecycle.py --format json

      - name: Run Gate 2 (TDD Implementation) & Gate 3 (Code Audit)
        run: |
          # 1. Execute agent runner harness for TDD tasks
          # e.g., agy run --skill tdd "Execute tasks in active openspec"
          python3 skills/ship/scripts/inspect_lifecycle.py --checkpoint gate-2-impl

          # 2. Execute agent runner harness for Audit loop
          # e.g., agy run --skill audit "Review changes in review-loop mode"

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
            - Verified against Gate 1 ADR & OpenSpec
            - Adversarial Review Judge verdict: **PASS**
          branch: "ship/${{ github.event.issue.number }}"
```

---

## 5. State Machine Automation Commands

| Command | Purpose in CI/CD |
|---|---|
| `python3 skills/ship/scripts/inspect_lifecycle.py --status-check` | Exits `0` if ready for delivery, `1` if blocked, `2` if rollback required. Use in CI branch protection. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --checkpoint <gate>` | Records immutable internal git refs (`refs/ship/...`) and JSON receipts in `.scratch/`. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --rollback gate-1-spec` | Safely archives untracked/modified edits to `.scratch/backups/` and resets `tasks.md` for revision. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --archive <topic>` | Syncs delta specs into `openspec/specs/` and archives completed change packages. |
