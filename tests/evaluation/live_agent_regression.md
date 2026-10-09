# Live agent regression and trace capture

`python3 scripts/test/run_live_regression.py --output live-agent-artifacts` runs
actual Anthropic model tool calls through a host-owned dispatcher. It has no stub
fallback. This suite is distinct from the legacy `run_agent_regression.py` response
harness, whose `live` mode only captures `agy` text output.

## Setup and scheduling

Set `ANTHROPIC_API_KEY` and `AGENT_REGRESSION_MODEL` in the host environment. Select
an available, organization-approved model ID explicitly; there is no moving default.
Build the command executor before running:

```sh
docker build -t agentflow-live:local -f tests/agent_harness/Dockerfile .
python3 scripts/test/run_live_regression.py --output live-agent-artifacts
```

The workflow `.github/workflows/live-agent-regression.yml` runs at 02:23 UTC nightly,
on `release.published`, and on manual dispatch. It never runs on pull requests.
Configure the GitHub environment `live-agent-regression` with the secret
`ANTHROPIC_API_KEY` and variable `AGENT_REGRESSION_MODEL`. Configure environment
reviewers/branch restrictions as appropriate for your release process. Missing
configuration fails the job rather than skipping or substituting canned responses.
A published-release run is post-publication validation, not a pre-publication gate.
Before publishing, run the **Release candidate** workflow on the exact candidate commit.
It runs deterministic checks and calls the live workflow; its `candidate-gate` job
requires both to succeed. The live job validates the complete case set, requested
model, clean checkout, and candidate SHA with `scripts/verify/live_release.py`.
Missing credentials, missing Ship observations, or stale reports fail closed.

A publishing workflow must call `release-candidate.yml` and depend on its success.
This repository does not publish releases automatically; maintainers can still bypass
checks by publishing manually unless the organization restricts that permission.
Configure branch/release permissions and environment approval outside this repository.
The included transport measures only `anthropic-tool-loop`; organization approval
also requires recorded trials on every intended host/model configuration.

The host HTTP client follows the [Messages client-tool protocol](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls).
Only synthetic fixture files and selected skill instructions/references are given
to the model. Commands run in a fresh Docker container with network disabled,
read-only root filesystem, dropped capabilities, resource limits, and only the
fixture mounted. The image embeds the candidate runtime and skill distribution at build time.
Provider credentials, the host checkout, Docker socket, and evidence directory
are never mounted or passed into command environments. The inspected
image ID is recorded and used for execution. Local execution is only a test seam;
the live CLI always uses Docker. Keep Docker and the host runtime patched.

## Evidence and execution order

Each case retains:

- `metadata.json`: suite commit, fixture/skill hashes, requested model, executor
  image ID, turn budget and capture scope. The suite report also records whether
  the checkout was dirty.
- `model-*.json`, `messages.json`: provider responses (including model and usage),
  actual tool requests, results, and conversation history.
- `trace.jsonl`: host-generated ordered hash-chained events: calls, results,
  source/test edits with before/after hashes and diffs, commands and parsed tests.
- `command-*.json`: complete captured stdout/stderr, argv, working directory,
  duration, and real exit code. Timeouts have nonzero status.
- `acceptance.json`: a separate host-owned acceptance test command for implementation
  scenarios, excluded from the agent's red/green evidence.
- `result.json` and suite `report.json`: individual checks and failure details.

Tools execute serially, including multiple calls in one model response. Evidence is
saved before dispatch and after each tool. Exceptions, turn exhaustion, missing tools,
and missing positive test counts cannot become successful live runs. Partial traces
survive model/command failures and are uploaded by CI even when the suite fails.
Artifacts are retained for 14 days; longer retention is an organization decision.

Snapshots observe file state at tool boundaries. They do not observe edits and
reverts within a subprocess, ignored runtime/cache/Git files, or the internal order
of multiple edits in a process. Command-induced edits are conservatively recorded
before test results, so ambiguous order cannot establish red-before-edit evidence.
Symlinks are never dereferenced during host evidence collection and are rejected
by outcome checks. Hash chaining detects later changes, not a malicious host or
independent identity. Agent-written test output is not an unforgeable attestation.

## Coverage and limits

The bounded suite covers TDD implementation, debug repair, read-only review of an
empty-input arithmetic defect, and a Ship lifecycle trial. TDD/debug require observed test edits,
a failing test before the first production edit, a passing test after the final
production edit, preserved unrelated work, and separate functional acceptance tests.
Review requires actual source/contract reads, no edits, and a relevant defect report;
its report check is a text predicate, not an independent semantic review judge.

The Ship trial starts without a design package. The model compiles ADR/OpenSpec
artifacts and stops for a synthetic host approval. The host records the design digest
and clears conversation context; the model must resume from the workspace. After
a successful delivery status check, the host changes source, records the resulting
stale-evidence rejection, and requires fresh test/review evidence before archiving.
Approval timing, preserved user work, actual execution receipts, runtime archive, and
a separate functional acceptance command are checked. The model cannot write host
configuration or ledger receipts using `write_file`; arbitrary test code still runs
only inside the isolated executor. Local evidence is not a security attestation.

These checks cover one bounded end-to-end scenario, not every Ship branch, supported
language, or general agent reliability. Changed requirements, repair-limit exhaustion,
wrong-change selection, and archive crash recovery have deterministic regression
coverage and still require representative live org trials before broad rollout. A pass never means all causal invariants are proven.
The normal PR suite tests this harness using deterministic model-response fixtures
and real local subprocesses; those tests are explicitly not live-model trials.
