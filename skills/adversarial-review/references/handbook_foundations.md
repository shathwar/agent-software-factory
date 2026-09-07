# Engineering Handbook: Foundations (Stages 1–3)

Consult this reference when conducting deep audits on Correctness, Concurrency, and Failure Resilience.

---

## Stage 1: Correctness

- **Logic & Edge Cases**:
  - Off-by-one errors in loops, ranges, slicing, or time windows (`<=` vs `<`, `>=` vs `>`).
  - Check half-open intervals `[start, end)` vs closed intervals `[start, end]`.
  - Null / None / empty collections handling. Does `.getFirst()`, `list[0]`, or `map.get()` throw `NoSuchElementException` or `NullPointerException`?
  - Optional unwrapping: check `.orElseThrow()` or `.get()` on empty optionals.
  - Boundary values: min/max integer limits, 0, negative values, empty strings.
- **Mathematical & Financial Accuracy**:
  - Division by zero guards (`val / total` where total can be 0).
  - Floating-point vs decimal precision (`BigDecimal` / `Decimal` vs binary float rounding). Never compare floats with `==`.
  - Rounding direction (floor vs ceil vs half-up) and integer division truncation (`a / b` vs `a // b`).
- **Domain vs Presentation Invariant**:
  - Presentation logic (e.g. lot size multiplication, UI currency formatting) must **never** mutate domain or execution engine state (`trail_order.qty`, `tsl`).
- **Sentinel Objects**:
  - If a sentinel value (e.g. `EMPTY_SENTINEL`, `None`, `-1`) represents non-existence, verify downstream logic does not treat it as valid.

---

## Stage 2: Concurrency & Safety

- **Mutexes & Keyed Locks**:
  - Lock ordering to prevent deadlocks across multi-resource acquisitions.
  - Double release: ensure `finally` blocks do not release an unacquired lock or release twice.
  - Reentrancy: check if coroutines/threads call methods that attempt to re-acquire the same non-reentrant lock.
  - Never hold a lock during long-running blocking I/O (HTTP calls, database queries).
  - Memory cleanup in keyed locks: avoid leaks under high symbol churn.
- **Atomicity & State Mutations**:
  - TOCTOU (Time-of-Check to Time-of-Use) / check-then-act race windows.
  - `ConcurrentHashMap` compound atomicity: use `computeIfAbsent`, `compute`, `putIfAbsent` instead of separate `containsKey` + `get` + `put`.
- **Virtual Threads (Java)**:
  - Do not pin carrier threads inside `synchronized` blocks doing carrier-thread-blocking I/O; prefer `ReentrantLock`.
  - Offload long-running tasks from stream consumers to VT executors to keep ingress streams unblocked.
- **Asyncio / Coroutines (Python)**:
  - Background task exceptions: ensure background tasks have explicit exception handlers; unhandled exceptions in background tasks are silent killers.
  - Synchronous blocking broker SDKs or file I/O must use `run_in_threadpool` or `asyncio.to_thread`.
  - Cancellation handling: ensure state remains consistent if a task is cancelled during critical section.

---

## Stage 3: Failure & Resilience

- **Error Propagation & Leaks**:
  - Are exceptions caught at the right boundaries or leaking as unhandled 500s?
  - Check for silent exception swallows (`catch (Exception e) {}` or `except: pass`). Every failure must be logged with context or propagated.
- **Timeouts & Deadlines**:
  - Explicit socket, connection, and execution timeouts on every external call (HTTP, WebSocket, DB, Redis).
- **Retry Storms & Backoff**:
  - Are retries bounded with exponential backoff and jitter?
  - Is circuit breaker logic or backpressure applied to avoid hammering failing downstream dependencies?
- **Poison-Pill Defense**:
  - If a corrupted message arrives on a stream/queue, is it logged at ERROR and acknowledged/dead-lettered to prevent consumer crash loops?
