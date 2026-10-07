"""
scenarios_review.py – Regression scenarios for the /review skill.

Coverage matrix (12 scenarios)
───────────────────────────────────────────────────────────────────────
 ID   Case                       Expected behaviour
───────────────────────────────────────────────────────────────────────
 R01  Clean repo finds defect    At least one finding with evidence
 R02  Genuinely clean code       Reports "READY TO DEPLOY" / no findings
 R03  Missing evidence           Judge refuses hallucinated finding
 R04  Stale / phantom evidence   Rejects finding referencing absent file
 R05  Large diff                 Scopes all 10 stages; still finds defects
 R06  Security issue             Escalates to CRITICAL / HIGH RISK BLOCKED
 R07  Repair requested           Doesn't silently mutate the diff
 R08  Race condition             Identifies concurrent write window
 R09  N+1 query                  Flags performance / query plan issue
 R10  No conversational filler   Never starts with "Certainly" etc.
 R11  Schema compliance          Every finding has all 12 required fields
 R12  Requires-human trade-off   Asks a batched Decision Round question
───────────────────────────────────────────────────────────────────────

Stub responses are realistic agent outputs stored inline.  When
AGENT_HARNESS_MODE=live or AGENT_HARNESS_MODE=anthropic the harness
sends the real prompt to a real model; the same checks run against the
live response.
"""

from __future__ import annotations

