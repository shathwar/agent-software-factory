# Outcome evaluation and negative controls

These checks distinguish fixture correctness, reported findings, rendered behavior,
and live-agent adherence. Passing a fixture suite does not establish agent quality.

## Seeded review benchmark

`review_benchmark.py` contains five defects with executable oracles and clean controls:
empty-input arithmetic, expiry-spec alignment, stale writes, retry exhaustion, and
per-item database round trips. Other review stages remain explicitly `unrun`.

Run from the repository root:

```sh
PYTHONPATH=src:tests python3 -m tests.evaluation.review_benchmark list
PYTHONPATH=src:tests python3 -m tests.evaluation.review_benchmark provision empty-average:buggy /tmp/review-subject
```

Give a fresh reviewing agent only the provisioned workspace, the review skill, and
the request to review `subject.py` against `CONTRACT.md`. Do not give it this module,
case name, clean solution, oracle, or adjudication answers. Capture its actual report
outside the subject workspace in the existing strict review JSON format. Record the
skill commit, model, host, trial identifier and actions alongside it. An empty report
is valid only if it has the required schema fields and explicitly covers `subject.py`.

A separate evaluator reads the findings and maps each finding ID to the seeded defect
ID, or `null` for an unsupported finding. Exact source lines are checked mechanically;
semantic equivalence of the reported defect is the evaluator's responsibility.
The adjudication is bound to the report's SHA-256 (UTF-8 JSON serialized with Python
`json.dumps(report, sort_keys=True, allow_nan=False)`). Example adjudication shape:

```json
{
  "evaluator": "independent-evaluator",
  "report_sha256": "replace-with-the-report-sha256",
  "matches": {"FINDING-001": "empty-input-division"}
}
```

```sh
PYTHONPATH=src:tests python3 -m tests.evaluation.review_benchmark score empty-average:buggy /tmp/review-subject /tmp/review-report.json /tmp/adjudication.json
PYTHONPATH=src:tests python3 -m tests.evaluation.review_benchmark summarize /tmp/trial-results/*.json
```

Save each score's JSON output separately, and include all ten cases for a complete
suite. Duplicate detections count as false positives; absent findings count as misses
on seeded cases. Clean controls have no recall denominator (`null`); no findings has
no precision denominator (`null`). Partial suites are inconclusive. Repeat trials in
separate suites; these ten cases are a small development benchmark, not a statistical
estimate of general review performance. Evaluator identity is reported, not authenticated.

## Rendered UX checks

The Python package remains standard-library-only. Browser tests have an isolated,
pinned development dependency in `tests/browser/`:

```sh
cd tests/browser
npm ci
npx playwright install chromium
npm test
```

CI installs Chromium with its OS dependencies in a separate job and
uploads `artifacts/` even on failure. A missing browser or launch error exits nonzero
with `inconclusive`; it is not silently skipped. Locally, `UX_BROWSER_CHANNEL=chrome`
can use an installed Chrome instead; its version is retained in the report.

The fixture exercises empty, loading, populated, partial/stale, error/recovery and
unavailable states. Checks cover disabled/busy controls, hover/pressed feedback,
Tab/Enter recovery while preserving input, visible focus, 4.5:1 opaque-text contrast,
mobile overflow, desktop bounds and touch target size. Five deliberately broken
variants must be caught. Screenshots and Playwright traces record each run; visual
gates use measured layout and style assertions, not screenshot pixel similarity.
Playwright's [browser API](https://playwright.dev/docs/api/class-page) supplies the
rendering, interaction and screenshot capture.

`node evaluate.cjs --fixture /path/to/candidate.html --output /tmp/ux-candidate`
evaluates a candidate implementing the same state-query and selector contract as
`fixture.html`. It does not inject the built-in negative controls into an external
candidate. This is a bounded fixture benchmark, not a whole-application WCAG audit
or evidence that an agent generated a correct UI.

## Rubric adversarial checks

The standard Python suite includes `test_rubric_adversarial.py`:

- Empty artifacts cannot pass any of the nine skill rubrics; an absent source file
  is inconclusive for simplify rather than evidence of a working simple solution.
- Design keyword stuffing, repetition and negation cannot certify architectural
  correctness. A high keyword score is `INCONCLUSIVE`, with `passed=false`.
- Review lint requires the strict report schema; source grounding requires actual
  files and evidence in the cited line range. Without a source root, a plausible
  report is inconclusive. A lint pass does not measure defect recall.
- Eval specs reject boolean isolation/correction claims, missing or overlapping
  development/held-out IDs, duplicate IDs, unpinned judge names, nonbinary labels,
  nonfinite/out-of-range metrics and correction arithmetic inconsistent with its
  inputs. Passing remains spec lint; label quality and sample adequacy need evaluation.

These negative controls prevent known false passes. They are not semantic judges
and cannot prove every rubric is immune to gaming.

## Live agent execution

See [live agent regression](./live_agent_regression.md) for the host-mediated tool loop,
nightly/release workflow, credential setup, retained traces, and measurement limits.
