# Systems Inquiry Matrix

This matrix details the technical checklists and high-yield probing questions that the Principal Systems Architect uses to construct the Design Tree.

---

## Domain 1: State, Invariants & Consistency

### Critical Inquiries:
- **Single Source of Truth**: Where does canonical state live? In a relational database, memory cache, event log, or third-party service? If replicated, what is the replication lag and split-brain defense?
- **Consistency Boundary**: Is the transaction boundary local or distributed? If distributed, are we using a 2-phase commit (avoid if possible), a SAGA pattern, or outbox pattern with eventual consistency?
- **Domain Invariants**: What business rules must **never** be broken, even under catastrophic failure or network partition? (e.g. *"An account balance can never drop below zero"*, *"An order can never be double-executed"*).
- **Mutations vs. Queries**: Is CQRS strictly needed, or are we adding speculative architectural bloat? Can standard read-replicas solve the load?

### High-Yield Questions:
- *"If the process crashes right after writing to Postgres but before publishing to Kafka, how is state recovered without losing or duplicating the event?"*
- *"What happens when two concurrent updates to the same entity arrive simultaneously at different nodes?"*
- *"Are we using database-level constraints (foreign keys, check constraints, unique indexes) or relying solely on application-level checks that fail under concurrent writes?"*

---

## Domain 2: Concurrency, Contention & Race Windows

### Critical Inquiries:
- **Locking Model**: Optimistic locking (version columns) vs. Pessimistic locking (`SELECT FOR UPDATE`) vs. Keyed in-memory locks (`ReentrantLock`, `asyncio.Lock`) vs. Distributed locks (Redis Redlock, Postgres advisory locks).
- **Deadlock Avoidance**: If multiple resources must be acquired, is there a deterministic global ordering?
- **Idempotency Keys**: Does every mutating endpoint or consumer enforce unique idempotency keys (`X-Idempotency-Key` or event ID)? Where are keys recorded, and what is their TTL?
- **Runtime Threading Model**: Will blocking I/O calls pin virtual threads or block the Node/Python event loop? Are thread pools bounded?

### High-Yield Questions:
- *"Under what conditions does a check-then-act (TOCTOU) race condition exist between checking availability and acquiring the resource?"*
- *"If a client disconnects mid-request, does the background task continue to mutate state, or is cancellation properly propagated?"*
- *"What happens when a distributed lock holder experiences a GC pause or network blip that exceeds the lock lease time?"*

---

## Domain 3: Failure Domains, Timeouts & Resilience

### Critical Inquiries:
- **Timeouts**: Does EVERY network boundary (HTTP, gRPC, Redis, DB, queue) have explicit connect, socket, and deadline timeouts?
- **Retry Mechanics**: Are retries bounded (e.g. max 3)? Do they use exponential backoff with full jitter to avoid retry storms?
- **Circuit Breakers & Bulkheads**: If a non-critical downstream dependency fails, does it degrade gracefully or take down the primary customer path?
- **Poison-Pill Protection**: When a corrupt or unparseable payload arrives on a stream or queue, does the consumer crash-loop or route to a Dead Letter Queue (DLQ) after bounded retries?

### High-Yield Questions:
- *"What is the fallback behavior when downstream dependency X starts taking 8 seconds per request instead of 50ms?"*
- *"How do we prevent a 'thundering herd' on cold cache start or Redis eviction?"*
- *"Can an unhandled exception in an asynchronous fire-and-forget worker silently kill the daemon or drop customer data?"*

---

## Domain 4: Data Evolution, Schema & Migrations

### Critical Inquiries:
- **Zero-Downtime Migration**: Can this schema change be deployed while the previous version of the application code is still running?
- **Table Lock Hazards**: Will adding a column, index, or constraint take an exclusive lock (`ACCESS EXCLUSIVE`) that stalls high-throughput production writes?
- **Index Coverage**: Are composite indexes aligned with the exact filter and sort columns in the hot-path query? Is the leftmost prefix rule respected?
- **Backfill Strategy**: If migrating historical data (e.g. 50M rows), will it be done in small batched transactions with throttle delays, or in one monolithic query that blows up the WAL/undo log?

### High-Yield Questions:
- *"If we rollback the deployment 10 minutes after releasing, will the old application code crash when reading rows written by the new schema?"*
- *"Are new columns nullable or given non-locking defaults during the transition phase?"*
- *"Have we checked foreign key constraints without concurrent index creation in Postgres/MySQL?"*

---

## Domain 5: Operational Blast Radius, Rollback & Observability

### Critical Inquiries:
- **Blast Radius**: If this feature fails completely in production, does it impact 100% of users, or can it be scoped to a specific cohort or tenant?
- **Kill-Switch / Feature Flag**: Can this code path be toggled off dynamically without requiring a redeployment or restart?
- **Observability**: What exact metric (SLI) signals that this system is malfunctioning? (e.g. error rate spike, p99 latency regression, queue lag).
- **Rollback Safety**: Can the feature be cleanly rolled back without requiring database restores or data patches?

### High-Yield Questions:
- *"How will on-call engineers distinguish between an issue in this new component and an outage in downstream infrastructure at 3 AM?"*
- *"What logs or traces are emitted on the failure path, and do they scrub PII and secrets while preserving the correlation ID?"*
