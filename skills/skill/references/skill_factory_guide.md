# Skill Factory Reference Guide

## 1. Native Claude Skills Architecture

Every skill follows the standardized directory layout:
```text
skills/<skill-name>/
├── SKILL.md            # Primary agent instruction file with YAML frontmatter
├── VERSION             # Single-line SemVer string (e.g. 1.0.0)
├── CHANGELOG.md        # Monotonic revision log
├── scripts/            # Zero-dependency deterministic TypeScript/Node tools
│   └── validate_<name>.ts
├── references/         # In-depth domain manuals, templates, checklists
│   └── <name>_guide.md
├── assets/             # Static files, schemas, diagrams, template JSONs
│   └── manifest.json
└── evals/              # Behavioral regression scenarios
    └── eval_cases.json
```

## 2. Skill × Model × Host Compatibility

Skills specify compatibility targets to allow graceful degradation across runtimes:

### Host Profiles
| Host ID | Platform | Terminal | Filesystem | MCP | Subagents |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `claude_code` | Claude Code CLI | ✅ | ✅ | ✅ | ✅ |
| `antigravity` | Google Antigravity | ✅ | ✅ | ✅ | ✅ |
| `claude_desktop` | Claude Desktop | Via MCP | Via MCP | ✅ | ❌ |
| `cursor` | Cursor IDE | ✅ | ✅ | Partial | ❌ |
| `codex` | OpenAI Assistants / Code Interpreter | ❌ | ✅ | ❌ | ❌ |

### Fallback Strategy
When a host lacks native terminal execution:
1. Fallback to MCP tools (e.g. `ship_spike_run`, `ship_tdd_verify`).
2. If MCP is unavailable, fallback to deterministic assertions in-process.

## 3. Run Cost & Usage Economics

To prevent runaway inference costs, skills track runtime resource consumption:
- `tokens`: input tokens, cached token hits, output tokens.
- `duration_ms`: end-to-end execution latency.
- `tool_calls`: list and count of tool invocations.
- `estimated_cost_usd`: calculated against standard model pricing tables ($/M tokens).
