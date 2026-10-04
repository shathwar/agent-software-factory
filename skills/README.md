# Agent Skills Distribution

Modular, zero-external-dependency engineering skills for autonomous coding agents (Google Antigravity, Claude Code, and compatible agent runtimes).

---

## Canonical Skill Anatomy

Each skill folder in this directory follows a strict, predictable structural specification:

```text
skills/<skill-name>/
├── SKILL.md            # Required: Skill definition with YAML frontmatter, turn contracts, and rules
├── VERSION             # Required: Semantic version of the skill
├── agents/             # Optional: Specialized agent role sub-prompts for multi-agent delegation
├── references/         # Optional: On-demand markdown references, checklists, and templates
└── scripts/            # Optional: Self-contained zero-dependency Python utility and audit tools
```

### Component Roles

1. **`SKILL.md` (Root Manifest)**:
   - Includes YAML frontmatter with `name` and `description` triggering the skill.
   - Declares `<hard_constraints>` that the model must not violate.
   - Defines a `<turn_contract>` checklist verified before concluding the agent turn.
   - Documents core operating workflows, CLI commands, and links to references.

2. **`VERSION`**:
   - Plaintext semantic version identifier (e.g., `1.0.0`) tracking updates to skill logic.

3. **`agents/` (Role Prompts)**:
   - Contains targeted, single-responsibility system prompts for subagent workers (e.g., `principal_architect.md`, `test_driver.md`, `simplify_implementer.md`, `code_refactorer.md`, `review_judge.md`).

4. **`references/` (On-Demand Deep Context)**:
   - Supplemental architecture guides, design checklists, schema templates, and operational matrices loaded only when needed, conserving agent context windows.

5. **`scripts/` (Automated Tooling)**:
   - Standalone Python 3.10+ standard library scripts providing deterministic auditing, benchmarking, and lifecycle gates (e.g., `verify_tdd.py`, `scan_debt.py`, `run_spike.py`, `validate_report.py`, `lifecycle/`).

---

## The 8 Production Skills

| Skill | Directory | Triggers | Primary Agents | Specialist Script |
|---|---|---|---|---|
| **Design** | [`design/`](./design/) | `/design`, `design`, `architecture`, `grill me` | `principal_architect` | *(Autonomous file & schema inspection)* |
| **Spike** | [`spike/`](./spike/) | `/spike`, `spike`, `benchmark`, `proof of concept` | `spike_prototyper` | `scripts/run_spike.py` |
| **TDD** | [`tdd/`](./tdd/) | `/tdd`, `tdd`, `red-green-refactor`, `tests first` | `test_driver`, `simplify_implementer`, `code_refactorer` | `scripts/verify_tdd.py` |
| **Simplify** | [`simplify/`](./simplify/) | `/simplify`, `simplify`, `yagni`, `do less` | `simplify_implementer` | `scripts/scan_debt.py` |
| **Review** | [`review/`](./review/) | `/review`, `review`, `code review`, `diff review` | `review_judge`, `correctness_reviewer`, `code_fixer`, etc. | `scripts/validate_report.py` |
| **Ship** | [`ship/`](./ship/) | `/ship`, `ship`, `lifecycle`, `full lifecycle` | `lifecycle_orchestrator` | `scripts/lifecycle/*.py` |
| **Evals** | [`evals/`](./evals/) | `/evals`, `evals`, `eval`, `ai evals`, `error discovery` | `error_analyst`, `eval_auditor`, `judge_engineer`, `calibration_statistician` | `scripts/score_calibration.py` |
| **Debug** | [`debug/`](./debug/) | `/debug`, `debug`, `/fix`, `fix`, `bugfix`, `hotfix` | `root_cause_investigator`, `reproduction_specialist`, `surgical_fixer` | `scripts/verify_fix.py` |

---

## Installation & Discovery

Agent platforms discover skills through standard directory conventions:

### 1. Google Antigravity
- **User Global**: `~/.gemini/config/skills/<skill-name>/`
- **Workspace Local**: `<workspace-root>/.gemini/skills/<skill-name>/`

To link all skills globally:
```bash
for skill in design spike tdd simplify review ship evals debug; do
  ln -sfn "$(pwd)/skills/$skill" "$HOME/.gemini/config/skills/$skill"
done
```

### 2. Claude Code
- **User Global**: `~/.claude/skills/<skill-name>/`
- **Workspace Local**: `<workspace-root>/.claude/skills/<skill-name>/`

```bash
for skill in design spike tdd simplify review ship evals debug; do
  ln -sfn "$(pwd)/skills/$skill" "$HOME/.claude/skills/$skill"
done
```

---

## Zero-Drift Parity with `src/ship`

All Python automation scripts inside `skills/*/scripts/` are maintained in 100% byte-for-byte parity with the packaged `src/ship/` library.

Parity is enforced by automated test guards (`tests/test_packaging.py`) and managed via the sync engine:

```bash
# Verify parity without making changes
python3 scripts/sync_skills.py --check

# Synchronize modifications from src/ship into skills/
python3 scripts/sync_skills.py --direction src-to-skills

# Synchronize modifications from skills/ into src/ship
python3 scripts/sync_skills.py --direction skills-to-src
```
