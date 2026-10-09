# Agentic Software Factory

A local-first autonomous engineering lifecycle engine, state ledger, and MCP server for AI coding agents. Covers the complete lifecycle from architectural design, empirical spikes, test-driven implementation, and adversarial review to delivery sign-off, enterprise policy enforcement, and native skill authoring:

```text
                     USER REQUEST: /ship "<Feature Idea>"
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 DESIGN: SPECIFICATION & ARCHITECTURE (design)               │
│   • Persona: Senior Principal Systems Architect                             │
│   • Model: Design Tree & Frontier Algorithm (Round-based batching)          │
│   • Output: Provider-owned specifications and design decisions            │
└──────────────────────┬───────────────────────────────┬──────────────────────┘
                       │                               │
                       ▼ (Ungrillable Question?)       │
        ┌─────────────────────────────┐                │
        │    SPIKE: spike             │                │
        │   • Isolated scratch sandbox│                │
        │   • Measures empirical SLIs │                │
        │   • Settles design frontier │                │
        └──────────────┬──────────────┘                │
                       │ (Verdict returned)            │
                       ▼                               ▼ (User Approves Spec)
┌─────────────────────────────────────────────────────────────────────────────┐
│          IMPLEMENTATION: TEST-FIRST DEVELOPMENT (tdd + simplify)            │
│   • Test Driver: Writes failing behavioral test (Red Phase)                 │
│   • Simplify Implementer: Climbs Laziness Ladder, stdlib-first (Green)      │
│   • Code Refactorer: Simplifies under green; adds simplify: debt markers    │
│   • Inputs: SDD provider tasks and acceptance criteria                       │
│   • Output: Self-verifying, lean production implementation                  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼ (Code & Tests Complete)
┌─────────────────────────────────────────────────────────────────────────────┐
│          REVIEW: ADVERSARIAL REVIEW & AUTO-FIX (review)                       │
│   • Stage 0: Spec Alignment (Verifies code directly against ADR/Spec)       │
│   • Stages 1–9: Correctness, Concurrency, Failure, Craftsmanship, SOLID     │
│   • Review Loop: Finds critical issues and checks for regressions            │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼ (Judge Issues PASS)
┌─────────────────────────────────────────────────────────────────────────────┐
│                 DELIVERY: PR SIGN-OFF & ARCHIVING                           │
│   • Final test suite verification run                                       │
│   • Delivery Walkthrough Report & PR summary ready for review               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Quickstart & Installation

Install skills into your environment's local skills directory (defaults to `~/.gemini/config/skills/`):

```bash
# Standard installation
./scripts/setup/install_skills.sh

# Target-specific installation
./scripts/setup/install_skills.sh --target-claude      # Claude Code (~/.claude/skills)
./scripts/setup/install_skills.sh --target-cursor      # Cursor (~/.cursor/skills)
./scripts/setup/install_skills.sh --target-antigravity # Google Antigravity (~/.gemini/config/skills)

