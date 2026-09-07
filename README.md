# Antigravity Skills Repository

A centralized, multi-skill repository for Google Antigravity agents. This repository houses reusable, production-grade skills that can be consumed globally across workspaces or linked directly into individual projects.

---

## Repository Structure

The repository is structured to cleanly scale to multiple independent skills:

```text
skills/
├── .gitignore
├── README.md                             # Skills catalog & repository documentation
├── skills.json                           # Antigravity customization manifest
└── skills/                               # Root directory for all skills
    └── <skill-name>/                     # Individual skill package
        ├── SKILL.md                      # Core prompt, triggers, and short rules (always loaded)
        ├── scripts/                      # (Optional) Executable CLI helpers
        │   └── ...
        └── references/                   # (Optional) Engineering handbooks (loaded on-demand only)
            └── ...
```

---

## Skills Catalog

| Skill Name | Identifier | Triggers | Description |
|---|---|---|---|
| **Adversarial Code Review** | [`adversarial-review`](./skills/adversarial-review/) | `/adversarial-review`, `"adversarial review"`, `"review like a principal engineer"`, `"code review"`, `"PR review"`, `"diff review"`, `"pre-deploy risk review"` | Conducts an exhaustive, zero-blindspot code review adopting the persona of a Senior Principal Engineer. Evaluates code strictly across a 9-stage engineering hierarchy. |

---

## Featured Skill: `adversarial-review`

A production-grade code review skill designed around a low-cognition, progressive disclosure architecture:

- **Persona**: Senior Principal Engineer (uncompromising on correctness, allergic to bloat, zero hand-waving, pragmatic minimalism).
- **The 9-Stage Evaluation Hierarchy**:
  ```text
  1. Correctness
         ↓
  2. Concurrency / Safety
         ↓
  3. Failure / Resilience
         ↓
  4. Simplicity (YAGNI)
         ↓
  5. Maintainability
         ↓
  6. Reuse (DRY)
         ↓
  7. Performance
         ↓
  8. SOLID Principles
         ↓
  9. Patterns
  ```
- **The Engineering Handbook** (`skills/adversarial-review/references/`):
  - [`handbook_foundations.md`](./skills/adversarial-review/references/handbook_foundations.md): Deep-dive checklists for Correctness, Concurrency, and Failure Resilience.
  - [`handbook_craftsmanship.md`](./skills/adversarial-review/references/handbook_craftsmanship.md): Criteria for Simplicity, Maintainability, Reuse, and Performance.
  - [`handbook_architecture.md`](./skills/adversarial-review/references/handbook_architecture.md): Principles for SOLID and Design Patterns / Anti-Patterns.
  - [`production_risk_matrix.md`](./skills/adversarial-review/references/production_risk_matrix.md): Operational hazards, contract drift, DB migrations, and blast radius.
  - [`review_modes.md`](./skills/adversarial-review/references/review_modes.md): Tailored multi-pass review invocations.
- **Helper Script**:
  - [`scripts/inspect_changes.sh`](./skills/adversarial-review/scripts/inspect_changes.sh): Automated git inspector for working tree diffs, branch comparisons vs `main`, and commit histories.

---

## How to Install & Use Skills

### 1. Global Installation (Machine-Wide)

To make all skills in this repository available across all projects on your machine, add this repo's `skills` folder to your global `~/.gemini/config/skills.json`:

```json
{
  "entries": [
    {
      "path": "/Users/Sumanth/Documents/Projects/skills/skills"
    }
  ]
}
```

Or symlink individual skills into your global config directory:
```bash
ln -sfn /Users/Sumanth/Documents/Projects/skills/skills/adversarial-review ~/.gemini/config/skills/adversarial-review
```

### 2. Workspace Installation (Project-Specific)

To load skills into a specific project workspace, add a `skills.json` under the project's `.agents/` directory:

```json
{
  "entries": [
    {
      "path": "/Users/Sumanth/Documents/Projects/skills/skills"
    }
  ]
}
```

---

## Adding a New Skill

To contribute a new skill to this repository:

1. **Create Skill Directory**:
   ```bash
   mkdir -p skills/<new-skill-name>/references skills/<new-skill-name>/scripts
   ```
2. **Author `SKILL.md`**:
   Ensure it begins with standard YAML frontmatter:
   ```markdown
   ---
   name: my-new-skill
   description: >-
     Clear explanation of what the skill does and when the agent should trigger it.
     Mention trigger phrases (e.g. /my-new-skill).
   ---
   ```
3. **Follow the Low-Cognition Architecture**:
   - Keep `SKILL.md` lean (~100 lines) with high-density "always loaded" short rules.
   - Place detailed checklists, manuals, and deep reference material in `references/` so the agent loads them only when required.
4. **Register in `README.md`**: Add the new skill to the Skills Catalog above.
