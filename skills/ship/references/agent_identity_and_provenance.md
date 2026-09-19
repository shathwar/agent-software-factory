# Agent Identity & Provenance: Attributable Principal & Verification Binding Chain

This document establishes the architecture, invariants, and operational models for attributing lifecycle actions to verifiable principals and binding them across the complete execution chain:

$$\text{agent} \longrightarrow \text{session} \longrightarrow \text{change} \longrightarrow \text{task} \longrightarrow \text{lease} \longrightarrow \text{action} \longrightarrow \text{evidence} \longrightarrow \text{verification}$$

---

## 1. Core Philosophy: Attributable Principals & Maker $\neq$ Checker

In multi-agent autonomous software engineering, actions cannot be anonymous or ungrounded.
Every code mutation, test execution, benchmark run, architectural review, and gate transition must answer three foundational questions:

1. **Who performed the action?** (`agent_id`, `role`, `session_id`, `runtime`, `model`, `parent_agent_id`)
2. **What was the exact context and payload?** (SHA-256 canonical digest of inputs and produced evidence)
3. **Who independently verified it?** (Maker $\neq$ Checker separation enforced mechanically)

### The Maker $\neq$ Checker Principle

The agent that authorial code, tests, or claims (**Maker**) cannot be the principal that independently verifies or approves those claims (**Checker** / **Verifier**).
$$\text{agent\_id}_{\text{maker}} \neq \text{agent\_id}_{\text{checker}}$$

If an agent attempts to verify its own evidence, the verification engine raises a `Maker-Checker violation` and rejects gate advancement.

---

## 2. The 8-Stage Provenance Binding Chain

Every lifecycle event forms an immutable link in an 8-stage chain:

```
┌─────────────────┐
│  AgentIdentity  │  Principal definition (ID, Role, Model, Runtime, Parent)
└────────┬────────┘
         │ 1. spawns / enters
         ▼
┌─────────────────┐
│  AgentSession   │  Timeboxed working session (UUID, timestamps, skill version)
└────────┬────────┘
         │ 2. targets
         ▼
┌─────────────────┐
│  ChangePackage  │  Active change scope (e.g. feature-auth, fix-race)
└────────┬────────┘
         │ 3. selects
         ▼
┌─────────────────┐
│    Task ID      │  Discrete task definition (e.g. 1.1, T2) from tasks.md
└────────┬────────┘
         │ 4. coordinates via
         ▼
┌─────────────────┐
│    TaskLease    │  Exclusive logical lock token, TTL expiration, target files
└────────┬────────┘
         │ 5. executes
         ▼
┌─────────────────┐
│ ActionProvenance│  Tamper-evident record with input and evidence digests
└────────┬────────┘
         │ 6. produces
         ▼
┌─────────────────┐
│    Evidence     │  Test receipts, diff analysis, coverage, review findings
└────────┬────────┘
         │ 7. subjected to
         ▼
┌─────────────────┐
│  Verification   │  Independent verification by distinct Verifier principal
└─────────────────┘
```

---

## 3. Domain Models

### AgentRole Enum
- `ARCHITECT`: System design, ADR authoring, architecture review.
- `TECH_LEAD`: Plan approvals, risk assessment, gate overrides.
- `MAKER`: Test-driven implementation, bug fixing, refactoring.
- `CHECKER`: Code inspection, style audit, test validation.
- `VERIFIER`: Independent out-of-band test harness executor.
- `REMEDIATOR`: Targeted failure remediation agent.
- `SUPERVISOR`: Lifecycle coordinator, turn advancement monitor.
- `COORDINATOR`: Multi-agent lease broker, task dispatcher.
- `SPECIALIST`: Focused tooling runner (benchmark spike, mutation auditor).

### AgentIdentity
```python
@dataclass
class AgentIdentity:
    agent_id: str                   # Unique principal identifier (e.g. "agent-tdd-worker-1")
    role: str                       # AgentRole enum value
    runtime: str = "antigravity"    # Execution runtime (antigravity, cli, python-sdk)
    model: str = "unknown"          # LLM identifier (gemini-1.5-pro, claude-3-5-sonnet, etc.)
    parent_agent_id: Optional[str]  # Delegating parent agent ID if spawned as subagent
    created_at: str                 # ISO 8601 UTC timestamp
    metadata: Dict[str, Any]        # Extensible context tags
```