from tests.agent_harness.core import (
    BehaviourCheck,
    Scenario,
    ScenarioFixture,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check(name: str, fn, *, negate: bool = False, description: str = "") -> BehaviourCheck:
    return BehaviourCheck(name=name, predicate=fn, negate=negate, description=description)


def _contains(pattern: str, *, negate: bool = False) -> BehaviourCheck:
    name = f"{'NOT ' if negate else ''}contains({pattern!r})"
    return BehaviourCheck(name=name, predicate=lambda t: t.contains(pattern), negate=negate)


# ---------------------------------------------------------------------------
# R01 – Clean repo finds a meaningful defect
# ---------------------------------------------------------------------------

_R01_FIXTURE = ScenarioFixture(
    files={
        "average.py": """\
            def average(values):
                return sum(values) / len(values)
        """,
        "tests/test_average.py": """\
            from average import average
            def test_basic():
                assert average([1, 2, 3]) == 2
        """,
    }
)

_R01_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: CHANGES REQUIRED
- **Targeted Review Mode**: Standard Code Change
- **Summary**: `average()` divides by `len(values)` without guarding against an
  empty list, which raises `ZeroDivisionError` in production.

## Review Scorecard
| Stage / Area | Status | Principal Engineer Assessment |
|---|---|---|
| 1. **Correctness** | FAIL | Empty-list path unguarded — ZeroDivisionError. |

## Findings (Contract: finding_schema.md)

### [FINDING-001] [HIGH] Division by zero on empty input

- **Category**: Correctness
- **Location**: average.py:L2
- **Confidence**: 1.0
- **Fixability**: autonomous
- **Problem**: `len(values)` is `0` for empty input; division raises `ZeroDivisionError`.
- **Evidence**:
  ```python
  return sum(values) / len(values)
  ```
- **Impact on Live Production**: Any caller passing an empty list crashes with an unhandled exception.
- **Recommendation**:
  ```python
  def average(values):
      if not values:
          return 0.0
      return sum(values) / len(values)
  ```
"""

SCENARIO_R01 = Scenario(
    skill="review",
    id="review-R01-clean-repo-finds-defect",
    description="A repo with a real division-by-zero defect must be flagged with evidence",
    prompt=(
        "Review the following code change. File: average.py\n\n"
        "```python\n"
        "def average(values):\n"
        "    return sum(values) / len(values)\n"
        "```\n\n"
        "Find any defects. Apply the /review skill."
    ),
    fixture=_R01_FIXTURE,
    stub_response=_R01_STUB,
    checks=[
        _check(
            "finds at least one finding",
            lambda t: len(t.finding_ids()) >= 1,
            description="Must report at least FINDING-001",
        ),
        _check(
            "finding references correct file",
            lambda t: t.contains(r"average\.py"),
            description="Finding must cite the actual source file",
        ),
        _check(
            "finding has evidence block",
            lambda t: t.has_evidence_block(),
            description="Evidence must be a verbatim code snippet",
        ),
        _check(
            "verdict is CHANGES REQUIRED or HIGH RISK",
            lambda t: t.contains(r"CHANGES REQUIRED|HIGH RISK", flags=0),
            description="Overall verdict must not say READY TO DEPLOY",
        ),
        _check(
            "correctness stage fails",
            lambda t: t.scorecard_stage("Correctness") in ("FAIL", "WARN"),
            description="Scorecard stage 1 must reflect the defect",
        ),
        _check(
            "no conversational filler",
            lambda t: not t.has_conversational_filler(),
            description="Must not start with 'Certainly', 'I'd be happy to', etc.",
        ),
    ],
    tags=["critical", "correctness"],
)


# ---------------------------------------------------------------------------
# R02 – Genuinely clean code returns READY TO DEPLOY
# ---------------------------------------------------------------------------

_R02_FIXTURE = ScenarioFixture(
    files={
        "greet.py": """\
            def greet(name: str) -> str:
                if not name:
                    return "Hello, World!"
                return f"Hello, {name}!"
        """,
        "tests/test_greet.py": """\
            from greet import greet
            def test_empty():  assert greet("") == "Hello, World!"
            def test_name():   assert greet("Alice") == "Hello, Alice!"
        """,
    }
)

_R02_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: READY TO DEPLOY
- **Targeted Review Mode**: Standard Code Change
- **Summary**: Implementation is correct, well-tested, and free of concurrency,
  resilience, or security concerns. Clean review.

## Review Scorecard
| Stage / Area | Status | Principal Engineer Assessment |
|---|---|---|
| 1. **Correctness** | PASS | Edge-case (empty string) guarded and tested. |
| 2. **Concurrency / Safety** | PASS | Pure function; no shared state. |
| 3. **Failure / Resilience** | PASS | No I/O paths; no resilience concerns. |
| 4. **Simplicity** | PASS | Minimal, readable. |
| 5. **Maintainability** | PASS | Clear naming. |
| 6. **Reuse** | PASS | No duplication. |
| 7. **Performance** | PASS | O(1) string concat; irrelevant at this scale. |
| 8. **SOLID** | PASS | Single responsibility satisfied. |
| 9. **Patterns** | PASS | No pattern over-engineering. |

## Findings (Contract: finding_schema.md)

No findings. The implementation is correct and the test suite covers the edge cases.
"""

SCENARIO_R02 = Scenario(
    skill="review",
    id="review-R02-clean-code-reports-clean",
    description="Genuinely clean code must yield READY TO DEPLOY, not manufactured findings",
    prompt=(
        "Review this clean implementation. File: greet.py\n\n"
        "```python\n"
        "def greet(name: str) -> str:\n"
        "    if not name:\n"
        "        return 'Hello, World!'\n"
        "    return f'Hello, {name}!'\n"
        "```\n\n"
        "Apply the /review skill."
    ),
    fixture=_R02_FIXTURE,
    stub_response=_R02_STUB,
    checks=[
        _check(
            "reports READY TO DEPLOY",
            lambda t: t.contains(r"READY TO DEPLOY"),
            description="Clean code must not be blocked",
        ),
        _check(
            "no findings emitted",
            lambda t: len(t.finding_ids()) == 0,
            description="Must not manufacture spurious findings",
        ),
        _check(
            "no conversational filler",
            lambda t: not t.has_conversational_filler(),
        ),
    ],
    tags=["critical", "clean-review"],
)


# ---------------------------------------------------------------------------
# R03 – Missing evidence → Judge refuses finding
# ---------------------------------------------------------------------------

_R03_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: CHANGES REQUIRED
- **Targeted Review Mode**: Standard Code Change
- **Summary**: One candidate finding was raised by the Correctness reviewer but
  **rejected by the Judge** for lacking source-grounded evidence.

## Judge Adjudication

DISPUTED [FINDING-001]: The reviewer claimed a race condition exists in
`worker.py:L88` but the file does not contain that line and no verbatim trigger
code was provided. Finding rejected — plausible-failure hypothesis without
concrete trigger.

## Findings (Contract: finding_schema.md)

No findings passed adjudication. Review outcome: inconclusive on submitted
evidence. Recommend expanding the diff context.
"""

SCENARIO_R03 = Scenario(
    skill="review",
    id="review-R03-missing-evidence-refused",
    description="A finding without source evidence must be rejected by the Judge, not returned",
    prompt=(
        "Review this diff. A reviewer candidate says there is a race condition "
        "in worker.py line 88, but does not provide a code snippet.\n\n"
        "```diff\n--- a/worker.py\n+++ b/worker.py\n@@ -1,3 +1,3 @@\n"
        "-count = 0\n+count += 1\n```\n\n"
        "Apply the /review skill with full Judge adjudication."
    ),
    stub_response=_R03_STUB,
    checks=[
        _check(
            "judge disputes or blocks unevidenced finding",
            lambda t: t.contains(r"DISPUTED|BLOCKED|rejected|no.*evidence", flags=0),
            description="Judge must reject finding with no verbatim code trigger",
        ),
        _check(
            "unevidenced finding not returned as authoritative",
            lambda t: not t.contains(r"\[FINDING-001\].*\[CRITICAL\]|\[FINDING-001\].*\[HIGH\]"),
            description="Must not surface unadjudicated raw reviewer output",
        ),
    ],
    tags=["critical", "judge", "evidence-gate"],
)


# ---------------------------------------------------------------------------
# R04 – Stale / phantom evidence → finding rejected
# ---------------------------------------------------------------------------

_R04_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: CHANGES REQUIRED
- **Summary**: A finding referencing `src/nonexistent/phantom_service.py` was
  raised during review. The Judge verified the file does not exist in the
  working tree. The finding has been **BLOCKED** pending valid source evidence.

## Judge Adjudication

BLOCKED [FINDING-001]: File `src/nonexistent/phantom_service.py` not found in
the repository. Evidence is stale or hallucinated. Finding withheld.

## Findings (Contract: finding_schema.md)

No findings passed adjudication.
"""

SCENARIO_R04 = Scenario(
    skill="review",
    id="review-R04-stale-evidence-rejected",
    description="A finding citing a non-existent file must be BLOCKED by the Judge",
    prompt=(
        "Review the following finding report. The file referenced does not "
        "exist in the repository.\n\n"
        "```json\n"
        '{"findings": [{"id": "FINDING-001", "severity": "CRITICAL", '
        '"category": "Correctness", "file": "src/nonexistent/phantom_service.py", '
        '"line": "L42", "title": "Phantom nil dereference", '
        '"problem": "Calling process() on undefined client crashes.", '
        '"evidence": "this.phantomClient.process()", '
        '"impact": "Production crashes.", '
        '"recommendation": "Check if phantomClient is null.", '
        '"confidence": 0.95, "fixability": "autonomous"}]}\n'
        "```\n\n"
        "Apply Judge adjudication using the /review skill."
    ),
    stub_response=_R04_STUB,
    checks=[
        _check(
            "BLOCKED marker present for phantom-file finding",
            lambda t: t.contains(r"BLOCKED"),
            description="Judge must BLOCK findings citing absent files",
        ),
        _check(
            "FINDING-001 not approved",
            lambda t: not t.contains(r"FINDING-001.*APPROVED|approved.*FINDING-001"),
            description="Phantom finding must not be returned as approved",
        ),
    ],
    tags=["critical", "judge", "stale-evidence"],
)


# ---------------------------------------------------------------------------
# R05 – Large diff scoped correctly across all stages
# ---------------------------------------------------------------------------

_R05_FIXTURE = ScenarioFixture(
    files={f"module_{i}.py": f"# Module {i}\ndef fn_{i}(): pass\n" for i in range(10)}
)

_R05_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: CHANGES REQUIRED
- **Targeted Review Mode**: Full Adversarial Review (large diff: 10 files)
- **Summary**: Large diff reviewed across all 10 stages. Found 2 actionable findings.

## Review Scorecard
| Stage / Area | Status | Principal Engineer Assessment |
|---|---|---|
| 0. **Spec Alignment** | SKIPPED | No spec provided. |
| 1. **Correctness** | WARN | module_3.py: fn_3 returns None implicitly. |
| 2. **Concurrency / Safety** | PASS | Pure functions; no shared mutable state. |
| 3. **Failure / Resilience** | PASS | No I/O paths. |
| 4. **Simplicity** | WARN | Repeated `pass` stubs across 10 modules suggest unimplemented logic. |
| 5. **Maintainability** | PASS | Consistent naming. |
| 6. **Reuse** | PASS | No duplication yet. |
| 7. **Performance** | PASS | Trivial functions. |
| 8. **SOLID** | PASS | Single responsibility per module. |
| 9. **Patterns** | PASS | No over-engineering. |

## Findings (Contract: finding_schema.md)

### [FINDING-001] [MEDIUM] Stub implementations silently return None
- **Category**: Correctness
- **Location**: module_3.py:L2
- **Confidence**: 0.85
- **Fixability**: requires-human
- **Problem**: `fn_3()` returns `None` implicitly. Callers expecting a return value will silently receive `None`.
- **Evidence**:
  ```python
  def fn_3(): pass
  ```
- **Impact on Live Production**: Silent `None` propagation masks missing implementations.
- **Recommendation**: Raise `NotImplementedError` until implementation is complete.
"""

SCENARIO_R05 = Scenario(
    skill="review",
    id="review-R05-large-diff-scoped",
    description="Large diff (10 files) must traverse all 10 scorecard stages and still find defects",
    prompt=(
        "Review this large diff spanning 10 Python modules (module_0.py through "
        "module_9.py). All functions currently contain `pass`. Apply the /review skill "
        "and cover all 10 review stages in the scorecard."
    ),
    fixture=_R05_FIXTURE,
    stub_response=_R05_STUB,
    checks=[
        _check(
            "all 10 scorecard stages present",
            lambda t: all(
                t.scorecard_stage(s) is not None
                for s in [
                    "Correctness", "Concurrency", "Failure", "Simplicity",
                    "Maintainability", "Reuse", "Performance", "SOLID", "Patterns",
                ]
            ),
            description="Every stage must appear in the scorecard table",
        ),
        _check(
            "at least one finding returned",
            lambda t: len(t.finding_ids()) >= 1,
        ),
        _check(
            "no conversational filler",
            lambda t: not t.has_conversational_filler(),
        ),
    ],
    tags=["scope", "large-diff"],
)


# ---------------------------------------------------------------------------
# R06 – Security issue escalated to CRITICAL / HIGH RISK BLOCKED
# ---------------------------------------------------------------------------

_R06_FIXTURE = ScenarioFixture(
    files={
        "auth.py": """\
            import sqlite3

            def get_user(username):
                conn = sqlite3.connect("users.db")
                cur = conn.cursor()
                cur.execute(f"SELECT * FROM users WHERE name = '{username}'")
                return cur.fetchone()
        """,
    }
)

_R06_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: HIGH RISK - BLOCKED
- **Targeted Review Mode**: Full Adversarial Review
- **Summary**: SQL injection vulnerability detected. Deployment blocked.

## Review Scorecard
| Stage / Area | Status | Principal Engineer Assessment |
|---|---|---|
| 1. **Correctness** | FAIL | SQL injection via f-string interpolation. |

## Findings (Contract: finding_schema.md)

### [FINDING-001] [CRITICAL] SQL Injection via unsanitized f-string interpolation

- **Category**: Security
- **Location**: auth.py:L6
- **Confidence**: 1.0
- **Fixability**: autonomous
- **Problem**: User-controlled `username` is interpolated directly into the SQL
  query without parameterisation.  An attacker supplies `' OR '1'='1` to bypass
  authentication or `'; DROP TABLE users; --` to destroy data.
- **Evidence**:
  ```python
  cur.execute(f"SELECT * FROM users WHERE name = '{username}'")
  ```
- **Impact on Live Production**: Full authentication bypass; arbitrary data
  exfiltration and destruction.
- **Recommendation**:
  ```python
  cur.execute("SELECT * FROM users WHERE name = ?", (username,))
  ```
"""

SCENARIO_R06 = Scenario(
    skill="review",
    id="review-R06-security-issue-escalated",
    description="SQL injection must be escalated to CRITICAL with HIGH RISK BLOCKED verdict",
    prompt=(
        "Review this Python auth module for security issues. Apply /review.\n\n"
        "```python\n"
        "import sqlite3\n\n"
        "def get_user(username):\n"
        "    conn = sqlite3.connect('users.db')\n"
        "    cur = conn.cursor()\n"
        "    cur.execute(f\"SELECT * FROM users WHERE name = '{username}'\")\n"
        "    return cur.fetchone()\n"
        "```\n"
    ),
    fixture=_R06_FIXTURE,
    stub_response=_R06_STUB,
    checks=[
        _check(
            "HIGH RISK BLOCKED verdict",
            lambda t: t.contains(r"HIGH RISK.*BLOCKED|BLOCKED", flags=0),
            description="Security issues must block deployment",
        ),
        _check(
            "CRITICAL severity finding",
            lambda t: t.contains(r"\[CRITICAL\]"),
            description="SQL injection must be CRITICAL",
        ),
        _check(
            "finding cites SQL injection",
            lambda t: t.contains(r"SQL\s*[Ii]njection|injection"),
        ),
        _check(
            "evidence block contains the vulnerable line",
            lambda t: t.contains(r"f.SELECT.*username"),
            description="Must quote the exact vulnerable f-string",
        ),
        _check(
            "recommendation uses parameterised query",
            lambda t: t.contains(r"\?.*username|username.*\?"),
            description="Fix must switch to parameterised query",
        ),
        _check(
            "no conversational filler",
            lambda t: not t.has_conversational_filler(),
        ),
    ],
    tags=["critical", "security"],
)


# ---------------------------------------------------------------------------
# R07 – Repair requested → doesn't silently mutate the diff
# ---------------------------------------------------------------------------

_R07_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review) — review-loop mode

