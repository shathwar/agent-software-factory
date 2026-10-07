# Developer Scripts Directory

This directory organizes developer tools, test runners, and setup automation into clear domain and intent subdirectories:

```text
scripts/
├── verify/                     # Verification, linting, parity & CI gates
│   ├── check_sanity.sh         # Syntax, parity, nano budget, and coverage checks
│   ├── check_coverage.py       # Skill step & rubric coverage scanner
│   ├── sync_parity.py          # Distribution parity checker & sync between src/ and skills/
│   └── ci_gate.py              # Pull-request / CI workflow policy gate
│
├── test/                       # Test runners
│   ├── test_fast.sh            # Selected unit tests
│   └── test_full.sh            # Full test suite (all unit, integration, and policy tests)
│
└── setup/                      # Environment setup & installation
    ├── install_skills.sh       # Portable installer for local AI hosts (Claude, Cursor, Codex)
    ├── setup_hooks.sh          # Git pre-commit hook installer (parity + coverage checks)
    └── setup_playground.sh     # Ephemeral disposable git sandbox provisioner
```

---

## Quick Reference / Cheat Sheet

### 1. Verification & Sanity Checks (`scripts/verify/`)

| Task | Command | Description |
|---|---|---|
| **Fast Sanity Check** | `./scripts/verify/check_sanity.sh` | Runs syntax, parity, nano budget, and coverage checks. |
| **Check Parity** | `python3 scripts/verify/sync_parity.py --check` | Checks lifecycle modules and the six mapped specialist tools. |
| **Sync Parity** | `python3 scripts/verify/sync_parity.py` | Syncs files selected by the parity mapping into `skills/`. |
| **Coverage Summary** | `python3 scripts/verify/check_coverage.py` | Audits skill step and rubric verification coverage across all 9 skills. |
| **Coverage Gaps** | `python3 scripts/verify/check_coverage.py --skill <name> --gaps` | Inspects verification gaps for a specific skill. |
| **CI Gate** | `python3 scripts/verify/ci_gate.py` | Strict gate used in CI pipelines. |

### 2. Testing (`scripts/test/`)

| Task | Command | Description |
|---|---|---|
| **Fast Tests** | `./scripts/test/test_fast.sh` | Runs the selected unit test modules. |
| **Full Suite** | `./scripts/test/test_full.sh` | Runs Python checks, regression tests (stub harness by default), and lifecycle benchmarks. Browser checks run separately. |

### 3. Setup & Environment (`scripts/setup/`)

| Task | Command | Description |
|---|---|---|
| **Install Skills** | `./scripts/setup/install_skills.sh --target-claude` | Symlinks skills into Claude Code/Desktop environments. |
| **Git Pre-commit Hook** | `./scripts/setup/setup_hooks.sh` | Installs `.git/hooks/pre-commit` to prevent parity drift and broken coverage. |
| **Git Playground** | `./scripts/setup/setup_playground.sh` | Creates an isolated sandbox repo in `.agentflow/playground`. |
