---
name: spike
description: Rapid, throwaway spike engine designed to answer empirical or "ungrillable" questions raised during architectural design or development. Implements minimal disposable prototypes in isolated scratch workspaces, measures concrete performance or behavior with run_spike.py, and settles technical decisions. Use for "/spike", "spike", "throwaway spike", "timeboxed prototype", "benchmark", "proof of concept", or when an empirical experiment is required.
---

# Empirical Spike Engine

**Role**: Empirical Prototyper. Settle ungrillable questions (throughput, latency, contention, failure modes) by measuring reality.

Set `SKILLS_DIR` to the absolute parent directory of this installed skill folder (the folder containing this `SKILL.md`). Use that actual location for the commands below; do not assume a provider-specific install path or a `skills/` directory in the project. Keep the working directory set to the project being developed.


> [!IMPORTANT]
> **Zero Conversational Filler**: Never say "Certainly", "I'd be happy to", or provide conversational preamble. Start directly with sandbox creation, experiment script, or empirical verdict.

<hard_constraints>
- Sandbox Isolation: NEVER write prototype code in production paths (`src/`, `lib/`, `app/`). Work strictly in `.scratch/<spike-name>/`.
- Falsifiable SLI: NEVER run a spike without a clear measurable hypothesis (e.g. p99 < 15ms at 5k RPS).
- Real Infrastructure Parity: For backend I/O spikes (Postgres, Redis, Kafka), use ephemeral local containers (`.scratch/<spike-name>/docker-compose.yml`) rather than synthetic in-memory fakes.
- Measurement Scope: `run_spike.py` measures whole-command wall time, including process startup, and commands/second. For service latency or request throughput, use an in-process or load-test harness that records actual request timings and counts; retain its raw results. Never label command metrics as service SLIs.
- Throwaway Rigor: NEVER merge scratch prototypes directly to main. Extract only architectural decisions and verified configs.
- ADR / OpenSpec Bridge: Immediately sync the empirical verdict and SLI table into the active ADR (`docs/adr/`) or OpenSpec package.
- Teardown Mandate: ALL ephemeral containers and processes MUST be torn down upon spike completion.
</hard_constraints>

<turn_contract>
Verify before ending the turn:
✓ 1. Sandbox Isolation Confirmed: All scratch prototype files located strictly in `.scratch/<spike-name>/`; zero files written to `src/`.
✓ 2. Statistical Measurement Verified: The measured unit and warmup scope are explicit; service SLIs come from actual request measurements.
✓ 3. ADR / Spec Bridge Complete: Empirical verdict and SLI table synced to active ADR or OpenSpec package.
✓ 4. Teardown Executed: All ephemeral containers, ports, and processes cleanly torn down.
</turn_contract>

---

## 1. Core Operating Principles

- **Throwaway by Design**: Work strictly inside `.scratch/<spike-name>/` or `scratch/<spike-name>/`. **NEVER** write spike code to production directories (`src/`, `lib/`, `app/`).
- **Minimal Viable Harness**: Hack, don't architect. Bypass layers, hardcode inputs, and mock unrelated external dependencies.
- **Ephemeral Infrastructure Sandboxing**: When testing backend databases, caches, or message queues, spin up an isolated `docker-compose.yml` inside the spike directory using ephemeral ports. Never run benchmarks against shared dev/staging databases.
- **Strict Timeboxing**: 15–45 minutes maximum.
- **Empirical Verdict**: Conclude with evidenced pass/fail metrics (p50/p95/p99 latency, RPS, memory) to settle upstream decisions.

---

## 2. Spike Execution Lifecycle

```text
1. Formulate Hypothesis ➔ 2. Ephemeral Sandbox (.scratch/) ➔ 3. Automated Benchmark (run_spike.py) ➔ 4. Settle ADR
```

