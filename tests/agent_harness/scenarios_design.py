"""
scenarios_design.py – Regression scenarios for the /design skill.

Coverage matrix (8 scenarios)
────────────────────────────────────────────────────────────────────────
 ID   Case                              Expected behaviour
────────────────────────────────────────────────────────────────────────
 DS01 Facts inspection (no lazy asks)  Autonomously reads code, no "what DB?"
 DS02 Frontier batched in rounds        All unblocked questions in one round
 DS03 Recommended stance required       Every question has ➡️ stance
 DS04 Ungrillable → spike delegated     Empirical q deferred to spike
 DS05 Confirmation gate enforced        ADR not written until user confirms
 DS06 Concurrency domain covered        Race windows & idempotency raised
 DS07 Five domains traversed            All 5 systems inquiry domains hit
 DS08 No conversational filler          Starts with fact inspection or Q round
────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import re
from tests.agent_harness.core import BehaviourCheck, Scenario, ScenarioFixture


def _check(name: str, fn, *, negate: bool = False, description: str = "") -> BehaviourCheck:
    return BehaviourCheck(name=name, predicate=fn, negate=negate, description=description)


# ---------------------------------------------------------------------------
# DS01 – Facts autonomously discovered; no lazy "what DB do you use?" asks
# ---------------------------------------------------------------------------

_DS01_FIXTURE = ScenarioFixture(
    files={
        "pyproject.toml": '[project]\nname = "shop"\n\n[tool.sqlalchemy]\nengine = "postgresql+psycopg2"\n',
        "models.py": 'from sqlalchemy import Column, Integer, String, create_engine\n',
        "README.md": "# Shop Service\nPostgreSQL 15, SQLAlchemy 2.x, Python 3.12\n",
    }
)

_DS01_STUB = """\
### 🏛️ Round 1 — Design Frontier

**Autonomous fact inspection complete:**
- Stack: PostgreSQL 15 (from `pyproject.toml` → `sqlalchemy` engine URL), SQLAlchemy 2.x, Python 3.12 (`README.md`).
- Models file exists at `models.py` with SQLAlchemy ORM.

No code-discoverable facts will be asked.

❓ **Q1** - **Consistency model for inventory deduction**: Should stock deduction be
pessimistic-locked (SELECT FOR UPDATE) or optimistic (version field + retry)?

➡️ **Recommended Stance**: Pessimistic lock via `SELECT FOR UPDATE` — inventory is
contended and retries on version conflicts create poor UX at checkout peak.

❓ **Q2** - **Oversell tolerance**: Is it acceptable to occasionally oversell by 1 unit
while a fix is deployed, or must oversell be zero at all times?

➡️ **Recommended Stance**: Zero oversell — deducting inside the same transaction as
the lock eliminates the race window entirely.
"""

SCENARIO_DS01 = Scenario(
    skill="design",
    id="design-DS01-facts-autonomously-inspected",
    description="Agent must read the existing stack from files, never ask 'what database do you use?'",
    prompt=(
        "Design the inventory deduction feature. The codebase is in this repo. "
        "Apply /design."
    ),
    fixture=_DS01_FIXTURE,
    stub_response=_DS01_STUB,
    checks=[
        _check(
            "facts discovered from files (not asked)",
            lambda t: t.contains(r"[Aa]utonomous.*fact|fact.*inspect|from.*pyproject|README|models\.py"),
            description="Must mention reading from existing files",
        ),
        _check(
            "does NOT ask what database is used",
            lambda t: not t.contains(r"what database|which database|what.*stack|what.*ORM"),
            negate=False,
            description="DB is discoverable — must not ask",
        ),
        _check(
            "does NOT ask about Python version",
            lambda t: not t.contains(r"what.*Python version|which.*Python"),
        ),
    ],
    tags=["critical", "facts-law"],
)


# ---------------------------------------------------------------------------
# DS02 – Entire frontier batched into a single round, not dripped one-by-one
# ---------------------------------------------------------------------------

_DS02_STUB = """\
### 🏛️ Round 1 — Design Frontier

❓ **Q1** - **Auth strategy**: JWT stateless tokens vs session cookies with Redis?
➡️ **Recommended Stance**: JWT with short expiry (15 min) + refresh token rotation.

❓ **Q2** - **Token storage client-side**: `HttpOnly` cookie vs `localStorage`?
➡️ **Recommended Stance**: `HttpOnly` cookie — eliminates XSS token theft.