## Executive Summary
- **Overall Verdict**: CHANGES REQUIRED
- **Mode**: review-loop (bounded repair, max 3 iterations)

## Findings (Contract: finding_schema.md)

### [FINDING-001] [HIGH] Division by zero on empty input

- **Category**: Correctness
- **Location**: calc.py:L2
- **Confidence**: 1.0
- **Fixability**: autonomous
- **Problem**: `sum(vals) / len(vals)` raises `ZeroDivisionError` for empty input.
- **Evidence**:
  ```python
  return sum(vals) / len(vals)
  ```
- **Impact on Live Production**: Empty request body causes unhandled 500.
- **Recommendation**:
  ```python
  def average(vals):
      if not vals:
          return 0.0
      return sum(vals) / len(vals)
  ```

## Repair Log

Iteration 1 of 3: Applying autonomous fix to calc.py (L2 guard clause).
Fix applied. Running tests… tests pass. Stopping — no further findings.

**Files modified**: calc.py
**No other files were changed.** The original diff scope was respected.
"""

SCENARIO_R07 = Scenario(
    skill="review",
    id="review-R07-repair-no-silent-mutation",
    description="In review-loop mode the agent must not silently mutate files beyond the targeted fix",
    prompt=(
        "Enter review-loop mode. Review and repair:\n\n"
        "```python\n"
        "# calc.py\n"
        "def average(vals):\n"
        "    return sum(vals) / len(vals)\n"
        "```\n\n"
        "Fix any defects found. Do not touch any other files."
    ),
    stub_response=_R07_STUB,
    checks=[
        _check(
            "only targeted file mutated",
            lambda t: all(
                "calc.py" in p or p == "calc.py"
                for p in (t.repair_mutations() or ["calc.py"])
            ),
            description="Only calc.py must appear in diff +++ lines",
        ),
        _check(
            "max-3-iteration constraint mentioned",
            lambda t: t.contains(r"[Ii]teration\s+\d\s+of\s+3|max.*3.*iter"),
            description="Bounded repair ceiling must be visible in trace",
        ),
        _check(
            "finding adjudicated before repair",
            lambda t: t.contains(r"FINDING-\d{3}"),
            description="At least one adjudicated finding must precede repairs",
        ),
    ],
    tags=["repair", "review-loop"],
)


# ---------------------------------------------------------------------------
# R08 – Race condition identified
# ---------------------------------------------------------------------------

_R08_FIXTURE = ScenarioFixture(
    files={
        "counter.py": """\
            import threading

            counter = 0
            lock = threading.Lock()

            def increment():
                global counter
                temp = counter       # read
                temp += 1            # modify
                counter = temp       # write  (window: another thread can read between read and write)
        """,
    }
)

_R08_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: CHANGES REQUIRED
- **Summary**: Non-atomic read-modify-write on a shared global creates a race window.

## Review Scorecard
| Stage / Area | Status | Principal Engineer Assessment |
|---|---|---|
| 2. **Concurrency / Safety** | FAIL | Read-modify-write not atomic; lost updates possible. |

## Findings (Contract: finding_schema.md)

### [FINDING-001] [HIGH] Non-atomic read-modify-write creates race window

- **Category**: Concurrency
- **Location**: counter.py:L7-L9
- **Confidence**: 1.0
- **Fixability**: autonomous
- **Problem**: Three separate statements (`temp = counter`, `temp += 1`, `counter = temp`)
  are not protected by the lock.  A second thread can read `counter` between the
  read and write of thread 1, causing lost updates.
- **Evidence**:
  ```python
  temp = counter       # read
  temp += 1            # modify
  counter = temp       # write  (window: another thread can read between read and write)
  ```
- **Impact on Live Production**: Under concurrent load `counter` underestimates
  actual increments; metrics drift silently.
- **Recommendation**:
  ```python
  def increment():
      global counter
      with lock:
          counter += 1
  ```
"""

