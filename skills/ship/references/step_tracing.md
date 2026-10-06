# Step observations

Use `agentflow steps` (or `python3 "$SKILLS_DIR/ship/scripts/trace_steps.py"` with the same arguments) from the consumer repository. This records observations in `.agentflow/events.jsonl`. It does not alter delivery readiness or independently grade the agent.

## Capture a task

```sh
agentflow steps catalog --skill tdd
agentflow steps begin --skill tdd --skill simplify --change feature-login --task email-validation
# Retain the returned run_id. Before executing the red step:
agentflow steps started <run_id> tdd.red
# Retain the returned attempt_id. Save the actual runner output to a receipt file.
agentflow steps completed <run_id> tdd.red --attempt <attempt_id> --evidence .agentflow/receipts/red.txt
agentflow steps skipped <run_id> tdd.characterize --reason 'New implementation; no existing behavior to characterize'
agentflow steps report <run_id>
```

Use a separate run for each atomic task/invocation; include only participating skills. The catalog gives each step's applicability and expected evidence. Repeated interview rounds, review passes, or red/green cycles create new attempts for the same step. Finish the active attempt before starting another. The run snapshots skill versions and source digests, so an upgrade cannot relabel historical observations. Supply `--agent`, `--session`, and `--model` when known; omitted metadata remains null. These identities are caller-reported, not authenticated.

Record `started` before doing the step, then `completed` with one or more repository-relative evidence files. Evidence should address the catalog's expectation: actual terminal receipts, source references, decisions, or inspection artifacts. A filename and hash establish which bytes were submitted; they do not establish that those bytes prove the claimed behavior. Never fabricate a receipt or retroactively start steps to imply capture happened earlier. Keep receipt files free of credentials and sensitive raw payloads.

Use `failed --attempt <attempt_id> --reason '...'` when a step fails. Use `skipped --reason '...'` for a deliberately inapplicable step; include the active attempt ID if it was already started. After a crash, inspect the report, close an abandoned attempt as failed with the interruption reason, then start a new attempt. Do not replace failure with success or erase earlier attempts. The event listing (`agentflow events list --type SKILL_RUN_STARTED --json`) can recover lost run IDs.

## Report semantics

- `unobserved`: no record exists. This is not a pass or a justified skip.
- `started`: an attempt has no terminal result, including interrupted work.
- `completed`: reported completion backed by file references and hashes, not independent verification.
- `failed`: reported failure with a reason; preserved when a later attempt succeeds.
- `skipped`: deliberate omission with a reason; never counted as completed.

The report includes every catalog step, all attempts, recording timestamps, duration, evidence integrity, and counts by latest status. `fully_observed` means every step has a terminal observation, including failures/skips; it does not mean success. Missing, changed, and unsafe evidence remains visible without rewriting history. CLI exit zero means the report was read successfully, not that the run passed. An invalid event hash chain blocks reporting and further trace writes.

MCP exposes `ship_steps_begin`, `ship_steps_record`, and `ship_steps_report`. Begin/record follow the existing trusted-host mutation switch; report is available without that switch. This is local, caller-reported telemetry. Host-side capture of tool actions and independent behavioral evaluation remain separate work.

If the tracing runtime is unavailable, continue the authorized skill workflow and state that step capture was unavailable. Never label an uncaptured workflow fully observed. Read-only modes or explicit no-write requests take precedence over local telemetry persistence; report capture unavailable instead of writing into the reviewed project.

## Maintaining the catalog

The canonical IDs and evidence expectations live in `tests/skill_coverage.json`. After reviewing a skill change, update its coverage source digest and run `python3 scripts/verify/build_step_catalog.py`. This generates a Python catalog shipped with both the package and standalone lifecycle scripts; consumer projects do not need the source repository or its test files. `--check` and the test suite reject catalog drift. Do not remove behavioral coverage gaps merely because a step can now be recorded.