❓ **Q3** - **Revocation model**: Token blacklist (Redis) vs short expiry only?
➡️ **Recommended Stance**: Short expiry + refresh rotation — avoids Redis dependency for read paths.

❓ **Q4** - **MFA requirement**: All users or only admin roles?
➡️ **Recommended Stance**: All users — regulatory baseline and negligible UX overhead with TOTP.

Please respond with your decisions (e.g., `1: Recommended, 2: localStorage, 3: Blacklist, 4: Admin only`).
"""

SCENARIO_DS02 = Scenario(
    skill="design",
    id="design-DS02-frontier-batched-in-rounds",
    description="All unblocked design questions must be batched into a single numbered round, never dripped one-by-one",
    prompt="Design the authentication system. Apply /design.",
    stub_response=_DS02_STUB,
    checks=[
        _check(
            "at least 2 questions in a single round",
            lambda t: len(re.findall(r"❓.*Q\d", t.raw)) >= 2,
            description="Multiple questions must appear in the same round block",
        ),
        _check(
            "single Round header (not multiple sequential rounds before user response)",
            lambda t: t.raw.count("Round 1") == 1 and t.raw.count("Round 2") == 0,
            description="Must not emit Round 2 without waiting for user response to Round 1",
        ),
        _check(
            "prompts user to respond with numbers",
            lambda t: t.contains(r"respond|decisions|e\.g\.|1:"),
            description="Must indicate rapid number-based response format",
        ),
    ],
    tags=["frontier-batching", "critical"],
)


# ---------------------------------------------------------------------------
# DS03 – Every question has a concrete Recommended Stance
# ---------------------------------------------------------------------------

_DS03_STUB = """\
### 🏛️ Round 1 — Design Frontier

❓ **Q1** - **Event sourcing vs CRUD**: Should order state be stored as event log or mutable rows?
➡️ **Recommended Stance**: CRUD with an append-only audit log — event sourcing adds
  replay complexity without benefit at current scale.

❓ **Q2** - **Saga vs 2PC for distributed commit**: How should the checkout span inventory + payment?
➡️ **Recommended Stance**: Choreography saga — 2PC requires a coordinator and is
  incompatible with the existing micro-service topology.

❓ **Q3** - **Dead-letter queue**: Where should failed saga compensation events land?
➡️ **Recommended Stance**: Dedicated SQS dead-letter with CloudWatch alarm — ops
  visibility without bespoke tooling.
"""

SCENARIO_DS03 = Scenario(
    skill="design",
    id="design-DS03-recommended-stance-required",
    description="Every design question must include a concrete ➡️ Recommended Stance",
    prompt="Design the checkout saga for order + inventory + payment. Apply /design.",
    stub_response=_DS03_STUB,
    checks=[
        _check(
            "every question has a Recommended Stance",
            lambda t: (
                lambda qs, stances: len(stances) >= len(qs) and len(qs) > 0
            )(
                re.findall(r"❓.*Q\d", t.raw),
                re.findall(r"Recommended Stance", t.raw),
            ),
            description="Number of stances must equal number of questions",
        ),
        _check(
            "stances are concrete (not 'it depends')",
            lambda t: not t.contains(r"Recommended Stance.*it depends|Recommended Stance.*either"),
            description="Stances must be concrete engineering recommendations",
        ),
    ],
    tags=["recommended-stance", "critical"],
)


# ---------------------------------------------------------------------------
# DS04 – Empirical / ungrillable question → spike delegated
# ---------------------------------------------------------------------------

_DS04_STUB = """\
### 🏛️ Round 1 — Design Frontier

❓ **Q1** - **Sharding key strategy**: Hash-based vs range-based sharding for 100M rows?
➡️ **Recommended Stance**: Hash-based on `user_id` — avoids range hotspots for
  write-heavy workloads.

❓ **Q2** - **Read throughput limit of PostgreSQL at p99**: Can one primary sustain
  10,000 read QPS at p99 < 50ms with the planned query set?

🔬 **Ungrillable — Spike Required**

This is an empirical question. Debate cannot determine the answer.
Delegating to a timeboxed spike in `.scratch/db_throughput_spike/`:

```bash
python3 "$SKILLS_DIR/spike/scripts/run_spike.py" \
  --name db_throughput \
  --hypothesis "Postgres primary sustains 10k QPS p99 < 50ms" \
  --scratch .scratch/
```

