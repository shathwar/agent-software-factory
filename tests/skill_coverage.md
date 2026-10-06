# Skill step coverage inventory

[skill_coverage.json](./skill_coverage.json) maps the nine repository skills to
required workflow steps, including conditional branches and every numbered turn
contract. It records what evidence each step should produce, which existing
validators and evaluation cases can inspect parts of that evidence, and the gaps
that remain. Stable IDs such as `tdd.red` can be reused by future step telemetry.

This is a reviewed inventory, not an executed evaluation report. A validator or
test reference does not prove that an agent called it, that evidence was captured,
or that the step succeeded. No automated real-agent evaluator is registered in
schema version 1. All steps still have gaps, including the shared lack of mandatory
correlated step-start/result telemetry.

## Inspect the inventory

Run from the repository root:

```bash
make coverage
python3 scripts/check_skill_coverage.py --skill tdd --gaps
python3 scripts/check_skill_coverage.py --json
```

The summary counts **steps with mapped checks**, not tests passed or a coverage
percentage. A step may have several checks and appear in several columns.
`--skill` filters the report, while validation still checks the entire inventory.
`--json` includes the step mappings and an `agent_evaluation` field:
`manual_only` means a written manual acceptance case exists; `missing` means no
agent case is registered. Neither value claims an executed result.

Exit `0` means the inventory is structurally valid and its references are current.
Exit `1` means malformed data, stale sources, missing references, unmapped skills
or contracts, or an invalid skill selection. Known gaps do not fail this check.
Both `make check` and the full CI test entry point validate the inventory.

## Manifest contract

| Field | Meaning |
|---|---|
| `schema_version` | Version of the inventory contract; currently `1`. |
| `scope`, `limitations` | Explicit scope and limits on interpreting coverage. |
| `source_digests` | SHA-256 of each skill definition and referenced requirement document at the last coverage review. |
| `validators` | Reusable validator IDs, exact Python symbols, and the limited claim each validator supports. |
| `eval_cases` | Reusable case IDs, exact test symbols or documented acceptance-case selectors, case kind, and scope. |
| `skills` | Every directory containing a root `SKILL.md`, with ordered step mappings. |

Each step contains:

- `id`, `title`: stable `skill.step` identity and its action.
- `requirement`: repository-relative source and a literal text selector.
- `applies_when`: workflow or condition in which the step is required. This is a
  human-readable condition, not an executable routing rule.
- `turn_contracts`: numbered contract items supported by this step. Several steps
  may support one item; all numbered items must be mapped.
- `expected_evidence`: required artifacts or receipts. These are requirements,
  not assertions that automatic capture exists.
- `validators`, `eval_cases`: IDs in the registries; empty lists explicitly mean
  no mapped check of that kind.
- `gaps`: known missing checks or limits of the existing checks. Version 1 requires
  a nonempty gap list; removing the last gap requires revisiting the coverage
  contract and supporting a stronger claim with real execution evidence.

Evaluation kinds deliberately distinguish different evidence:

| Kind | What it establishes |
|---|---|
| `tool_unit` | Behavior of a verification tool or helper on its test inputs. |
| `lifecycle_integration` | Engine/API behavior, usually with synthetic agent evidence. |
| `static_fixture` | Source-pattern checks on fixtures, including the simulated UX pipelines. |
| `manual_agent` | A written real-agent acceptance scenario, with no automated run result implied. |

The UX fixture evaluator is registered as `static_fixture`. Its simulated fixes,
regressions, token counts, and time estimates are not measured agent outcomes or
rendered-browser verification. The manual cases in
[skill_evaluations.md](./skill_evaluations.md) likewise remain manual until an
independent agent runner and grading evidence exist.

## Maintain the mappings

1. After editing a skill or a referenced requirement document, review its entire
   step list, conditional modes, hard constraints, and turn contracts. Update the
   requirement selectors, evidence expectations, mappings, and gaps as needed.
   The checklist guard detects unmapped numbered contracts; semantic completeness
   of prose and supplemental references still needs human review.
2. Only after that review, update the affected `source_digests` values to the
   SHA-256 of the current file bytes. Do not refresh hashes just to silence CI.
3. When adding a validator or case, identify an existing symbol rather than a
   whole test file, and describe exactly what it proves. References are inspected
   with AST/text checks, never imported or executed by the inventory checker.
4. A renamed or deleted symbol, removed acceptance-case selector, new skill, or
   stale skill/document digest fails validation. Changes inside an existing
   validator/test symbol still require reviewing its stated scope; symbol
   existence alone does not prove the mapping remains semantically accurate.
5. Run the inventory checker and its regression tests:

```bash
python3 scripts/check_skill_coverage.py
PYTHONPATH=src:tests python3 -m unittest tests.test_skill_coverage -v
```

To introduce automated agent cases later, extend the schema and checker with
explicit runner, fixture, grading, and evidence requirements. Do not relabel
component tests as agent behavior coverage. This inventory does not replace the
deterministic benchmark scorecard or its measured pass/fail outcomes.