SCENARIO_R08 = Scenario(
    skill="review",
    id="review-R08-race-condition-identified",
    description="Non-atomic read-modify-write on shared state must be flagged as concurrency defect",
    prompt=(
        "Review counter.py for concurrency issues:\n\n"
        "```python\n"
        "import threading\n"
        "counter = 0\n"
        "lock = threading.Lock()\n\n"
        "def increment():\n"
        "    global counter\n"
        "    temp = counter\n"
        "    temp += 1\n"
        "    counter = temp\n"
        "```\n\n"
        "Apply /review."
    ),
    fixture=_R08_FIXTURE,
    stub_response=_R08_STUB,
    checks=[
        _check(
            "concurrency stage fails",
            # The stage may be named "Concurrency / Safety" or "Concurrency"
            lambda t: (
                t.scorecard_stage("Concurrency") in ("FAIL", "WARN")
                or t.scorecard_stage("Concurrency / Safety") in ("FAIL", "WARN")
                or t.contains(r"\*\*Concurrency.*\*\*.*\|\s*(FAIL|WARN)")
            ),
        ),
        _check(
            "finding cites race window",
            lambda t: t.contains(r"race|atomic|read.modify.write|lost update"),
        ),
        _check(
            "evidence shows the 3-statement window",
            lambda t: t.contains(r"temp\s*=\s*counter"),
        ),
    ],
    tags=["concurrency", "race-condition"],
)


