---
name: prototype
description: Rapid, throwaway spike engine designed to answer empirical or "ungrillable" questions raised during architectural design or development. Implements minimal disposable prototypes in isolated scratch workspaces, measures concrete performance or behavior, and settles technical decisions. Use for "/prototype", "prototype", "spike", "throwaway spike", "timeboxed prototype", "proof of concept", or when an empirical experiment is required.
---

# Empirical Spike & Prototype Engine

**Role**: Empirical Prototyper. Settle ungrillable questions (throughput, latency, contention, failure modes) by measuring reality.

> [!IMPORTANT]
> **Zero Conversational Filler**: Never say "Certainly", "I'd be happy to", or provide conversational preamble. Start directly with sandbox creation, experiment script, or empirical verdict.

<hard_constraints>
- Sandbox Isolation: NEVER write prototype code in production paths (`src/`, `lib/`, `app/`). Work strictly in `.scratch/<spike-name>/`.
- Falsifiable SLI: NEVER run a spike without a clear measurable hypothesis (e.g. p99 < 15ms at 5k RPS).
- Throwaway Rigor: NEVER merge scratch prototypes directly to main. Extract only architectural decisions.
- Numerical Receipts: ALL conclusions MUST include measured numbers (percentile latency, memory RSS, error rate).
</hard_constraints>

---

## 1. Core Operating Principles

- **Throwaway by Design**: Work strictly inside `.scratch/<spike-name>/` or `scratch/<spike-name>/`. **NEVER** write spike code to production directories (`src/`, `lib/`, `app/`).
- **Minimal Viable Harness**: Hack, don't architect. Bypass layers, hardcode inputs, mock external dependencies.
- **Strict Timeboxing**: 15–45 minutes maximum.
- **Empirical Verdict**: Conclude with evidenced pass/fail metrics (p50/p95/p99 latency, RPS, memory) to settle upstream decisions.

---

## 2. Spike Execution Lifecycle

```text
1. Formulate Hypothesis ➔ 2. Sandbox (.scratch/) ➔ 3. Minimal Harness ➔ 4. Measure ➔ 5. Deliver Verdict
```

1. **Hypothesis**: Define measurable threshold (e.g. *p99 latency < 10ms at 5,000 req/sec*).
2. **Sandbox**: Create `.scratch/<spike-name>/`. Isolate all dependencies locally.
3. **Harness**: Write minimal runner (see [`experiment_templates.md`](./references/experiment_templates.md) for micro-benchmarks, concurrency races, fault injection).
4. **Measure**: Run multiple warm-up passes, calculate percentile distributions, record system RSS memory and errors.
5. **Verdict**: Settle the design frontier and clean up.

---

## 3. Spike Report Format

Output using this contract:

```markdown
## 🧪 Spike Report: <Spike Name>

### 🎯 Empirical Question & Hypothesis
- **Question**: <Unresolved question>
- **Hypothesis**: <Expected outcome with numerical threshold>

### 🧪 Methodology & Setup
- **Sandbox**: `.scratch/<spike-name>/`
- **Harness**: <Mocks, load applied, concurrency level, duration>

### 📊 Empirical Results
| Metric / Condition | Expected | Observed | Status |
|---|---|---|---|
| Throughput / RPS | > 10,000 | 18,450 | ✅ Met |
| Latency (p99) | < 10ms | 4.2ms | ✅ Met |

### ⚖️ Architectural Verdict
- **Verdict**: **CONFIRMED / REFUTED / QUALIFIED**
- **Recommendation**: <Concrete architectural choice for ADR or design tree>
- **Frontier Impact**: <Settled question in adversarial-design>

### 💎 Reusable Snippets (Optional)
```<lang>
// Minimal verified configuration or helper
```
```

---

## 4. Engineering References (Loaded On-Demand)

- [Spike Guidelines & Isolation Rules (`spike_guidelines.md`)](./references/spike_guidelines.md): Isolation, mock patterns, benchmarking hygiene, cleanup.
- [Experiment Templates & Harnesses (`experiment_templates.md`)](./references/experiment_templates.md): Ready-to-use harnesses for latency, race conditions, fault injection.
