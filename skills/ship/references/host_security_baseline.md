# Host Runtime Security Baseline & Hardening Specification

**Version:** 1.0.0  
**Status:** Approved for Organization-Wide Rollout  
**Target Systems:** Google Antigravity, Cursor, Claude Desktop, Headless CI Agents

---

## 1. Executive Summary

The **AgentFlow / Ship SDLC Framework** enforces governance policies at the logical application and lifecycle layer:
- Role & Ring isolation (Ring 0 Hypervisor, Ring 1 Governance, Ring 2 Production, Ring 3 Sandboxed).
- Fine-grained capability checks (`CapabilityManager`).
- Maker $\ne$ Checker mechanical separation.
- Cryptographic hash-chaining of action events (`EventLogger` & `ExecutionTrace`).
- Secrets preflight checks, command leakage prevention, and output redaction (`SecretsBroker`).

However, **logical policies cannot replace kernel-level sandboxing, OS process isolation, and physical secret vault containment**. This document outlines the mandatory baseline configuration required from host runtimes hosting AgentFlow agents.

---

## 2. Per-Host Mandatory Configuration

### 2.1 Google Antigravity
1. **Sandbox Mode Enforcement:**
   - Must run with `BypassSandbox: false` (Standard Sandbox Mode) by default.
   - Any tool requiring `BypassSandbox: true` must trigger interactive human authorization.
2. **Path Containment:**
   - Agent read/write paths must strictly resolve within the designated workspace root (`Cwd`).
   - Host must block path traversal (`../`) escaping the workspace boundaries.
3. **Network Containment:**
   - Standard sandbox mode blocks outbound TCP/UDP traffic.
   - Egress must remain restricted unless explicitly approved for whitelisted endpoints (e.g., git remote push).

### 2.2 Cursor & Claude Desktop (MCP Deployments)
1. **MCP Mutation Gate:**
   - The environment variable `AGENTFLOW_MCP_ALLOW_MUTATIONS=1` must only be set by trusted operators for sessions explicitly intended to modify workspace code.
   - Without this variable, all modifying tools (`ship_checkpoint`, `ship_record_turn`, `ship_record_tests`) reject execution.
2. **Workspace Pinning:**
   - Set `AGENTFLOW_MCP_ROOT=/path/to/repo` in MCP configuration to lock the server to a specific workspace and prevent arbitrary directory access.
3. **Command Execution Guards:**
   - Commands must route through the `CapabilityGuard` and `SecretsBroker.inspect_command()`.
   - Blanket shell execution tools (`bash`, `sh`) must never run commands that dump the environment (`env`, `printenv`, `set`).

---

## 3. Secrets Management & Vault Integration

1. **Zero Plaintext Secrets in Working Trees:**
   - All files matching `.env*`, `*.pem`, `*.key`, `id_rsa*`, `secrets.yaml`, and `credentials.json` are classified as **Ring 1 Governance** and excluded from autonomous agent reading by default.
2. **Indirect Credential References:**
   - Agents must only be provided with secret references (e.g. `${env:DEPLOY_TOKEN}` or vault paths `vault:secret/data/ci`) rather than plaintext secrets.
3. **Output Redaction (`SecretsBroker`):**
   - All tool responses and MCP stdout streams must pass through `SecretsBroker.scrub_text()` to redact API keys (`sk-...`, `ghp_...`, `AIzaSy...`), private keys, and authorization headers.
4. **Environment Isolation:**
   - Sensitive environment variables must be stripped before spawning sub-processes for agents (`subprocess.run(env=sanitized_env)`).

---

## 4. Audit Trail & Cryptographic Anchoring

1. **Tamper-Evident Event Log:**
   - All actions, lease claims, and verifications are appended to `.agentflow/events.jsonl` with SHA-256 hash chaining.
2. **Witness Anchoring:**
   - Host environments must invoke `AuditAnchorManager.create_anchor()` upon completing major lifecycle milestones (spec approval, TDD green, delivery).
   - In production CI/CD pipelines, anchor records should be synced to an immutable, append-only store (e.g. S3 Object Lock, Cloud Storage Retention Policy).
3. **Log Rotation:**
   - When event logs exceed 10,000 entries, `AuditAnchorManager.rotate_event_log()` automatically archives the file, embeds its SHA-256 in the filename, and chains the new genesis record to the archive.

---

## 5. Agent Identity & Provenance Verification

1. **Signed Session Tokens:**
   - All agent sessions started via `ProvenanceManager.start_session()` mint an HMAC-signed session token.
   - The token seals `agent_id`, `role`, `ring`, and `change_id`.
2. **Maker $\ne$ Checker Rule:**
   - Verification records must strictly be signed by an agent whose identity differs from the implementing agent (`maker != checker`).
3. **Multi-Agent Leases:**
   - Task execution requires explicit leases with active TTL heartbeats to prevent concurrent file mutations and race conditions.