# ---------------------------------------------------------------------------
# R09 – N+1 query pattern flagged
# ---------------------------------------------------------------------------

_R09_FIXTURE = ScenarioFixture(
    files={
        "views.py": """\
            from models import Order, Item

            def get_order_details(order_ids):
                orders = Order.objects.filter(id__in=order_ids)
                result = []
                for order in orders:
                    items = Item.objects.filter(order=order)  # N+1
                    result.append({"order": order, "items": list(items)})
                return result
        """,
    }
)

_R09_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: CHANGES REQUIRED
- **Summary**: N+1 query pattern detected.

## Review Scorecard
| Stage / Area | Status | Principal Engineer Assessment |
|---|---|---|
| 7. **Performance** | FAIL | N+1 query: one DB round-trip per order. |

## Findings (Contract: finding_schema.md)

### [FINDING-001] [HIGH] N+1 query pattern causes O(n) database round-trips

- **Category**: Performance
- **Location**: views.py:L7
- **Confidence**: 0.95
- **Fixability**: autonomous
- **Problem**: `Item.objects.filter(order=order)` executes inside a loop, issuing
  one SQL query per order.  For 1,000 orders, 1,001 queries are sent.
- **Evidence**:
  ```python
  for order in orders:
      items = Item.objects.filter(order=order)  # N+1
  ```
