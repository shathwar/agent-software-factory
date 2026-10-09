# External SDD skill integration

Ship consumes a small JSON handoff from an external specification-driven development
skill. The host invokes that skill; Ship does not execute command strings, import
provider plugins, or duplicate its templates. One skill may implement all four
operations, or each operation may name a separate installed skill.

## Configuration

In the consumer project's `.agentflow.json`:

```json
{
  "version": 1,
  "sdd": {
    "provider": "your-provider",
    "snapshot": ".agentflow/sdd.json",
    "skills": {
      "prepare": "your-sdd-skill",
      "inspect": "your-sdd-skill",
      "verify": "your-sdd-skill",
      "finalize": "your-sdd-skill"
    }
  }
}
```

The provider label identifies the external SDD provider (such as `openspec`).
Skill values identify installed skills or their readable SKILL.md locations, not
executable shell commands. All four operations are required.
Configure the provider in repository `.agentflow.json`; per-command config overrides
cannot select a different provider. Pin external skill versions using the team's
normal distribution mechanism. Ship's doctor does not certify their availability
or behavior: the host must resolve and read them before running their operations.

| Operation | Responsibility |
|---|---|
| prepare | Create/update requirements, design decisions, and implementation task scope. |
| inspect | Read native artifacts/status and refresh the handoff without changing specification semantics. |
| verify | Compare implementation to the approved specification and retain evidenced findings. |
| finalize | Reconcile/archive using native conventions, with a durable completion report. |

The adapter is an instruction mapping plus the JSON handoff below, not a second
specification system. The host translates observed provider output when the skill
does not emit this format itself. Refresh after every native task/artifact change
and on resume; never infer state from a stale handoff. Missing provider capabilities
must be disclosed and resolved rather than replaced by an invented passing report.

## Handoff v1

Write the configured snapshot atomically after a successful inspection:

```json
{
  "version": 1,
  "provider": "your-provider",
  "changes": [{
    "change": "empty-input",
    "artifacts": [
      {"id": "requirements", "path": "planning/requirements.txt"},
      {"id": "tasks", "path": "planning/work.md", "normalization": "markdown-checkboxes"}
    ],
    "tasks": [
      {"id": "one", "description": "Return zero for empty input", "completed": false}
    ]
  }]
}
```

Paths are repository-relative regular files; traversal and symlinks are rejected.
List **all** approved requirements, design decisions, and task-scope artifacts,
including repository ADRs if applicable. Artifact and task IDs must be unique
within their respective lists. Native provider layout is unrestricted.

Ship hashes actual artifact bytes, logical IDs, normalization choices, ordered task
scope, and provider configuration. Task completion alone does not change scope.
For Markdown task files, `markdown-checkboxes` ignores only checkbox completion
markers; it does not ignore task wording. Other artifact formats are hashed as-is;
if they embed changing status, the adapter must expose a stable native scope
artifact or accept reapproval when that artifact changes. Do not omit scope to
avoid an approval check.

Artifact paths may change during native archival while logical IDs and content
remain stable. Keep the change in the handoff after finalization so Ship can
reconcile interrupted delivery. Empty artifacts cannot be approved and empty tasks
cannot advance to implementation. Unknown/malformed handoffs fail closed; an absent
handoff allows initial preparation.

After provider verification, add to the change:

```json
"verification": {
  "verdict": "PASS",
  "report": ".agentflow/provider-verification.md",
  "design_fingerprint": "<Ship --design-fingerprint output>",
  "tree_fingerprint": "<Ship inspection git.working_tree_fingerprint>"
}
```

`FAIL` and `INCONCLUSIVE` block delivery. The report must exist and both fingerprints
must remain current. Store diagnostic reports under `.agentflow/` to avoid changing
the reviewed source snapshot merely by writing evidence. This is a provider's local
verification record, not proof that an independent human reviewed the specification.
Ship separately enforces execution receipts and Judge review.

After native finalization, add `"finalization": ".agentflow/provider-finalization.md"`.
The file records the selected change, resulting locations, and what the provider
completed. Refresh artifact paths, rerun verification/review/tests if the tree
changed, then call Ship `--archive <id>` to record delivery. This final call is
idempotent and does not mutate native artifacts. `--force` cannot bypass external
SDD delivery gates. Preserve interrupted provider work and use its recovery flow;
Ship delegates artifact lifecycle recovery to the configured provider.

## Initial provider: OpenSpec

Use the native skills installed by the team's pinned OpenSpec distribution:

```json
"sdd": {
  "provider": "openspec",
  "skills": {
    "prepare": "openspec-propose",
    "inspect": "openspec-propose",
    "verify": "openspec-verify-change",
    "finalize": "openspec-archive-change"
  }
}
```

Read [the OpenSpec adapter](./sdd_openspec.md) for operation-specific use. Other
providers need only the same four responsibilities and handoff; no core code change
or OpenSpec-compatible directory structure is required.

## Workspace configuration

Projects use external SDD configuration (defaulting to `provider: openspec`).
Inspect through the configured provider, populate the handoff, then review and approve
the specification digest. Never copy an old approval onto a modified digest.
