# Claude Skill Frontmatter Specification

## Specification Overview

Claude Code and the Agent Skills standard parse YAML frontmatter at the beginning of `SKILL.md` to index, route, sandbox, and execute skills.

```text
---
name: <identifier>
description: <description>
model: <model-identifier>
effort: <effort-level>
allowed-tools:
  - <tool-1>
  - <tool-2>
context: <fork|inherit>
when_to_use: <trigger-instructions>
---
```

---

## Field Reference

### `name` (Required)
- **Type**: String (kebab-case recommended)
- **Example**: `code-review`, `db-migrate`, `claude`
- **Purpose**: Unique identifier for the skill.

### `description` (Required)
- **Type**: String
- **Example**: `Review code changes for correctness, safety, and performance. Trigger with "/review" or "review".`
- **Purpose**: Used by the agent router to determine when this skill should be auto-invoked. Should include concise purpose and primary trigger phrases.

### `model` (Optional)
- **Type**: String
- **Allowed Values**: `claude-3-7-sonnet`, `claude-3-5-sonnet`, `claude-3-5-haiku`, `claude-3-opus`, or aliases (`sonnet`, `haiku`, `opus`)
- **Purpose**: Overrides the active session model to run this skill on a specific model tier.

### `effort` (Optional)
- **Type**: String or Integer
- **Allowed Values**: `low`, `medium`, `high`, `max` (or integer 1–10)
- **Purpose**: Configures the reasoning depth and thinking budget allocated to the model when executing this skill.

### `allowed-tools` (Optional)
- **Type**: List of Strings
- **Examples**:
  ```yaml
  allowed-tools:
    - Read
    - Glob
    - Grep
  ```
- **Purpose**: Restricts the tools the agent is permitted to call during skill execution. Pre-approves safe actions and blocks unauthorized tools.

### `context: fork` (Optional)
- **Type**: String (`fork`)
- **Purpose**: Runs the skill inside an isolated sub-agent context. Prevents large outputs, log spew, or transient state from polluting the user's primary conversation.

### `when_to_use` (Optional)
- **Type**: String
- **Purpose**: Supplementary guidance appended to the model's system prompt specifying precise behavioral trigger conditions.

---

## Complete Examples

### Example 1: Read-Only Audit Skill
```yaml
---
name: sec-audit
description: Security and vulnerability scanner for code repositories.
model: claude-3-7-sonnet
effort: high
allowed-tools:
  - Read
  - Glob
  - Grep
---
```

### Example 2: Fast Mechanical Formatter
```yaml
---
name: code-formatter
description: Run automated code formatters and fix syntax formatting issues.
model: claude-3-5-haiku
effort: low
allowed-tools:
  - Read
  - Edit
  - Bash
---
```