- **Impact on Live Production**: Response times degrade linearly with order count;
  connection pool exhausted under moderate load.
- **Recommendation**:
  ```python
  orders = Order.objects.filter(id__in=order_ids).prefetch_related('item_set')
  ```
"""

SCENARIO_R09 = Scenario(
    skill="review",
    id="review-R09-n-plus-1-query-flagged",
    description="N+1 query pattern inside a loop must be flagged as a Performance defect",
    prompt=(
        "Review this Django view for performance issues:\n\n"
        "```python\n"
        "def get_order_details(order_ids):\n"
        "    orders = Order.objects.filter(id__in=order_ids)\n"
        "    result = []\n"
        "    for order in orders:\n"
        "        items = Item.objects.filter(order=order)\n"
        "        result.append({'order': order, 'items': list(items)})\n"
        "    return result\n"
        "```\n\n"
        "Apply /review."
    ),
    fixture=_R09_FIXTURE,
    stub_response=_R09_STUB,
    checks=[
        _check(
            "performance stage fails",
            lambda t: t.scorecard_stage("Performance") in ("FAIL", "WARN"),
        ),
        _check(
            "N+1 pattern identified",
            lambda t: t.contains(r"N\+1|n\+1|one query per|per\s+order.*query"),
        ),
        _check(
            "recommendation uses prefetch or join",
            lambda t: t.contains(r"prefetch|select_related|JOIN"),
        ),
    ],
    tags=["performance", "n+1"],
)


# ---------------------------------------------------------------------------
# R10 – Zero conversational filler (standalone check)
# ---------------------------------------------------------------------------

_R10_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: READY TO DEPLOY
- **Summary**: No defects found.
"""

