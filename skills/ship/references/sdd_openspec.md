# OpenSpec SDD adapter

OpenSpec is an external dependency. Use its installed, pinned skill instructions
and CLI output as authority for artifact layout and workflow. See upstream
[supported skills](https://github.com/Fission-AI/OpenSpec/blob/main/docs/supported-tools.md).
Ensure the distribution includes verification; not every installation profile does.

- **Prepare:** invoke `openspec-propose` to produce the native change package. Feed
  architectural decisions into its design artifact; use separate ADRs only when
  repository conventions require them.
- **Inspect:** read the inspection/status instructions from `openspec-propose`, but
  execute only its read-only status and artifact-discovery steps. Do not rerun
  proposal creation on resume. Read the selected change's native tasks and export
  the [handoff](./sdd.md#handoff-v1), including every scope artifact discovered by
  OpenSpec. Map native task IDs/descriptions/completion; use checkbox normalization
  for Markdown task artifacts. Resolve paths from actual provider output.
- **Verify:** invoke `openspec-verify-change`, preserve requirement-level findings,
  and translate the report into PASS/FAIL/INCONCLUSIVE with Ship's current design
  and tree fingerprints. A completed task list alone is not verification.
- **Finalize:** after Ship is ready, invoke `openspec-archive-change`; let that
  workflow perform its native reconciliation/archival. Refresh artifact locations
  from its result, preserve logical IDs, and retain a finalization report before
  recording Ship delivery. If native archive changes approved content rather than
  just locations, surface the scope change and obtain renewed approval.

The adapter must not invoke Ship's legacy spec merger or impose its archive paths.
Do not install or upgrade OpenSpec implicitly while resuming an approved change.