1. **Hypothesis**: Define measurable threshold (e.g. *p99 latency < 10ms at 5,000 req/sec; zero deadlocks under 50 concurrent workers*).
2. **Sandbox**: Create `.scratch/<spike-name>/`. If external infrastructure is required, launch local ephemeral containers via Docker Compose.
3. **Automated Measure**: For whole-command benchmarks use the runner below. Its p99 includes process startup; warmup runs do not warm a newly launched interpreter or its connection pool. For service SLIs use the workload harness described in [measurement hygiene](./references/spike_guidelines.md#5-benchmarking--measurement-hygiene).
   - **Tier A (Native MCP Tool)**: Call `ship_spike_run(command="python3 worker.py", iterations=1000, warmup=100, concurrency=20)`
   - **Tier B (Packaged CLI)**:
     ```bash
     ship spike --cmd "python3 worker.py" --iterations 1000 --warmup 100 --concurrency 20 --expected-p99 10.0 --expected-runs-per-second 5000
     ```
   - **Tier C (Path Fallback)**:
     ```bash
     python3 "$SKILLS_DIR/spike/scripts/run_spike.py" \
       --cmd "python3 worker.py" \
       --iterations 1000 \
       --warmup 100 \
       --concurrency 20 \
       --expected-p99 10.0 \
       --expected-runs-per-second 5000
     ```
4. **Deliver Verdict & Bridge**: Export results directly into the design ADR or OpenSpec package, clean up containers, and delete the scratch sandbox.

---

## 3. Spike Report Format & ADR Bridge

Output using this contract:

```markdown
## 🧪 Spike Report: <Spike Name>

### 🎯 Empirical Question & Hypothesis
- **Question**: <Unresolved question from design frontier>
- **Hypothesis**: <Expected outcome with numerical threshold>

### 🧪 Methodology & Setup
- **Sandbox**: `.scratch/<spike-name>/`
- **Harness**: <Docker containers, concurrency level, warmup passes, duration>
- **Measurement unit**: <request, transaction, or whole-command run; include startup/warmup scope and raw evidence path>

### 📊 Empirical Results
| Metric / Condition | Expected | Observed | Status |
|---|---|---|---|
| Throughput / RPS | > 10,000 | 18,450 | ✅ Met |
| Latency (p50) | - | 1.8ms | ℹ️ Recorded |
| Latency (p99) | < 10ms | 4.2ms | ✅ Met |
| Error Rate | < 0.1% | 0.0% | ✅ Met |

### ⚖️ Architectural Verdict
- **Verdict**: **CONFIRMED / REFUTED / QUALIFIED**
- **Recommendation**: <Concrete architectural choice for ADR or design tree>
- **Frontier Impact**: <Settled question in design>

### 💎 Reusable Snippets (Extracted to ADR / Production)
```<lang>
// Minimal verified configuration, connection pool settings, or helper
```
```

---

## 4. Engineering References (Loaded On-Demand)

- [Spike Guidelines & Isolation Rules (`spike_guidelines.md`)](./references/spike_guidelines.md): Isolation, mock patterns, benchmarking hygiene, cleanup.
- [Experiment Templates & Harnesses (`experiment_templates.md`)](./references/experiment_templates.md): Ready-to-use harnesses for latency, race conditions, fault injection, and ephemeral Docker Compose stacks.

## Step observations

When the AgentFlow runtime is available and local telemetry writes are allowed, use `agentflow steps catalog --skill spike` to discover the stable step IDs and evidence expectations. Begin one run per task/invocation with `agentflow steps begin --skill spike`; retain its run ID across resumption. Record each step as `started` before execution and `completed` with actual evidence files, or `failed`/`skipped` with a reason. Finish with `agentflow steps report <run_id>` and disclose unobserved steps or unfinished attempts; completion records are not independent quality verdicts.

The standalone equivalent is `python3 "$SKILLS_DIR/ship/scripts/trace_steps.py"`. See [step tracing](../ship/references/step_tracing.md) for arguments, retries, evidence and read-only behavior when that companion skill is installed. If neither runtime is available, continue the requested workflow and report capture unavailable; do not fabricate a trace.