### AgentSession
```python
@dataclass
class AgentSession:
    session_id: str                 # Unique session token (e.g. "sess-a1b2c3d4e5f6")
    agent_id: str                   # Principal agent identity
    change_id: str                  # Target change package
    role: str                       # Active role
    started_at: str                 # ISO 8601 UTC timestamp
    ended_at: Optional[str]         # Closure timestamp
    status: str = "ACTIVE"          # ACTIVE, COMPLETED, FAILED, CANCELLED
    agentflow_version: str          # Suite version ("1.0.0")
    skill: str                      # Active skill context (e.g. "tdd")
    skill_version: str              # Skill revision
    runtime: str                    # Host runtime
    model: str                      # Model backing the session
    parent_session_id: Optional[str]# Parent session if nested
    metadata: Dict[str, Any]
```

### ActionProvenance
```python
@dataclass
class ActionProvenance:
    action_id: str                  # Unique action token ("act-...")
    action_name: str                # e.g. "claim_lease", "execute_tests", "record_finding"
    agent_id: str                   # Attributable principal ID
    session_id: str                 # Active session ID
    change_id: str                  # Target change ID
    role: str                       # Agent role
    timestamp: str                  # ISO 8601 UTC timestamp
    task_id: Optional[str]          # Bound task
    lease_token: Optional[str]      # Active lease token
    runtime: str                    # Host runtime
    model: str                      # LLM model
    skill: str                      # Skill
    skill_version: str              # Skill version
    agentflow_version: str          # Suite version
    parent_agent_id: Optional[str]  # Delegating principal
    inputs_digest: str              # SHA-256 of canonical inputs
    evidence_digest: str            # SHA-256 of canonical evidence
    metadata: Dict[str, Any]
```

---

## 4. Cryptographic Tamper-Evidence

All arbitrary inputs and evidence payloads are hashed deterministically into canonical SHA-256 digests:
```python
def compute_payload_digest(payload: Any) -> str:
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
```
This guarantees that evidence cannot be silently mutated after generation.
Any alteration to test logs, review findings, or task deliverables immediately invalidates the provenance link.

---

## 5. Ledger Storage Architecture

Identity and provenance data are persisted directly in `.agentflow/ledger.json` under the target change package, protected by filesystem-level advisory locks (`fcntl.flock`):

```json
{
  "changes": {
    "feature-auth": {
      "provenance": {
        "identities": {
          "worker-1": {
            "agent_id": "worker-1",
            "role": "MAKER",
            "runtime": "antigravity",
            "model": "gemini-1.5-pro"
          }
        },
        "sessions": {
          "sess-93a8f10b2c": {
            "session_id": "sess-93a8f10b2c",
            "agent_id": "worker-1",
            "status": "ACTIVE",
            "started_at": "2026-09-19T10:00:00Z"
          }
        },
        "actions": [
          {
            "action_id": "act-1748cb921f",
            "action_name": "claim_task",
            "agent_id": "worker-1",
            "session_id": "sess-93a8f10b2c",
            "task_id": "1.1",
            "inputs_digest": "sha256:e3b0c44298...",
            "evidence_digest": "sha256:8f2a1b9c..."
          }
        ]
      }
    }
  }
}
```

---

## 6. Command-Line Interface

### Managing Agent Identities
```bash
# Register an agent principal
agentflow identity register worker-tdd --role maker --model gemini-1.5-pro --runtime antigravity

# List registered identities for the active change
agentflow identity list
```

### Managing Agent Sessions
```bash
# Start an active working session
agentflow session start worker-tdd --role maker --model gemini-1.5-pro --skill tdd

# List sessions
agentflow session list --active

# Close an agent session
agentflow session end sess-a1b2c3d4e5f6 --status COMPLETED
```

### Coordinating Tasks with Provenance
```bash
# Claim a task lease bound to an active session and model
agentflow lease claim 1.1 --owner worker-tdd --session sess-a1b2c3d4e5f6 --role MAKER --model gemini-1.5-pro

# Release task upon completion
agentflow lease release 1.1 --token <lease_token> --completed --session sess-a1b2c3d4e5f6
```

---

## 7. Zero-Dependency Invariant

This subsystem is implemented with **zero third-party dependencies**. It strictly uses Python standard library modules:
- `uuid` (unique identifier generation)
- `hashlib` (SHA-256 cryptographic digests)
- `datetime` (UTC ISO 8601 timestamps)
- `json` (canonical JSON serialization)
- `dataclasses` (typed data modeling)
- `pathlib` (path manipulation)
- `fcntl` (process-safe ledger locks)