# Safe update with timestamped backups
./scripts/setup/install_skills.sh --backup
```

For agent frameworks:
- **Vercel Skills CLI (70+ Agents)**: `npx skills add shathwar/agentflow`
- **Claude Code**: Workspace skills in [`.claude/skills/`](./.claude/skills/) and guidelines in [`CLAUDE.md`](./CLAUDE.md)
- **Cursor IDE**: Preconfigured in [`.cursor/rules/ship.mdc`](./.cursor/rules/ship.mdc)
- **OpenAI Codex**: Manifest configured in [`.codex-plugin/plugin.json`](./.codex-plugin/plugin.json)
- **GitHub Copilot**: Context instructions in [`.github/copilot-instructions.md`](./.github/copilot-instructions.md)
- **Universal Nano Rules**: Drop-in rule files in [`nano/`](./nano/) (<60 lines each, universal [`nano/AGENTS.md`](./nano/AGENTS.md) <100 lines)

---

## Skills Catalog

| Skill | Trigger / Command | Stage | Core Mandate & References |
|---|---|---|---|
| [**`review`**](./skills/review/SKILL.md) | `/review`, `review`, `adversarial review` | Post-implementation | **Recommended Pilot**. 10-stage systems review with evidence-based Judge. Ref: [Security](./skills/review/references/handbook_security.md), [WebPerf](./skills/review/references/handbook_webperf.md), [Architectural Invariants](./skills/review/references/architectural_invariants.md), [Finding Schema](./skills/review/references/finding_schema.md). |
| [**`simplify`**](./skills/simplify/SKILL.md) | `/simplify`, `simplify`, `lazy senior dev` | Simplicity & Anti-Bloat | Laziness Ladder (YAGNI, stdlib first, zero unrequested abstractions). Debt auditing via `scan_debt.py`. Ref: [Laziness Ladder](./skills/simplify/references/laziness_ladder.md), [Debt Tracking](./skills/simplify/references/debt_tracking.md). |
| [**`tdd`**](./skills/tdd/SKILL.md) | `/tdd`, `tdd`, `red-green-refactor` | Implementation | Iron Law of Test-First, Doubt Cycle, fast fakes over DB mocks. Diff auditor via `verify_tdd.py`. Ref: [Doubt Cycle](./skills/tdd/references/doubt_cycle.md), [TDD Patterns](./skills/tdd/references/tdd_patterns.md), [Anti-Patterns](./skills/tdd/references/anti_patterns.md). |
| [**`design`**](./skills/design/SKILL.md) | `/design`, `design`, `grill me on this design` | Pre-implementation | Facts vs. Decisions Law, batched Frontier Rounds, Capability Closure checklists. Ref: [Capability Closure](./skills/design/references/capability_closure.md), [ADR Template](./skills/design/references/adr_template.md), [External SDD integration](./skills/ship/references/sdd.md). |
| [**`spike`**](./skills/spike/SKILL.md) | `/spike`, `spike`, `throwaway spike` | Empirical Validation | Rapid disposable prototypes in `.scratch/`. Benchmark runner (`run_spike.py`) measuring p50/p90/p95/p99 and RSS memory. Ref: [Guidelines](./skills/spike/references/spike_guidelines.md), [Templates](./skills/spike/references/experiment_templates.md). |
| [**`ship`**](./skills/ship/SKILL.md) | `/ship`, `ship`, `/lifecycle` | Full Lifecycle | Chains all skills with transition gates, 2-phase atomic transactions, and working tree fingerprinting. Ref: [State Machine](./skills/ship/references/lifecycle_state_machine.md), [Team Rollout](./skills/ship/references/team_rollout.md), [Headless CI](./skills/ship/references/headless_ci_guide.md). |
| [**`evals`**](./skills/evals/SKILL.md) | `/evals`, `evals`, `ai evals` | AI Regressions & Evals | Parlance Labs / Hamel Husain methodology. Zero-dependency review app (`serve_review_app.py`), binary judges, Rogan-Gladen statistical calibration (`score_calibration.py`). Ref: [Taxonomy](./skills/evals/references/taxonomy_framework.md), [Math](./skills/evals/references/calibration_math.md). |
| [**`debug`**](./skills/debug/SKILL.md) | `/debug`, `debug`, `/fix`, `fix` | Root-Cause Repair | Reproduction test first, backward data-flow tracing, multi-boundary logging, anti-cheat verification via `verify_fix.py`. Ref: [Root Cause Tracing](./skills/debug/references/root_cause_tracing.md), [Logging](./skills/debug/references/multi_component_logging.md). |
| [**`ux`**](./skills/ux/SKILL.md) | `/ux`, `ux`, `ui`, `a11y` | Interface Engineering | Prime Directive (intent and flow before visual styling), State Completeness Law (6 view states + control states), and source-pattern linting via `audit_ux.py`. Ref: [Orchestration](./skills/ux/references/orchestration.md), [State Matrix](./skills/ux/references/state_matrix.md), [WCAG](./skills/ux/references/accessibility_wcag.md). |
| [**`skill`**](./skills/skill/SKILL.md) | `/skill`, `skill`, `create skill` | Authoring & Capabilities | End-to-end Skill Factory: transforms requirements into standard native Claude `SKILL.md` + companion deterministic `scripts/` + `references/` + `assets/` + `evals/`, assesses host × model compatibility matrices, and computes token cost economics. Ref: [Skill Guide](./skills/skill/references/skill_factory_guide.md). |

---

## Runtime and Verification Scope

1. **Standard-library core (Python 3.10+)**:
   The lifecycle engine, standalone Python validators, and default Python tests use the standard library. Rendered UX checks require Node, Playwright, and a browser. The legacy response harness has optional Anthropic SDK and `agy` CLI modes. The separate live tool-loop suite uses the standard-library HTTP client, an Anthropic API key, an explicitly configured model, and Docker.
2. **Byte-for-Byte Distribution Parity**:
   Every specialist tool in `src/ship/tools/` has a TypeScript distribution under `skills/*/scripts/`. Enforced by `scripts/verify/sync_parity.py --check` and Git pre-commit hooks.
3. **Native stdio Model Context Protocol (MCP) Server**:
   Built-in zero-dependency stdio server (`src/ship/mcp/`) connecting lifecycle management, gate checks, checkpoints, and verifications to Cursor, Claude Desktop, and Antigravity.
4. **Checks with explicit evidence limits**:
   Lifecycle delivery verification executes configured tests and binds receipts to source snapshots. Local receipts are not unforgeable attestations. Specialist checks have narrower scopes:
   - `verify_tdd.py`: Checks diff/test patterns and assertless tests; does not establish red-before-edit chronology.
   - `scan_debt.py`: Checks debt marker structure and static thresholds; does not measure runtime debt ceilings.
   - `validate_report.py`: Checks report shape and optional source grounding; does not measure defect recall.
   - `verify_fix.py`: Checks reproduction and assertion-change patterns; does not independently establish root cause.
   - `score_calibration.py`: Computes statistics from supplied labels; does not verify label correctness or judge quality.
   - `audit_ux.py`: Checks source patterns for UI states and accessibility; does not prove rendered behavior or WCAG compliance.
5. **Two-Phase Crash Self-Healing**:
   Authoritative multi-change ledger (`.agentflow/state.json`) with atomic two-phase commit spec archiving (`.agentflow/archive-transaction.json`) ensuring cold resumption after interrupted sessions.
6. **Real-Agent Observability & Hash-Chained Audit Trail**:
   The live fixture harness captures host-observed tool calls, edits, commands, and test results at tool boundaries. Local step observations may be agent-reported. Hash-chained events (`.agentflow/events.jsonl`) detect changes relative to a trusted prior hash; they are not immutable or independently authenticated. See the live evaluation documentation for chronology and capture limits.
7. **Enterprise Policy Governance**:
   A local policy layer (`.agentflow/policy.json`) checked at AgentFlow entry points declares tool allowlists, path restrictions, and approval requirements. Trusted hosts must protect authoritative policy, authenticate approvals, and enforce process, filesystem, and network isolation for all agent tools.
8. **Native Claude Skills Factory & Ecosystem Matrix**:
   Automated synthesis pipeline for native agent skills (`agentflow skill create`) generating standard `SKILL.md`, deterministic `scripts/validate_<skill>.py`, on-demand `references/`, `assets/`, and `evals/`. Assesses compatibility across Claude Code, Antigravity, Cursor, Codex, and Claude Desktop, while tracking token economics via `agentflow cost`.

---

## Developer Tooling & Verification Commands

Run these commands from the repository root. Browser checks run separately as described in [evaluation instructions](./tests/evaluation/README.md).

TypeScript tests use [Bun's native test runner](https://bun.sh/docs/test) (Bun 1.3.0 or newer).
No npm dependencies or build step are needed. Tool regressions migrated from
Python live alongside the TypeScript tool tests. Python tests remain for the
Python lifecycle, MCP runtime, and maintained Python tool implementations.

```bash
# Verification & Parity
./scripts/verify/check_sanity.sh               # Sanity checks (syntax, parity, nano budget, coverage)
python3 scripts/verify/sync_parity.py --check  # Verify byte-for-byte parity for mapped distribution files
python3 scripts/verify/check_coverage.py       # Audit skill step coverage inventory and verification gaps
python3 scripts/verify/build_step_catalog.py --check # Verify shipped runtime step IDs and source versions
python3 scripts/verify/ci_gate.py              # Strict CI pull-request policy gate

# Test Suites
bun run test                                # Bun unit, regression, and CLI tests
PYTHONPATH=src:tests:. python3 -m pytest     # Python tests, including subprocesses
./scripts/test/test_fast.sh                   # Selected unit tests
./scripts/test/test_full.sh                   # Full regression and evaluation test suite

# Setup & Sandboxes
./scripts/setup/setup_hooks.sh                 # Install Git pre-commit hook (auto-verifies parity & coverage)
./scripts/setup/setup_playground.sh            # Provision disposable isolated git test sandbox in .agentflow/playground

# Specialist CLI Diagnostics
python3 skills/ship/scripts/inspect_lifecycle.py --doctor  # Lifecycle preflight diagnostics
bun skills/simplify/scripts/scan_debt.ts --strict      # Check debt markers and static thresholds
bun skills/tdd/scripts/verify_tdd.ts --strict          # Check test diff patterns and detect assertless tests
bun skills/review/scripts/validate_report.ts report.json # Validate review report schema
bun skills/ux/scripts/audit_ux.ts --fail-on error src/ # Accessibility and interaction source-pattern checks
bun skills/debug/scripts/verify_fix.ts --strict        # Check reproduction and assertion-change patterns
bun skills/evals/scripts/score_calibration.ts --input test_results.jsonl --p-obs 0.80 # Calibrate judge TPR/TNR
bun skills/spike/scripts/run_spike.ts --cmd "python3 -c 'pass'" --iterations 100     # Run empirical benchmark

# AgentFlow CLI & Observability
agentflow doctor                               # Lifecycle, runtime, and policy preflight check
agentflow events verify                        # Verify tamper-evident hash-chained event stream
agentflow events tail -n 10                    # Tail latest recorded lifecycle events

# /skill Skill Factory & Cost Economics
agentflow skill create <name> --role "<role>"  # Synthesize complete native Claude skill
agentflow skill validate <dir> --strict        # Validate skill against standard layout
agentflow skill matrix <path>                  # Render Skill × Model × Host compatibility matrix
agentflow skill package <dir> --format tar.gz  # Package skill into distributable bundle
agentflow cost --model <model> --input <N> --output <N> # Compute token run cost and usage metadata
```

---

## Repository Structure

```text
scripts/
├── verify/                     # Sanity checks, parity synchronization, coverage, CI gates
│   ├── check_sanity.sh         # Syntax, parity, nano budget, and coverage checks
│   ├── check_coverage.py       # Audits skill step coverage inventory & rubric checks
│   ├── sync_parity.py          # Synchronizes mapped runtime and tool files
│   └── ci_gate.py              # Pull-request / CI workflow policy gate
├── test/                       # Unit and full regression runners
│   ├── test_fast.sh            # Selected unit test runner
│   └── test_full.sh            # Standard-library validation and regression runner
├── setup/                      # Host installation, hooks, sandboxes
│   ├── install_skills.sh       # Portable skill installer (symlink/copy to target environments)
│   ├── setup_hooks.sh          # Pre-commit hook installer checking mapped distribution parity
│   └── setup_playground.sh     # Ephemeral disposable git test repo provisioner
└── README.md                   # Detailed guide and cheat sheet for all developer scripts

skills/                         # Standalone modular agent skill definitions
├── design/                     # Pre-implementation architectural grilling & ADR compiler
├── spike/                      # Isolated empirical prototype & statistical benchmark engine
├── tdd/                        # Test-driven development engine with Doubt Cycle
├── simplify/                   # Anti-bloat, Laziness Ladder, and technical debt auditor
├── review/                     # 10-stage systems code review engine with adversarial Judge
├── ship/                       # Full lifecycle orchestrator with 2-phase commit recovery
├── evals/                      # Parlance Labs / Hamel Husain AI evaluation engine
├── debug/                      # Root-cause debugging engine with reproduction proofs
├── ux/                         # Intent-first interface engineering and source checks
└── skill/                      # Native Claude Skill Factory, validator, and compatibility matrix

nano/                           # High-density, compact rules (<60 lines each)
└── AGENTS.md                   # Universal drop-in rule (<100 lines) combining all 9 skills

src/ship/                       # Unified Python package with selected standalone mirrors
├── cli.py                      # Unified CLI entrypoint (agentflow / ship)
├── lifecycle/                  # SOLID lifecycle, gate, policy, observability, and skill factory
├── mcp/                        # Zero-dependency stdio Model Context Protocol server & policy gates
└── tools/                      # Specialist tools (mirrored in skills/*/scripts/)

