# Engineering Handbook: Foundations (Stages 1–3)

Investigation prompts for Correctness, Concurrency, and Failure Resilience. Verify runtime behavior, contracts, and execution paths before reporting.

---

## Stage 1: Correctness

- **Logic & Edge Cases**:
  - Off-by-one errors: loop bounds, ranges, slices, time windows (`<=` vs `<`, `>=` vs `>`).
  - Intervals: half-open `[start, end)` vs closed `[start, end]`.
  - Empty collections & nulls: check `.getFirst()`, `list[0]`, `map.get()`. Guard `NoSuchElementException` / `NullPointerException`.
  - Optionals: unwrapping without checks (`.orElseThrow()`, `.get()`).
  - Boundaries: min/max limits, 0, negative values, empty strings.
- **Mathematical & Financial Accuracy**:
  - Zero division guards (`val / total`).
  - Float vs decimal: `BigDecimal` / `Decimal` vs binary float rounding. Exact equality vs domain tolerance.
  - Rounding direction: floor vs ceil vs half-up. Integer division truncation (`a / b` vs `a // b`).
- **Domain vs Presentation Invariant**:
  - Presentation logic (lot size scaling, UI currency formatting) must **never** mutate domain/engine state (`trail_order.qty`, `tsl`).
- **Type Invariants**:
  - Verify legal states across construction, deserialization, mutation, and exposed mutable refs. Can callers bypass constraints?
  - Report reachable invalid states and consequences. Match language idiomatic guarantees.
- **Sentinel Objects**:
  - If sentinel represents non-existence (`EMPTY_SENTINEL`, `None`, `-1`), ensure downstream logic does not treat as valid data.

---

## Stage 2: Concurrency & Safety

- **Mutexes & Keyed Locks**:
  - Lock ordering: prevent deadlocks across multi-resource acquisitions.
  - Double release: `finally` blocks must not release unacquired or twice.
  - Reentrancy: detect coroutines/threads re-acquiring non-reentrant locks.
  - Blocking I/O inside lock: stalls workers and causes deadlocks. Establish invariant before moving I/O out.
  - Keyed lock memory: evict unused keys under high symbol/ID churn.
- **Atomicity & Mutations**:
  - TOCTOU (check-then-act) race windows.
  - Concurrent maps: compound operations require atomic primitives (`computeIfAbsent`, `compareAndSet`) or shared locks; thread-safe collections do not protect multi-step invariants.
- **Virtual Threads (Java)**:
  - Check JDK version and blocking calls before claiming carrier pinning. [JDK 24 changed monitor pinning](https://docs.oracle.com/en/java/javase/24/migrate/significant-changes-jdk-24.html) (JEP 491); do not flag `synchronized` without runtime verification.
  - Long tasks stalling ingress: verify offload preserves ordering, bounds concurrency, and handles failures.
- **Asyncio / Coroutines (Python)**:
  - Background tasks: require explicit exception handlers; unhandled task exceptions fail silently.
  - Blocking calls: synchronous broker SDKs or file I/O must use `asyncio.to_thread` or `run_in_threadpool`.
  - Task cancellation: state must remain consistent if cancelled during critical sections.

---

## Stage 3: Failure & Resilience

- **Error Propagation & Leaks**:
  - Catch at proper boundaries; prevent unhandled 500s.
  - Trace error paths: check cleanup and caller-observed results. Beware empty catch blocks or defaults hiding failures.
  - Fallbacks: ensure fallback does not mask fatal failure or exhausted retries. Verify caller diagnostics. Never expose internal errors to users.
- **Timeouts & Deadlines**:
  - Trace end-to-end deadlines through clients; flag missing bounds on I/O.
- **Retry Storms & Backoff**:
  - Bounded retries with exponential backoff and jitter.
  - Avoid retrying non-idempotent operations or amplifying system overload.
- **Poison-Pill Defense**:
  - Corrupted stream/queue messages: log at ERROR, route to DLQ / ack to prevent consumer crash loops.
