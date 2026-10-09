# Host security baseline and rollout approval

**Status:** Integration requirements; organization approval pending.
**Scope:** AgentFlow's local workflow controls plus the host controls required for a pilot.

## Implemented controls and limits

AgentFlow checks lifecycle evidence, design digests, configured capabilities and policy
at its own entry points. MCP mutations are disabled unless a trusted operator sets
`AGENTFLOW_MCP_ALLOW_MUTATIONS=1`. Set `AGENTFLOW_MCP_ROOT` to bind the MCP server to
one consumer workspace. The logical execution rings classify operations; they are
not OS privilege rings or kernel isolation.

Local ledgers, session identities, approval records, and hash-chained events are
writable by sufficiently privileged local processes. They do not authenticate a
human approver, prove an independent reviewer, or prevent a writer from replacing
an entire log. Step observations can be agent-reported. Host-observed fixture traces
have the narrower limits documented in [pilot evaluation guidance](./team_rollout.md#pilot-and-agent-behavior-evaluation).
A sequential Judge pass does not establish organizational separation of duties.

MCP responses, including structured values and error output, are scrubbed for known
secret patterns. Pattern redaction is defense in depth, not guaranteed secret
recognition. Local evidence files and arbitrary host tools are not covered by the
MCP response filter.

## Required host controls

Before enabling mutation or shell execution, the operator must verify:

- Filesystem and process isolation restrict the agent and its subprocesses to the
  intended workspace. AgentFlow's command classifier is not a sandbox; an allowed
  Python program or test runner can itself access files or execute other programs.
- Network egress is restricted by the host to approved destinations. Verify actual
  host behavior; do not infer isolation from a product name or UI setting.
- Provider credentials and production secrets are absent from the agent workspace
  and command environment. Strip sensitive environment variables before launching
  AgentFlow and its test runners. Use scoped, short-lived credentials only through
  an explicitly approved host integration.
- The agent cannot modify authoritative organization policy or forge host approval.
  Approval flags must come from trusted host decisions, never model arguments.
- Human review and protected CI checks remain authoritative for merge and deployment.
  Where maker/checker separation is required, enforce distinct authenticated
  identities outside the local ledger.
- Evidence retention, access control, and redaction are defined. If tamper-resistant
  auditing is required, export events and milestone anchors to an independently
  controlled append-only store. Local hashes alone are insufficient.

These are integration requirements, not claims that every supported host already
implements them. Record the tested host version, model, permissions, and isolation
checks for each approved configuration.

## Organization-owned rollout decision

A named engineering owner and security/platform owner must review the pinned
candidate commit, passing pre-release evaluation artifacts, target host/model
results, unresolved findings, and upgrade/rollback rehearsal. Record the decision
in the organization's approval system with scope and owners. A repository document
or local Judge PASS cannot grant this approval.

Start with the [team pilot scenarios](./team_rollout.md#pilot-and-agent-behavior-evaluation).
Do not expand while data-loss, wrong-change, false-readiness, or isolation failures
remain unresolved. Measure completion, review accuracy, time, and cost on representative
repositories before setting organization-specific acceptance thresholds.
