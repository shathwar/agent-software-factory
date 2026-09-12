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
                  • Ponytail: stdlib-first anti-bloat
                  • Adversarial Review: Judge PASS audit
                                      │
                                      ▼
               3. Action opens Pull Request with:
                  • Delivery Walkthrough Report
                  • Judge PASS Evidence Envelope
                  • Zero-regression terminal receipts
```

---

## 2. Configuration: `.ship.json`

Every repository or monorepo service should include a `.ship.json` at its root or service directory:

```json
{
  "version": 1,
  "project": {
    "name": "payment-gateway",
    "scope": "services/payment"
  },
  "gates": {
    "gate2_tdd": {
      "test_command": "pytest -q tests/unit",
      "typecheck_command": "mypy services/payment"
    },
    "gate3_audit": {
      "max_fix_iterations": 3,
      "debt_threshold": 0,
      "base_branch": "main"
    },
    "gate4_delivery": {
      "require_clean_working_tree": true,
      "target_branch": "main"
    }
  }
}
```

---

## 3. Reference GitHub Action Workflow (`.github/workflows/ship_headless.yml`)

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
    if: github.event_name == 'issues' && github.event.action == 'opened' && startsWith(github.event.issue.body, '/ship')
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Run Gate 1 (Design & Specification)
        run: |
          TOPIC=$(echo "${{ github.event.issue.title }}" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
          echo "Running Gate 1 for topic: $TOPIC"
          # Run agent with design
          python3 skills/ship/scripts/inspect_lifecycle.py --checkpoint gate-1-spec --topic "$TOPIC"

      - name: Post Spec Comment
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `### 📋 Specification Ready for Review\n\nPlease review the generated ADR and OpenSpec package. When approved, label this issue with \`ship:approved\` to proceed to implementation.`
            });

  gate2_and_3_implementation:
    if: github.event_name == 'issues' && github.event.action == 'labeled' && github.event.label.name == 'ship:approved'
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

      - name: Verify Gate 1 Checkpoint
        run: |
          python3 skills/ship/scripts/inspect_lifecycle.py --format json

      - name: Run Gate 2 (Implementation) & Gate 3 (Code Audit)
        run: |
          # Dispatch isolated subagents for TDD and Audit
          python3 skills/ship/scripts/inspect_lifecycle.py --checkpoint gate-2-impl
          # Run audit loop until Judge PASS
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

## 4. State Machine Automation Commands

| Command | Purpose in CI/CD |
|---|---|
| `python3 skills/ship/scripts/inspect_lifecycle.py --status-check` | Exits `0` if ready for delivery, `1` if blocked, `2` if rollback required. Use in CI branch protection. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --checkpoint <gate>` | Records immutable git refs (`refs/ship/...`) and JSON receipts in `.scratch/`. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --rollback gate-1-spec` | Automatically backs up broken edits to `.scratch/` and resets `tasks.md` for revision. |
| `python3 skills/ship/scripts/inspect_lifecycle.py --archive <topic>` | Syncs delta specs into `openspec/specs/` and archives completed change packages. |
