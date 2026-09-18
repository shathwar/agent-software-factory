# Nano Skill Distribution

Ultra-high-density, token-optimized engineering rules designed for token-constrained agent contexts, custom system instructions, and IDE rule files (`CLAUDE.md`, `.cursorrules`, `AGENT.md`, `copilot-instructions.md`).

---

## Token Economy & Philosophy

While the full [`skills/`](../skills/) distribution provides comprehensive workflows, modular agent personas, on-demand reference handbooks, and CLI automation, the `nano/` distribution strips away conversational instructions to deliver **dense, non-negotiable systems invariants** with minimal token overhead.

### Density Budgets (Tested & Enforced)

Every file in this directory is subject to strict automated size ceilings in [`tests/test_nano_rules.py`](../tests/test_nano_rules.py):
- **Universal Manifest (`AGENTS.md`)**: $\le$ 100 lines, $\le$ 6,000 bytes (~1,200 tokens).
- **Individual Nano Rules (`*.nano.md`)**: $\le$ 60 lines, $\le$ 4,000 bytes (~750 tokens each).

---

## Artifacts in this Directory

### 1. `AGENTS.md` (Universal Ruleset)
A single combined reference covering all 6 engineering disciplines, grounded in canonical literature:
- **Martin Kleppmann** (*Designing Data-Intensive Applications*): Invariants, transactions, concurrency hazards, fencing tokens.
- **Michael Nygard** (*Release It!*): Circuit breakers, bulkheads, timeouts on all I/O, poison-pill DLQs.
- **John Ousterhout** (*A Philosophy of Software Design*): Deep modules over shallow wrappers, defining errors out of existence.

### 2. Specialist Nano Rules (`*.nano.md`)
Granular rules for modular injection into specific agent sub-prompts or focused projects:

| File | Discipline | Key Invariants |
|---|---|---|
| [`design.nano.md`](./design.nano.md) | Systems Design | Facts vs. Decisions Law, decision frontier batching, ungrillable detection. |
| [`spike.nano.md`](./spike.nano.md) | Empirical Spikes | Scratch isolation (`.scratch/`), falsifiable SLIs, statistical percentiles. |
| [`tdd.nano.md`](./tdd.nano.md) | Test-Driven Dev | Zero production code before failing test, dual-speed testing tiers (domain vs persistence). |
| [`simplify.nano.md`](./simplify.nano.md) | Anti-Bloat | Laziness Ladder, YAGNI, deep modules, explicit `simplify:` debt ceilings. |
| [`review.nano.md`](./review.nano.md) | Code Review | Evidence-based judge (reject hallucinations), 10-stage review hierarchy. |
| [`ship.nano.md`](./ship.nano.md) | Delivery SDLC | Deterministic phase gates, git tag checkpoints, tri-tier state ledger. |

---

## Usage Patterns

### Pattern A: Single-File Repository Rules
To equip an AI agent with universal production engineering standards in any project, copy `AGENTS.md`:

```bash
# For Claude Code
cp nano/AGENTS.md /path/to/project/CLAUDE.md

# For Cursor
cp nano/AGENTS.md /path/to/project/.cursorrules

# For GitHub Copilot Workspace
cp nano/AGENTS.md /path/to/project/.github/copilot-instructions.md
```

### Pattern B: Selective Inlining
For specialized agent personas, concatenate only the disciplines relevant to that worker:

```bash
# E.g., For an autonomous implementation worker:
cat nano/tdd.nano.md nano/simplify.nano.md > /path/to/project/.gemini/worker_prompt.md
```