tests/                          # Unit tests, fixtures, and evaluation suites
```

---

## Step Observability

<!-- skill-coverage:start -->
This inventory maps requirements to checks; it does not record test executions or pass rates.

| Skill | Steps | Validator mappings | Component case mappings | Manual case mappings | Steps with gaps |
|---|---:|---:|---:|---:|---:|
| design | 7 | 7 | 6 | 3 | 7 |
| spike | 6 | 6 | 6 | 0 | 6 |
| tdd | 8 | 4 | 4 | 1 | 8 |
| simplify | 10 | 2 | 2 | 3 | 10 |
| review | 17 | 3 | 8 | 6 | 17 |
| debug | 9 | 3 | 3 | 0 | 9 |
| evals | 12 | 3 | 5 | 0 | 12 |
| ux | 17 | 5 | 10 | 0 | 17 |
| ship | 14 | 12 | 12 | 1 | 14 |

Runtime capture: `reported`. Every catalog step has a terminal observation; failures and skips count. This is not success.

Recorded completion does not verify behavior or quality. Recording order does not prove execution order. Step observations do not affect delivery gates.
<!-- skill-coverage:end -->

`agentflow steps begin --skill tdd --task <id>` starts a run using the same stable step IDs as the coverage inventory. Record `started`, `completed`, `failed`, or `skipped` observations, then use `agentflow steps report <run_id>` to inspect missing steps, retries, and evidence integrity. Completion records require evidence files; failed/skipped records require reasons. Reports distinguish missing capture from success and do not change delivery gates. See [step tracing](./skills/ship/references/step_tracing.md) for CLI, standalone, and MCP usage.

The table and observation contract above are generated with the runtime catalog by `scripts/verify/build_step_catalog.py`; `--check` rejects drift. Evidence hashes detect file changes, not whether the recorded claim is true.

The [response harness](./tests/test_agent_regression.py) covers review, debug, TDD, and design response predicates. CI defaults to canned responses (`stub`), even when credentials exist. Explicit `anthropic` mode evaluates model text without a tool loop; `live` evaluates CLI output and depends on host skill setup. Neither mode independently captures tool/edit chronology. A passing stub suite is a harness check, not measured agent adherence.

The [live tool-loop suite](./tests/evaluation/live_agent_regression.md) runs real model-selected tools against disposable fixtures, records host-observed tool calls, file diffs, commands, test results and order, and retains per-run evidence. It runs nightly, on published releases, and through the pre-publication `Release candidate` workflow, separately from PR checks. The Ship trial covers design approval, context reset/resumption, stale delivery rejection, renewed evidence, and archive on a bounded fixture. Missing credentials or incomplete execution cannot pass. Synthetic trace fixtures never certify real-agent behavior.

[Evaluation tooling](./tests/evaluation/README.md) also provides seeded review defects with clean controls, rendered UX fixture checks with negative controls, and adversarial rubric tests. These are bounded component measurements; review agent precision/recall requires actual submitted reviews and adjudication, and browser checks do not establish general accessibility compliance.

## Team Rollout & Governance

- **Enterprise Policy Engine ([`capability_permissions_and_rings.md`](./skills/ship/references/capability_permissions_and_rings.md))**: Policy checks at AgentFlow entry points; organization-wide enforcement requires protected policy and host isolation. See the [host baseline](./skills/ship/references/host_security_baseline.md).
- **Cryptographic Audit Stream ([`step_tracing.md`](./skills/ship/references/step_tracing.md))**: Local hash-chained events for instrumented actions. Completeness depends on capture mode; independent retention and trust require host integration.
- **Multi-Agent Coordination & Ring Lattice ([`multi_agent_coordination.md`](./skills/ship/references/multi_agent_coordination.md), [`agent_identity_and_provenance.md`](./skills/ship/references/agent_identity_and_provenance.md))**: Execution rings (Ring 0 System, Ring 1 Approval, Ring 2 Execution), agent provenance binding, and cooperative task leasing with atomic handoffs.
- **Local Rollout Guide ([`team_rollout.md`](./skills/ship/references/team_rollout.md))**: Preflight doctor checks, workflow profiles (`small-fix`, `standard`, `high-risk`), and zero-loss ledger migrations.
- **Headless CI Guide ([`headless_ci_guide.md`](./skills/ship/references/headless_ci_guide.md))**: Gated GitHub Actions integration requiring explicit design approvals and independent delivery execution receipts.
- **Behavioral Evaluations ([`skill_evaluations.md`](./tests/skill_evaluations.md))**: Manual acceptance scenarios and links to executable component checks.
- **Trust Boundaries**: AgentFlow coordinates local workflow states and policy enforcement. Sandboxing, secrets management, and network containment are reinforced by the host runtime.

### Configurable specification workflow

Ship delegates specification preparation, inspection, verification, and finalization
to an external SDD skill selected in `.agentflow.json`. Ship retains approval, TDD,
engineering review, and delivery evidence. See [the handoff contract and configuration](./skills/ship/references/sdd.md)
and the initial [OpenSpec adapter](./skills/ship/references/sdd_openspec.md).
