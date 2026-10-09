# Capability-Based Permissions & The Execution Ring Model

This document describes AgentFlow's local capability policy evaluator and target classifications.

**Enforcement boundary:** `evaluate_access` returns ALLOW/DENY and writes an audit record.
It does not intercept filesystem, shell, CLI, MCP, or network operations. A trusted
host must enforce the decision at execution time and protect its policy store from
untrusted writers. Local identities and approval references are supplied by callers;
they are not authenticated identities. The ledger is mutable by the local user.
Adversarial fixtures test policy decisions, not containment of malicious code.

MCP mutation and shell tools require an explicit server-environment opt-in,
`AGENTFLOW_MCP_ALLOW_MUTATIONS=1`. That grants a trusted client access to those tools;
the command execution adapter also requires an `agent_id`, operation, and scoped target
and calls the host-side `CapabilityGuard` before starting a process. Use host permissions
and OS sandboxing for containment beyond this policy check.

Provider integrations should use `ExternalActionAdapter`: inject the SDK call through
`network`, `secret`, `cloud`, or `github`. The adapter evaluates the scoped capability
before invoking the callback, so denied actions never reach the provider implementation.

---

## 1. Architectural Motivation: From RBAC to OCAP

Traditional role-based access control (RBAC) assigns broad privileges based on static roles:
> *"Agent X has role MAKER, so Agent X is allowed to write all files in Ring 2."*

In autonomous multi-agent environments, this coarse model leaves severe vulnerabilities:
- **Blast radius ambiguity**: A worker agent leased to implement an authentication fix could accidentally or maliciously modify database migration scripts or payment gateways.
- **Temporal leakage**: An agent whose task lease expired or was handed off might still issue mutations.
- **Cross-task pollution**: Multiple agents working concurrently in the same change could overwrite each other's target files without mechanical containment.

### The OCAP Paradigm
AgentFlow evolves the security model into a fine-grained, verifiable capability grant:
> *"This agent (`agent_id`), in this session (`session_id`), for this task (`task_id`), currently holds this capability (`operation` on `target`), expiring at `expires_at` with authorization `approval_ref`."*

---

## 2. The 4-Ring Privilege Lattice

Blast radius and asset criticality are organized into four execution rings:

```text
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ Ring 0: Hypervisor & Ledger (Policy-protected)                                │
 │ • .agentflow/ledger.json, state.json, checkpoints/, refs/ship/*         │
 │ • Default Access: READ allowed; WRITE/DELETE/GIT STRICTLY RESTRICTED.   │
 │ • Requires: Explicit hypervisor/system or human authorization ref.      │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ Ring 1: Architecture & Governance (Design-Gate Locked)                  │
 │ • .agentflow.json, ARCHITECTURAL_INVARIANTS.md, ADRs, specs/**          │
 │ • Default Access: READ allowed; WRITE/DELETE locked during TDD.         │
 │ • Requires: Approved ADR or Design Gate authorization ref.              │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ Ring 2: Production Code & Tests (TDD / Ship Dev)                        │
 │ • Application source (src/**), unit tests (tests/**), build configs     │
 │ • Default Access: Scoped WRITE/DELETE strictly bound to TaskLease.      │
 │ • Requires: Active capability grant AND valid unexpired TaskLease.      │
 ├─────────────────────────────────────────────────────────────────────────┤
 │ Ring 3: Disposable Workspace & Scratch (Host-isolated)                      │
 │ • .scratch/**, scratch/**, build/**, dist/**, caches           │
 │ • Default Access: Disposable; broad WRITE/DELETE within sandbox targets.│
 └─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. The 6-Stage Access Enforcement Chain

Each explicit capability check evaluates the following policy stages; execution is a separate host responsibility:

```
Agent Action Request (agent_id, operation, target, task_id, session_id, lease_token)
  │
  ▼ Stage 1: Identity Gate
Is the agent registered as an attributable principal in the ledger?
  ├─► NO  ──► DENY (UNKNOWN_PRINCIPAL)
  └─► YES
  │
  ▼ Stage 2: Ring Classification