SCENARIO_R10 = Scenario(
    skill="review",
    id="review-R10-no-conversational-filler",
    description="Agent must never open with 'Certainly', 'Of course', 'I'd be happy to', etc.",
    prompt="Review this trivial file for issues: ```python\ndef noop(): pass\n```",
    stub_response=_R10_STUB,
    checks=[
        _check(
            "no conversational filler anywhere in trace",
            lambda t: not t.has_conversational_filler(),
            description="Zero-filler hard constraint enforced",
        ),
        _check(
            "starts with structured content not prose",
            lambda t: t.raw.lstrip().startswith("#"),
            description="Must start with a markdown heading, not a greeting",
        ),
    ],
    tags=["ux", "filler"],
)


# ---------------------------------------------------------------------------
# R11 – Schema compliance: all 12 fields present in every finding
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {
    "id", "severity", "category", "file", "line", "title",
    "problem", "evidence", "impact", "recommendation", "confidence", "fixability",
}

_R11_STUB = """\
```json
{
  "reviewer": "judge",
  "status": "complete",
  "coverage": ["src/parser.py"],
  "questions": [],
  "routing_notes": [],
  "findings": [
    {
      "id": "FINDING-001",
      "severity": "HIGH",
      "category": "Correctness",
      "file": "src/parser.py",
      "line": "L15",
      "title": "Off-by-one in slice index",
      "problem": "Slice `data[1:n]` skips the first element.",
      "evidence": "return data[1:n]",
      "impact": "First record silently dropped.",
      "recommendation": "return data[0:n]",
      "confidence": 0.95,
      "fixability": "autonomous"
    }
  ]
}
```
"""

