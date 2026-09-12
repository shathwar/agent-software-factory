# Architecture Decision Record (ADR) Template

This document defines the canonical specification format produced at the conclusion of a `/design` session. This ADR serves as the immutable ground truth for implementation and acts as the direct specification input for [`audit`](../../audit/SKILL.md) Stage 0 (Spec Alignment).

---

```markdown
# ADR-[NNNN]: [Short, Descriptive Title]

- **Status**: [PROPOSED / ACCEPTED / SUPERSEDED]
- **Date**: [YYYY-MM-DD]
- **Architects**: [User & Principal Systems Architect]
- **Target Components**: [e.g. OrderExecutionService, Postgres, RedisStreams]
- **Related Issues / PRDs**: [e.g. #123, PROJ-456]

---

## 1. Context & Problem Statement
*Describe the business requirement, technical challenge, and environmental constraints driving this architecture. Detail existing system limitations.*

---

## 2. Decision Drivers
*What technical forces and constraints guided the decision tree?*
- Driver 1: e.g. Maximum tolerable latency (p99 < 15ms)
- Driver 2: e.g. High concurrent write throughput (5,000 TPS)
- Driver 3: e.g. Zero data loss on broker failure (At-Least-Once delivery with idempotency)
- Driver 4: e.g. Zero-downtime deployment compatibility

---

## 3. Considered Options
*What architectural alternatives were explored during the design interview?*

### Option A: [Description]
- **Pros**: ...
- **Cons**: ...

### Option B: [Description] *(Chosen)*
- **Pros**: ...
- **Cons**: ...

---

## 4. Decision Outcome & Architecture Specification

### 4.1. Chosen Architecture
*Detailed explanation of the agreed-upon design and workflow.*

### 4.2. Invariants & Guarantees
- **State & Consistency**: [e.g. Single source of truth in Postgres; transactional outbox pattern for Kafka publishing]
- **Concurrency & Locking**: [e.g. Optimistic lock via version column; redis-based idempotency key with 24h TTL]
- **Resilience & Timeouts**: [e.g. 500ms connection timeout, 2000ms read timeout, exponential backoff (initial 100ms, max 3 retries, full jitter)]
- **Data & Migration**: [e.g. Add nullable column first; dual-write; backfill in batches of 1,000 rows; add NOT NULL constraint concurrently]
- **Blast Radius & Rollback**: [e.g. Gated behind feature flag `enable_order_v2`; immediate instant disable if error rate exceeds 1%]

---

## 5. Consequences & Trade-offs
- **Positive Consequences**: [What becomes easier, safer, or faster]
- **Negative Consequences / Accepted Technical Debt**: [Known limitations or operational overhead accepted]

---

## 6. Downstream Verification Criteria (For `audit`)

*These explicit acceptance criteria will be verified by the Principal Reviewer in `audit` Stage 0 (Spec Alignment) and Stages 1–3:*

- [ ] Criterion 1: [Specific behavioral or contract expectation]
- [ ] Criterion 2: [Concurrency or lock handling check]
- [ ] Criterion 3: [Error handling / timeout check]
- [ ] Criterion 4: [Database migration index & safety check]
```