Classify target resource into Ring 0, Ring 1, Ring 2, or Ring 3.
  │
  ▼ Stage 3: Ring 0 Policy Gate
Is operation modifying Ring 0 (ledger, internal state, git notes)?
  ├─► YES & No hypervisor approval ──► DENY (RING_0_RESTRICTED)
  └─► PASS
  │
  ▼ Stage 4: Capability Matching Gate
Does the agent hold an unrevoked, unexpired capability matching (operation, target, task, session)?
  ├─► NO matching grant ──► DENY (NO_CAPABILITY)
  ├─► Grant is expired  ──► DENY (CAPABILITY_EXPIRED)
  └─► MATCHED
  │
  ▼ Stage 5: Ring 1 Governance Gate
Is operation modifying Ring 1 (invariants, gate config, ADRs)?
  ├─► YES & No approved ADR ref ──► DENY (RING_1_UNAUTHORIZED)
  └─► PASS
  │
  ▼ Stage 6: Ring 2 Lease Gate
Is operation mutating Ring 2 production code or tests?
  ├─► No active task lease found      ──► DENY (LEASE_REQUIRED)
  ├─► Lease owned by another agent   ──► DENY (LEASE_OWNER_MISMATCH)
  ├─► Lease token mismatch           ──► DENY (LEASE_TOKEN_INVALID)
  ├─► Lease has expired              ──► DENY (LEASE_EXPIRED)
  ├─► Target outside leased files    ──► DENY (LEASE_FILE_MISMATCH)
  └─► PASS
  │
  ▼
ALLOW (Security Decision logged to local ledger audit trail)
```

---

## 4. Capability Operations

| Operation | Description | Target Examples |
|---|---|---|
| `READ` | Inspection, linting, reading file contents | `src/**/*.py`, `tests/**` |
| `WRITE` | Creating or modifying file contents | `src/auth/token.py` |
| `DELETE` | Purging disposable scratch or artifacts | `scratch/**`, `build/**` |
| `EXECUTE` | Subprocess command execution | `cmd:pytest*`, `cmd:git diff` |
| `GIT` | Manipulating git branches, commits, or refs | `ref:refs/heads/*` |
| `NETWORK` | Out-of-band network communication | `net:api.github.com` |
| `NETWORK_READ` | Read-only outbound network communication | `https://pypi.org/*` |
| `NETWORK_WRITE` | Outbound network mutation | `https://api.github.com/repos/org/repo/*` |
| `SECRET_READ` | Reading environment variables or vault keys | `secret:JWT_SECRET` |
| `CLOUD_MUTATE` | Mutating a scoped cloud resource | `aws:s3:::bucket/*` |
| `GITHUB_WRITE` | Mutating GitHub state | `github:pr:*` |

---

## 5. CLI Usage & Operations

### Granting a Capability
```bash
# Grant write access to a specific module bound to Task 1.1 for 15 minutes
agentflow capability grant worker-tdd \
  --op WRITE \
  --target "src/auth/*.py" \
  --task "1.1" \
  --ttl 900 \
  --approval "lease:tok-9b8a7c"
```

### Checking Access Before Action
```bash
# Programmatic/hook access check
agentflow capability check worker-tdd \
  --op WRITE \
  --target "src/auth/login.py" \
  --task "1.1" \
  --token "tok-9b8a7c"
```

### Listing Active Capabilities
```bash
agentflow capability list --active
```

### Revoking a Capability
```bash
agentflow capability revoke cap-a1b2c3d4e5f6 --reason "Task completed early"
```

---

## 6. Zero External Dependencies

The capability system is implemented purely with Python standard library primitives:
- `dataclasses` & `enum` for typed models
- `fnmatch` & `pathlib` for secure pattern matching
- `datetime` & `timezone` for UTC timestamping
- `uuid` for cryptographically random capability tokens
- `fcntl` for thread/process-safe ledger locks
