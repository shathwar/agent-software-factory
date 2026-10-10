# Claude Code Project Guidelines

## Engineering Lifecycle Standards

This repository develops the **Agentic Software Factory** (AgentFlow / Ship Engineering Lifecycle Engine) and modular agent skills. When operating in this project:

### 1. Directness & Zero Conversational Filler
- Never start responses with conversational fluff ("Certainly", "I'd be happy to", etc.).
- Begin directly with code, state inspection, or test execution receipts.

### 2. Model, Effort & Tool Optimization
- Refer to `.claude/skills/claude/SKILL.md` for choosing the optimal model, reasoning effort, and tool profiles.
- Route mechanical linting, search, and formatting to Haiku with low effort.
- Use Sonnet with calibrated effort (`medium` to `high`) for full-stack engineering, TDD, and systems review.
- Enforce least-privilege tool sandboxing via `allowed-tools`.

### 3. Test-Driven Development (TDD)
- Strict Red-Green-Refactor: Write failing behavioral tests before writing implementation code.
- Run tests and verify the assertion failure before writing minimal implementation.
- Run tests via `PYTHONPATH=src pytest` (or `pip install -e .`).

### 4. Parity & Packaging Invariants
- Lifecycle modules in `src/ship/lifecycle/` and `skills/ship/scripts/lifecycle/` maintain 100% byte-for-byte parity.
- Specialist tools in `src/ship/tools/` and `skills/*/scripts/` maintain byte-for-byte parity.
- Always run `python3 scripts/verify/sync_parity.py --check` to ensure zero drift.

### 5. Language Boundaries & Architectural Enforcement
- **TypeScript**: Factory runtime (Lifecycle Engine, state machine, CLI, MCP server, state ledger, and policy evaluator).
- **Python**: Specialist verification only (AST analysis, Python syntax, and Ruff/pytest wrappers). All specialist scripts MUST declare PEP 723 metadata (`dependencies = []`) using stdlib only.
- **Markdown + YAML**: Skill contracts (`SKILL.md`). Portable host interface decoupled from script implementation details.

### 6. Adversarial Code Review
- Adhere strictly to the 12-field finding schema in `skills/review/references/finding_schema.md`.
- Zero unhandled CRITICAL or HIGH defects before delivery.