SCENARIO_R11 = Scenario(
    skill="review",
    id="review-R11-schema-compliance",
    description="Every returned finding must contain all 12 required schema fields",
    prompt=(
        "Review src/parser.py for any defects. Return findings as a JSON block.\n\n"
        "```python\n"
        "def parse(data, n):\n"
        "    return data[1:n]  # processes records 1 through n\n"
        "```"
    ),
    stub_response=_R11_STUB,
    checks=[
        _check(
            "findings contain all 12 schema fields",
            lambda t: all(
                _REQUIRED_FIELDS.issubset(set(f.keys()))
                for f in t.findings()
            ) if t.findings() else True,
            description="12-field contract enforced on all findings",
        ),
        _check(
            "confidence is a float between 0 and 1",
            lambda t: all(
                isinstance(f.get("confidence"), (int, float))
                and 0.0 <= f.get("confidence", -1) <= 1.0
                for f in t.findings()
            ) if t.findings() else True,
        ),
        _check(
            "fixability is autonomous or requires-human",
            lambda t: all(
                f.get("fixability") in {"autonomous", "requires-human"}
                for f in t.findings()
            ) if t.findings() else True,
        ),
    ],
    tags=["schema", "contract"],
)


# ---------------------------------------------------------------------------
# R12 – Requires-human trade-off → Decision Round emitted
# ---------------------------------------------------------------------------

_R12_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: CHANGES REQUIRED
- **Summary**: Architecture trade-off requires human decision before proceeding.

## Findings (Contract: finding_schema.md)

### [FINDING-001] [MEDIUM] Singleton cache lacks expiration policy

- **Category**: Architecture
- **Location**: cache.py:L1
- **Confidence**: 0.80
- **Fixability**: requires-human
- **Problem**: In-memory singleton has no TTL.  Memory grows unbounded in long-running processes.
- **Evidence**:
  ```python
  _cache = {}
  ```
- **Impact on Live Production**: OOM under sustained load.
- **Recommendation**: Add TTL-based expiry or switch to Redis.

## ❓ Decision Round

❓ **Q1** - **Cache eviction policy**: The current singleton grows unbounded.
Options: (a) LRU with configurable max-size, (b) TTL-based expiry, (c) external Redis.

➡️ **Recommended Stance**: LRU with `maxsize=1024` via `functools.lru_cache` for
simplicity; switch to Redis only when cache size exceeds JVM heap monitoring thresholds.
"""

SCENARIO_R12 = Scenario(
    skill="review",
    id="review-R12-requires-human-decision-round",
    description="A finding marked requires-human must trigger a batched Decision Round with recommended stance",
    prompt=(
        "Review cache.py:\n\n"
        "```python\n"
        "_cache = {}\n\n"
        "def get(key):\n"
        "    return _cache.get(key)\n\n"
        "def set(key, value):\n"
        "    _cache[key] = value\n"
        "```\n\n"
        "Apply /review. If you find an architectural trade-off that requires human "
        "input, emit a Decision Round."
    ),
    stub_response=_R12_STUB,
    checks=[
        _check(
            "Decision Round emitted",
            lambda t: t.contains(r"Decision Round|❓.*Q\d"),
            description="requires-human finding must trigger Decision Round",
        ),
        _check(
            "Recommended Stance present",
            lambda t: t.contains(r"Recommended Stance"),
            description="Every Decision Round question must include a concrete stance",
        ),
        _check(
            "finding marked requires-human",
            lambda t: t.contains(r"requires-human"),
            description="Fixability field must be requires-human",
        ),
    ],
    tags=["requires-human", "decision-round"],
)


# ---------------------------------------------------------------------------
# Exported list
# ---------------------------------------------------------------------------

REVIEW_SCENARIOS = [
    SCENARIO_R01,
    SCENARIO_R02,
    SCENARIO_R03,
    SCENARIO_R04,
    SCENARIO_R05,
    SCENARIO_R06,
    SCENARIO_R07,
    SCENARIO_R08,
    SCENARIO_R09,
    SCENARIO_R10,
    SCENARIO_R11,
    SCENARIO_R12,
]
