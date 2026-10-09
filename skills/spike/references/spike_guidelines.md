# Spike Guidelines & Empirical Sandbox Protocol

A guide to executing rapid, disposable spikes that answer critical technical unknowns without creating architectural debt or polluting the codebase.

---

## 1. The Throwaway Mindset

A spike is a probe sent into the unknown to gather facts. It is **not** Phase 1 of implementation.

### Why Spikes Must Be Throwaway
1. **Speed requires abandoning production constraints**: Production code requires error boundaries, telemetry, accessibility, clean layering, internationalization, and test suites. If you apply these constraints to an experiment, exploring a single question takes days instead of 30 minutes.
2. **Spike architecture is biased toward the question**: A spike built to measure throughput cuts corners everywhere except the throughput bottleneck. If kept, those cut corners become hidden production bugs.
3. **Psychological freedom to abandon dead ends**: When you know code is throwaway, you will happily discard an approach that fails. When you feel you are writing "early production code", you will fall victim to the sunk cost fallacy.

> **Rule**: When the spike is complete, take the **knowledge**, extract any **minimal verified snippet** (e.g. an obscure config flag or correct API sequence), and **discard the harness**.

---

## 2. Sandboxing & Workspace Isolation

Spikes must never leave artifacts scattered across the production tree.

### Workspace Location Hierarchy
1. **Primary**: `.scratch/<spike-name>/` in the repository root. Ensure `.scratch/` is in `.gitignore`.
2. **Secondary**: `scratch/<spike-name>/` in the repository root or temporary directory.
3. **Agent Environment**: `<appDataDir>/brain/<conversation-id>/scratch/<spike-name>/`.

### Dependency Isolation
- Avoid modifying the root `package.json`, `go.mod`, `Cargo.toml`, or `pyproject.toml` for spike dependencies.
- Use isolated sub-packages or single-file scripts with self-contained dependencies:
  - **Python**: Use `uv run script.py` with PEP 723 inline script metadata.
  - **Node.js**: Use a nested `.scratch/package.json` or `npx`/`tsx`.
  - **Go**: Use a nested `.scratch/go.mod`.
  - **Rust**: Use `cargo-script` or a nested scratch crate in `.scratch/Cargo.toml`.

---

## 3. Formulating Falsifiable Hypotheses

Every spike must start with a question framed such that it can be answered with a clear **Yes / No / Specific Value**.

### Question Reframing Matrix

| Vague Design Question | Falsifiable Spike Hypothesis |
|---|---|
| "Can SQLite handle our writes?" | "Can SQLite in WAL mode with `busy_timeout=5000` process 5,000 serialized transactions/sec under 16 concurrent readers with zero `SQLITE_BUSY` errors?" |
| "Is WebSockets or SSE better for streaming?" | "Can an SSE endpoint maintain 1,000 idle connections consuming < 50MB RSS, and reconnect automatically within 2 seconds upon socket termination?" |
| "Does the ORM generate bad queries?" | "Does calling `findWithRelations()` on 1,000 entities trigger an N+1 query pattern or execute in a single SQL join?" |
| "Can we parse this 500MB JSON payload?" | "Can `stream-json` parse a 500MB JSON array in Node.js keeping heap usage under 100MB?" |

---

## 4. Mocking & Scaffolding Strategies

Do not build real backends to test a frontend question; do not build real frontends to test a backend question.

### Synthetic Data Generation
- Generate synthetic data in memory rather than reading massive fixtures from disk.
- Match realistic data shapes: if production strings are UUIDs or 200-character JSON blobs, do not test with `"foo"`. String allocation and hashing overhead matter at scale.

### Local Mock Services
- Replace third-party external APIs with a minimal in-memory HTTP server running on `localhost:PORT`.
- Simulate real-world network conditions:
  - **Latency**: Add deliberate `setTimeout` / `sleep` (e.g. 50ms–200ms).
  - **Jitter**: Randomize response delays by ±30%.
  - **Errors**: Return HTTP 429 (Rate Limit) or HTTP 503 every N requests.

---

## 5. Benchmarking & Measurement Hygiene

`run_spike.py` measures subprocess wall time (including startup and teardown) and
completed commands per second. The legacy JSON field `rps` and flag
`--expected-rps` refer to command runs, not application requests. JSON includes
`measurement_scope` and `throughput_unit`; prefer `--expected-runs-per-second`.

For service SLIs, use a workload harness that keeps the service running, warms the
actual process and connection pools, records one latency sample per operation, and
counts completed requests over the measurement interval. Record failures separately.
Retain raw samples or the load tool report, workload size, concurrency, and environment
with the ADR. Do not infer request counts from subprocess counts or divide a batch
p99 by batch size. A command-level PASS alone cannot settle a service SLI.

Follow these measurement rules:

### 1. Separate Warm-Up from Measurement
- JIT compilers (V8, JVM, PyPy) optimize code over initial runs.
- Database buffer pools, OS page caches, and connection pools must be primed.
- **Protocol**: Run 1,000 warm-up iterations unmeasured, then run 10,000 measured iterations.

### 2. Measure Distributions, Not Just Averages
- An average latency of 5ms can easily hide a p99 latency of 1,200ms caused by GC pauses or lock contention.
- Always calculate:
  - **p50 (Median)**: Typical experience.
  - **p95 / p99**: Long-tail behavior under contention.
  - **Max**: Extreme outliers.

### 3. Realistic Concurrency
- Do not measure concurrency by running asynchronous promises sequentially in a loop.
- Use worker pools, goroutines, or parallel worker threads that actively compete for the shared resource simultaneously.

---

## 6. Settle the Design Frontier

The purpose of the spike is to feed facts directly into the design process:

1. **Return to `design`**:
   - Provide the concrete measurement table.
   - Declare the open question settled.
   - Example: *"Question 3 on Redis locking is settled: with 64 workers, redlock overhead is 1.8ms p99, well within our 10ms budget. We can proceed with distributed locks."*
2. **Document in ADR**:
   - Record the spike findings under the *Decision Rationale* or *Consequences* section of the [ADR](../../design/references/adr_template.md).
   - Cite the sandbox benchmark script and date.

---

## 7. Cleanup & Archiving

Once the empirical verdict is accepted:
1. **Extract snippets**: If the spike revealed a specific non-obvious configuration or algorithm, paste the minimal snippet into the design doc or ADR.
2. **Clean up**: Delete `.scratch/<spike-name>/` unless the user explicitly requests keeping the benchmark code for regression tracking.
3. If kept, commit to a dedicated `benchmarks/` or `spikes/` directory with a README explaining how to rerun it.