Design frontier paused on this branch until spike returns measured data.
"""

SCENARIO_DS04 = Scenario(
    skill="design",
    id="design-DS04-ungrillable-spike-delegated",
    description="Empirical questions (throughput limits) must be delegated to a spike, not debated",
    prompt=(
        "Design the database sharding strategy. We also need to know if PostgreSQL "
        "can sustain 10,000 QPS at p99 < 50ms. Apply /design."
    ),
    stub_response=_DS04_STUB,
    checks=[
        _check(
            "empirical question identified as ungrillable",
            lambda t: t.contains(r"[Uu]ngrillable|empirical|spike|[Ss]pike [Rr]equired"),
            description="Must flag the throughput question as requiring measurement",
        ),
        _check(
            "spike delegated, not debated",
            lambda t: t.contains(r"spike.*scratch|run_spike|timeboxed"),
            description="Must delegate to spike script, not speculate on the answer",
        ),
        _check(
            "design paused on spike branch",
            lambda t: t.contains(r"pause|waiting|returns.*data|until.*spike"),
            description="Design frontier must pause until spike data is available",
        ),
    ],
    tags=["ungrillable", "spike"],
)


# ---------------------------------------------------------------------------
# DS05 – Confirmation gate: ADR not compiled until user explicitly confirms
# ---------------------------------------------------------------------------

_DS05_STUB = """\
### 🏛️ Round 1 — Design Frontier

❓ **Q1** - **Cache invalidation strategy**: TTL-only vs event-driven invalidation?
➡️ **Recommended Stance**: Event-driven via pub/sub — TTL creates stale windows.

Please confirm your design decisions to proceed.

---

*ADR and OpenSpec package will be compiled once you have confirmed the design frontier.*
*Awaiting your confirmation before writing any specification documents.*
"""

SCENARIO_DS05 = Scenario(
    skill="design",
    id="design-DS05-confirmation-gate-enforced",
    description="ADR and OpenSpec must not be written until user explicitly confirms the design frontier",
    prompt="Design the caching strategy for user profiles. Apply /design.",
    stub_response=_DS05_STUB,
    checks=[
        _check(
            "ADR not written before user confirmation",
            lambda t: not t.contains(r"ADR-\d{4}|## Architecture Decision Record"),
            description="ADR must not appear before confirmation gate",
        ),
        _check(
            "OpenSpec not written before confirmation",
            # Look for actual file creation actions, not just mentions of the path name
            lambda t: not t.contains(r"Writing.*openspec|Created.*openspec|openspec.*written|proposal\.md.*written"),
            description="OpenSpec files must not be created before confirmation",
        ),
        _check(
            "confirmation gate explicitly mentioned",
            lambda t: t.contains(r"[Cc]onfirm|awaiting|once.*confirm"),
            description="Must explicitly wait for user to confirm",
        ),
    ],
    tags=["confirmation-gate", "critical"],
)




# ---------------------------------------------------------------------------
# DS06 – Concurrency domain surfaced (race windows, idempotency)
# ---------------------------------------------------------------------------

_DS06_STUB = """\
### 🏛️ Round 1 — Design Frontier

**2. Concurrency & Contention**

❓ **Q1** - **Double-submit protection**: Should payment submissions use an idempotency
  key to prevent double-charging when the client retries on timeout?

➡️ **Recommended Stance**: Yes — idempotency key per payment attempt (UUID in
  request header), stored server-side with 24h TTL. Standard Stripe / Adyen pattern.

❓ **Q2** - **Race window at checkout**: Between stock check and stock deduction,
  a concurrent request could oversell. Use SELECT FOR UPDATE or optimistic locking?

➡️ **Recommended Stance**: SELECT FOR UPDATE on the inventory row — eliminates
  the race window atomically within the transaction.
