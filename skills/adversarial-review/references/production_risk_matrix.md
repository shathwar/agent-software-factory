# Production & Deployment Risk Matrix

A checklist for evaluating operational impact, deployment safety, and blast radius before shipping code to production.

---

## 1. High-Impact Operational Hazards

- **Financial / Trading Hazards**:
  - Double exit / double order placement.
  - Premature stop-loss cancellation leading to unhedged market exposure.
  - Stale quotes triggering false trailing-stop square-offs.
  - Reversal of sentiment or direction causing rapid churn.
- **Database & Data Integrity**:
  - Applied Flyway/Liquibase migration modifying an existing historical migration (causes checksum mismatch).
  - Migration adding a table column with a heavy lock or lack of index on high-cardinality query paths.
  - Foreign key constraint violations or missing cascade settings.
- **Network & Resource Exhaustion**:
  - Rapid loops calling broker REST APIs causing IP-level rate-limiting (429).
  - Unbounded Redis stream reads without `COUNT` or unacknowledged message backlog (`PEL` explosion).
  - Connection pool exhaustion (database, Redis, HTTP connection pools).

---

## 2. Contract Drift & Backward Compatibility

- **API Endpoints**:
  - Did response status codes change (e.g. 404 changed to 400 or empty 200)?
  - Were fields renamed or changed from required to optional?
  - Are query parameters or headers expected by existing clients (e.g. UI, upstream microservices) preserved?
- **Streaming Payloads (Redis Streams / Kafka / RabbitMQ)**:
  - Do downstream consumers expect fields that were modified or omitted?
  - Can consumers parse messages produced by both old and new versions during rolling deployments?
- **Serialization & Reflection (Native Image / Serde)**:
  - In GraalVM Native Image (or Jackson / Micronaut Serde), are newly created DTOs and models annotated with `@Serdeable` and `@Introspected`?

---

## 3. Environment & Configuration Safety

- **New Configuration Keys**:
  - Were new environment variables or application properties added? Are default fallback values provided so existing deployments don't crash on startup?
- **Timezones & Clock Drift**:
  - Operational market time checks must use explicit time zones (`Asia/Kolkata` / `ZoneId`) and not rely on the local container or host system default time zone.
  - Persisted database timestamps must use UTC (`Instant`).
- **Telemetry & Observability**:
  - Are metrics incremented on both success and failure branches?
  - Are critical operations logged at `INFO` or `WARN`/`ERROR` with contextual identifiers (`orderId`, `userId`, `symbol`)?