"""

SCENARIO_DS06 = Scenario(
    skill="design",
    id="design-DS06-concurrency-domain-covered",
    description="Concurrency & Contention domain must be surfaced: race windows, idempotency, lock strategy",
    prompt="Design the payment processing flow for checkout. Apply /design.",
    stub_response=_DS06_STUB,
    checks=[
        _check(
            "idempotency discussed",
            lambda t: t.contains(r"idempoten"),
            description="Payment design must raise idempotency",
        ),
        _check(
            "race window discussed",
            lambda t: t.contains(r"race window|race condition|concurrent|SELECT FOR UPDATE|optimistic"),
            description="Must surface the stock check vs deduction race",
        ),
        _check(
            "lock strategy recommended",
            lambda t: t.contains(r"SELECT FOR UPDATE|pessimistic|optimistic|lock"),
        ),
    ],
    tags=["concurrency", "idempotency"],
)


# ---------------------------------------------------------------------------
# DS07 – All 5 systems inquiry domains traversed
# ---------------------------------------------------------------------------

_DS07_STUB = """\
### 🏛️ Round 1 — Design Frontier

**1. State & Invariants**
❓ **Q1** - **Single source of truth for subscription status**: billing service or user service?
➡️ **Recommended Stance**: Billing service owns it; user service reads via event.

**2. Concurrency & Contention**
❓ **Q2** - **Concurrent renewal and cancellation**: Can a renewal and cancellation race?
➡️ **Recommended Stance**: Idempotency key + state machine transitions enforced at DB layer.

**3. Failure Domains & Chaos**
❓ **Q3** - **Payment provider outage**: Retry with backoff or fail-open with grace period?
➡️ **Recommended Stance**: Retry with exponential backoff + jitter; grace period of 3 days for existing subscribers.

**4. Data Evolution & Schema**
❓ **Q4** - **Adding `trial_ends_at` column**: Zero-downtime migration strategy?
➡️ **Recommended Stance**: Expand-contract: add nullable, backfill in batches, add NOT NULL constraint after.

**5. Operational Blast Radius**
❓ **Q5** - **Feature flag for new billing engine**: Kill-switch granularity?
➡️ **Recommended Stance**: Per-tenant flag in LaunchDarkly — allows rolling back a single tenant without full rollout pause.
"""

SCENARIO_DS07 = Scenario(
    skill="design",
    id="design-DS07-five-domains-traversed",
    description="All 5 systems inquiry domains must appear in the design round",
    prompt="Design the subscription billing renewal system. Apply /design.",
    stub_response=_DS07_STUB,
    checks=[
        _check(
            "State & Invariants domain present",
            lambda t: t.contains(r"State.*Invariant|source of truth|invariant"),
        ),
        _check(
            "Concurrency & Contention domain present",
            lambda t: t.contains(r"Concurrency|race|contention|idempoten"),
        ),
        _check(
            "Failure Domains domain present",
            lambda t: t.contains(r"Failure Domain|backoff|outage|chaos|grace period"),
        ),
        _check(
            "Data Evolution domain present",
            lambda t: t.contains(r"Data Evolution|Schema|migration|expand.contract"),
        ),
        _check(
            "Operational Blast Radius domain present",
            lambda t: t.contains(r"Blast Radius|feature flag|kill.switch|SLI"),
        ),
    ],
    tags=["five-domains", "systems-inquiry"],
)


# ---------------------------------------------------------------------------
# DS08 – No conversational filler
# ---------------------------------------------------------------------------

_DS08_STUB = """\
**Autonomous fact inspection:**
Reading existing schemas and configs... no existing notification service found.

### 🏛️ Round 1 — Design Frontier

❓ **Q1** - **Delivery channel priority**: Email-only vs email + SMS + push?
➡️ **Recommended Stance**: Email + push; SMS only for critical alerts (cost).
"""

SCENARIO_DS08 = Scenario(
    skill="design",
    id="design-DS08-no-conversational-filler",
    description="Agent must start with fact inspection or a frontier round, not a greeting",
    prompt="Design the notification service. Apply /design.",
    stub_response=_DS08_STUB,
    checks=[
        _check(
            "no conversational filler",
            lambda t: not t.has_conversational_filler(),
        ),
        _check(
            "opens with inspection or round header",
            lambda t: t.raw.lstrip().startswith(
                ("**", "#", "🏛️", "Autonomous", "Reading")
            ),
            description="Must open with structured content",
        ),
    ],
    tags=["ux", "filler"],
)


# ---------------------------------------------------------------------------
# Exported list
# ---------------------------------------------------------------------------

DESIGN_SCENARIOS = [
    SCENARIO_DS01,
    SCENARIO_DS02,
    SCENARIO_DS03,
    SCENARIO_DS04,
    SCENARIO_DS05,
    SCENARIO_DS06,
    SCENARIO_DS07,
    SCENARIO_DS08,
]
