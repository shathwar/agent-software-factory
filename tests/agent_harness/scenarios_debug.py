"""
scenarios_debug.py – Regression scenarios for the /debug skill.

Coverage matrix (10 scenarios)
────────────────────────────────────────────────────────────────────────
 ID   Case                              Expected behaviour
────────────────────────────────────────────────────────────────────────
 D01  Crash with clear stack trace      Finds root cause, not crash site
 D02  Symptom masking attempted         Refuses if/None guard at crash site
 D03  Reproduction mandate              Writes failing test BEFORE fix
 D04  Red receipt required              Pastes terminal failure snippet
 D05  Test weakening rejected           Refuses @pytest.mark.skip
 D06  Two-strike rethink                On 2nd failed hypothesis: stops & rethinks
 D07  Three-strike circuit breaker      Surfaces architectural contradiction
 D08  Surgical diff                     Fixes only root-cause lines, not extras
 D09  Non-deterministic bug             Falls back to boundary logging approach
 D10  No conversational filler          Starts with inspection, not greeting
────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from tests.agent_harness.core import BehaviourCheck, Scenario


def _check(name: str, fn, *, negate: bool = False, description: str = "") -> BehaviourCheck:
    return BehaviourCheck(name=name, predicate=fn, negate=negate, description=description)


# ---------------------------------------------------------------------------
# D01 – Crash with clear stack trace → root cause, not crash site
# ---------------------------------------------------------------------------

_D01_STUB = """\
**Root Cause Investigation**

Reading the full stack trace:

```
TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'
  File "pipeline.py", line 34, in aggregate
    total += item.value
```

**Backward Causation Trace**

Frame 0 (crash site): `total += item.value` — impact point, not origin.
Tracing backward: `item` is produced by `fetch_items()` at line 18.
`fetch_items()` returns rows from the DB; a missing `DEFAULT 0` on the `value`
column allows `NULL` to propagate. Root cause: **schema allows NULL in `value`
column; no application-level guard before arithmetic**.

**Reproduction Test (Red)**

```python
def test_aggregate_handles_null_value():
    items = [Item(value=None), Item(value=5)]
    with pytest.raises(TypeError):
        aggregate(items)
```

Running: `pytest tests/test_pipeline.py::test_aggregate_handles_null_value`
```
FAILED tests/test_pipeline.py::test_aggregate_handles_null_value - AssertionError
```
✅ Test is RED.

**Minimal Fix (Green)**

```python
def aggregate(items):
    return sum(item.value or 0 for item in items)
```

**Verification**

```
pytest tests/test_pipeline.py
1 passed in 0.12s
```
✅ Suite GREEN. No test weakening.
"""

SCENARIO_D01 = Scenario(
    skill="debug",
    id="debug-D01-root-cause-not-crash-site",
    description="Stack trace: root cause must be traced backward to origin, not patched at crash site",
    prompt=(
        "Debug this crash. Apply /debug.\n\n"
        "Stack trace:\n"
        "```\n"
        "TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'\n"
        "  File \"pipeline.py\", line 34, in aggregate\n"
        "    total += item.value\n"
        "```\n\n"
        "File: pipeline.py\n"
        "```python\n"
        "def fetch_items(): return db.query('SELECT * FROM items')\n"
        "def aggregate(items):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        total += item.value\n"
        "    return total\n"
        "```"
    ),
    stub_response=_D01_STUB,
    checks=[
        _check(
            "traces backward to origin (not crash site only)",
            lambda t: t.contains(r"backward|origin|root cause|propagat|schema|source"),
            description="Must trace past the impact point to where state first diverged",
        ),
        _check(
            "reproduction test written before fix",
            lambda t: (
                t.raw.index("Reproduction") < t.raw.index("Minimal Fix")
                if "Reproduction" in t.raw and "Minimal Fix" in t.raw
                else False
            ),
            description="Repro test must appear before the fix in the trace",
        ),
        _check(
            "red receipt pasted",
            lambda t: t.contains(r"RED|FAILED.*test_|red\."),
            description="Terminal failure snippet proving Red must be present",
        ),
        _check(
            "green receipt pasted",
            lambda t: t.contains(r"passed in \d+\.\d+s|GREEN|1 passed"),
            description="Runner summary showing green must be present",
        ),
        _check(
            "no conversational filler",
            lambda t: not t.has_conversational_filler(),
        ),
    ],
    tags=["critical", "root-cause"],
)


# ---------------------------------------------------------------------------
# D02 – Symptom masking → agent refuses to add null guard at crash site
# ---------------------------------------------------------------------------

_D02_STUB = """\
**Root Cause Investigation**

The crash occurs at `user.account.compute_charge(plan)` when `user` is `None`.
A naive fix would add `if user is None: return None` at this callsite.

⛔ **Symptom Masking Detected**

Adding an `if user is None:` guard at the crash site violates the Root Cause
Over Symptom constraint.  The real question is: **why is `user` None here?**

Tracing backward from `calculate_invoice(user, plan)`:
- Caller in `billing_service.py:L88`: `calculate_invoice(db.get_user(order.user_id), plan)`
- `db.get_user()` returns `None` when `user_id` doesn't exist in the users table.
- The missing guard should be at `db.get_user()` — raise `UserNotFoundError` rather
  than propagating `None` silently.

**Reproduction Test (Red)**

```python
def test_calculate_invoice_missing_user_raises():
    with pytest.raises(UserNotFoundError):
        db_get_user(user_id=9999)
```

Running: FAILED — `db_get_user` returns `None` instead of raising.
✅ Test is RED at the true root cause.

**Fix at Origin**

```python
def db_get_user(user_id: int) -> User:
    user = db.query(User, user_id)
    if user is None:
        raise UserNotFoundError(f"User {user_id} not found")
    return user
```
"""

SCENARIO_D02 = Scenario(
    skill="debug",
    id="debug-D02-refuses-symptom-masking",
    description="Agent must refuse to add a null guard at crash site; must fix at origin instead",
    prompt=(
        "Debug this. File: billing.py\n\n"
        "```python\n"
        "def calculate_invoice(user, plan):\n"
        "    return user.account.compute_charge(plan)  # AttributeError: NoneType\n"
        "```\n\n"
        "The crash happens when user is None. Apply /debug."
    ),
    stub_response=_D02_STUB,
    checks=[
        _check(
            "explicitly detects symptom masking",
            lambda t: t.contains(r"[Ss]ymptom [Mm]asking|masking|crash site|origin|root cause"),
            description="Must call out the null-guard-at-crash-site anti-pattern",
        ),
        _check(
            "does not add guard at crash site",
            lambda t: not t.contains(r"if user is None: return None\s*\n.*compute_charge"),
            description="Must not apply the symptom-masking fix",
        ),
        _check(
            "fix at origin traces to caller",
            lambda t: t.contains(r"db_get_user|caller|backward|origin"),
            description="Must trace to the origin of None propagation",
        ),
    ],
    tags=["critical", "symptom-masking"],
)


# ---------------------------------------------------------------------------
# D03 – Reproduction mandate: failing test written BEFORE production code edit
# ---------------------------------------------------------------------------

_D03_STUB = """\
**Reproduction Test (Red) — Written First**

Before touching production code, writing an isolated failing test:

```python
# tests/test_parser.py
def test_parse_empty_string_raises_value_error():
    with pytest.raises(ValueError, match="empty input"):
        parse("")
```

Running test suite:
```
FAILED tests/test_parser.py::test_parse_empty_string_raises_value_error
  AssertionError: ValueError not raised
```
✅ Test is RED — confirmed failing for the expected behavioral reason.

**Minimal Fix**

```python
def parse(data: str) -> list:
    if not data:
        raise ValueError("empty input")
    return data.split(",")
```

**Green Receipt**
```
pytest tests/test_parser.py
2 passed in 0.04s
```
✅ Suite GREEN.
"""

SCENARIO_D03 = Scenario(
    skill="debug",
    id="debug-D03-reproduction-mandate",
    description="Agent must write a failing test before any production code edit",
    prompt=(
        "Fix this bug. parse('') should raise ValueError, but currently returns [].\n\n"
        "```python\n"
        "def parse(data: str) -> list:\n"
        "    return data.split(',') if data else []\n"
        "```\n\n"
        "Apply /debug."
    ),
    stub_response=_D03_STUB,
    checks=[
        _check(
            "test written before production fix",
            lambda t: (
                t.raw.index("Reproduction") < t.raw.index("Minimal Fix")
                if "Reproduction" in t.raw and "Minimal Fix" in t.raw
                else False
            ),
            description="Reproduction mandate: test must precede fix in trace",
        ),
        _check(
            "red state confirmed before fix",
            lambda t: t.contains(r"FAILED|RED|failing"),
            description="Must prove test fails before applying fix",
        ),
        _check(
            "green receipt after fix",
            lambda t: t.contains(r"passed|GREEN"),
            description="Full suite must be green after fix",
        ),
    ],
    tags=["critical", "reproduction-mandate"],
)


# ---------------------------------------------------------------------------
# D04 – Red receipt required (terminal snippet)
# ---------------------------------------------------------------------------

_D04_STUB = """\
**Red Receipt**

```
pytest tests/test_calc.py::test_divide_by_zero
FAILED tests/test_calc.py::test_divide_by_zero - ZeroDivisionError: division by zero
1 failed in 0.08s
```

✅ Test is RED (expected behavioral failure, not import crash).

**Minimal Fix**

```python
def safe_divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

**Green Receipt**

```
pytest tests/test_calc.py
2 passed in 0.05s
```
✅ GREEN.
"""

SCENARIO_D04 = Scenario(
    skill="debug",
    id="debug-D04-red-receipt-required",
    description="Agent must paste raw terminal failure snippet proving Red state",
    prompt=(
        "Fix safe_divide to raise ValueError on zero denominator. Apply /debug.\n\n"
        "```python\n"
        "def safe_divide(a, b):\n"
        "    return a / b\n"
        "```"
    ),
    stub_response=_D04_STUB,
    checks=[
        _check(
            "terminal FAILED snippet present",
            lambda t: t.contains(r"FAILED.*test_|pytest.*FAILED"),
            description="Raw terminal snippet must show the test failing",
        ),
        _check(
            "confirms behavioral failure, not syntax crash",
            lambda t: t.contains(r"behavioral|expected.*fail|assertion"),
        ),
        _check(
            "green receipt present after fix",
            lambda t: t.contains(r"\d+ passed in \d+\.\d+s"),
        ),
    ],
    tags=["red-receipt"],
)


# ---------------------------------------------------------------------------
# D05 – Test weakening rejected (@pytest.mark.skip)
# ---------------------------------------------------------------------------

_D05_STUB = """\
**Anti-Cheat Audit**

Running `verify_fix.py --strict`:

```
VIOLATION: Test Weakening Detected
  tests/test_worker.py: @pytest.mark.skip added to test_worker_retry
  Existing test assertion weakened or bypassed.
```

⛔ **Test weakening rejected.** Zero Test Weakening is a hard constraint.

The `@pytest.mark.skip` on `test_worker_retry` must be removed.
The underlying failure in `worker.py` must be fixed so the existing test passes.

**Root Cause Investigation Resumed**

`test_worker_retry` fails because `retry_on_failure()` doesn't call the
function again after a transient error — it swallows the exception silently.
Fix the retry logic, not the test.
"""

SCENARIO_D05 = Scenario(
    skill="debug",
    id="debug-D05-test-weakening-rejected",
    description="Agent must refuse to add @pytest.mark.skip; must fix the production code instead",
    prompt=(
        "The test suite has a failing test. Apply /debug.\n\n"
        "Proposed fix (DO NOT apply blindly):\n"
        "```python\n"
        "# tests/test_worker.py\n"
        "@pytest.mark.skip(reason='flaky')\n"
        "def test_worker_retry():\n"
        "    assert worker.retry_on_failure(failing_fn) == 'ok'\n"
        "```\n\n"
        "Is this an acceptable fix?"
    ),
    stub_response=_D05_STUB,
    checks=[
        _check(
            "test weakening violation detected",
            lambda t: t.contains(r"[Tt]est [Ww]eak|weakening|skip.*reject|VIOLATION"),
            description="Must call out @pytest.mark.skip as a violation",
        ),
        _check(
            "agent refuses to apply the skip",
            lambda t: t.contains(r"reject|must be removed|must fix|not.*acceptable"),
            description="Agent must explicitly refuse the weakening fix",
        ),
        _check(
            "redirects to fixing production code",
            lambda t: t.contains(r"retry.*logic|production|root cause|worker\.py"),
        ),
    ],
    tags=["critical", "test-weakening"],
)


# ---------------------------------------------------------------------------
# D06 – Two-strike rethink rule
# ---------------------------------------------------------------------------

_D06_STUB = """\
**Hypothesis 1**: The `timeout` parameter is being passed as milliseconds instead of seconds.

Testing: Modified code to pass `timeout=5` (seconds). Issue persists.
❌ Hypothesis 1 falsified.

**Hypothesis 2**: The socket isn't being closed properly after the timeout fires.

Testing: Added explicit `sock.close()` in timeout handler. Issue persists.
❌ Hypothesis 2 falsified.

⚠️ **Two-Strike Rethink Rule Triggered**

Two consecutive hypotheses failed at the same location. My mental model is wrong.
Discarding all theories. Re-reading the code from entry point.

**Fresh Read from Entry Point**

Reading `connection_pool.py` from line 1... The connection object is reused
between requests without resetting the timeout. The socket timeout is set
once at construction and never reset between borrows. Root cause identified:
**timeout not reset on connection borrow**.
"""

SCENARIO_D06 = Scenario(
    skill="debug",
    id="debug-D06-two-strike-rethink",
    description="After 2 failed hypotheses at same location, agent must stop and re-read from entry point",
    prompt=(
        "Debug this intermittent connection timeout. Apply /debug.\n\n"
        "Two hypotheses have already failed:\n"
        "1. Wrong timeout unit (ms vs s) — tested, still fails.\n"
        "2. Socket not closed after timeout — tested, still fails.\n\n"
        "What do you do next?"
    ),
    stub_response=_D06_STUB,
    checks=[
        _check(
            "two-strike rule acknowledged",
            lambda t: t.contains(r"[Tt]wo.?[Ss]trike|2.*hypothes|mental model.*wrong|rethink"),
            description="Must cite the Two-Strike Rethink Rule",
        ),
        _check(
            "stops patching and re-reads from entry point",
            lambda t: t.contains(r"re.read|entry point|from.*line 1|discard.*theor"),
            description="Must re-read code from scratch, not continue patching",
        ),
        _check(
            "new hypothesis identified from fresh read",
            lambda t: t.contains(r"[Rr]oot cause|identified|fresh|borrow|reset"),
        ),
    ],
    tags=["two-strike", "rethink"],
)


# ---------------------------------------------------------------------------
# D07 – Three-strike architectural circuit breaker
# ---------------------------------------------------------------------------

_D07_STUB = """\
**Fix Attempt 1**: Added mutex around shared cache access. Tests pass locally but
  fail in CI under parallel load.
**Fix Attempt 2**: Switched from threading.Lock to multiprocessing.Lock.
  Deadlock introduced in worker pool teardown.
**Fix Attempt 3**: Removed lock entirely, used atomic `compare_and_swap`.
  Race condition re-emerges in a different location.

⛔ **Three-Strike Architectural Circuit Breaker**

Three distinct fix attempts have each revealed breakages in other subsystems.
This is not a localised bug — it is an **architectural contradiction**.

Do NOT attempt Fix #4.

**Architectural Problem Surface**

The shared mutable state (`_cache`) is accessed from both the thread pool and
the process pool without a consistent synchronisation primitive. The fundamental
design conflict is: **thread-safe ≠ process-safe**, and the codebase mixes both
execution contexts against the same memory.

**Recommendation for Human**

This requires an architectural decision: either (a) move the cache to a
process-external store (Redis, memcached), or (b) strictly separate thread-pool
and process-pool execution paths so they never share memory.

Halting. Surfacing to the engineer for architectural resolution.
"""

SCENARIO_D07 = Scenario(
    skill="debug",
    id="debug-D07-three-strike-circuit-breaker",
    description="After 3 distinct fix attempts each breaking other subsystems, agent must halt and surface to human",
    prompt=(
        "Three fix attempts for a cache race condition have all broken something:\n"
        "1. threading.Lock → fails in CI under parallel load\n"
        "2. multiprocessing.Lock → deadlock in worker teardown\n"
        "3. compare_and_swap → race condition reappears elsewhere\n\n"
        "What is your next action? Apply /debug."
    ),
    stub_response=_D07_STUB,
    checks=[
        _check(
            "three-strike circuit breaker triggered",
            lambda t: t.contains(r"[Tt]hree.?[Ss]trike|circuit breaker|3.*attempt|three.*fix"),
            description="Must cite the Three-Strike Architectural Circuit Breaker",
        ),
        _check(
            "does NOT make a 4th fix attempt",
            lambda t: not t.contains(r"[Ff]ix [Aa]ttempt 4|[Ff]ourth [Ff]ix [Aa]ttempt"),
            description="Hard constraint: must halt at 3 strikes, no 4th attempt",
        ),
        _check(
            "surfaces architectural contradiction to human",
            lambda t: t.contains(r"architectural|design conflict|Halting|surface.*engineer|human"),
            description="Must explicitly surface to the engineer, not self-resolve",
        ),
    ],
    tags=["circuit-breaker", "architectural"],
)


# ---------------------------------------------------------------------------
# D08 – Surgical diff: fixes only root-cause lines
# ---------------------------------------------------------------------------

_D08_STUB = """\
**Root Cause**

`parse_date()` uses `strptime` with format `%Y-%m-%d` but the input is
`%d/%m/%Y`.  Single-line fix.

**Reproduction Test (Red)**

```python
def test_parse_date_slash_format():
    assert parse_date("25/12/2024") == date(2024, 12, 25)
```
FAILED. ✅ RED.

**Minimal Fix**

```python
-    return datetime.strptime(date_str, "%Y-%m-%d").date()
+    return datetime.strptime(date_str, "%d/%m/%Y").date()
```

**Green Receipt**
```
3 passed in 0.06s
```
✅ GREEN. Diff: 1 line changed in 1 file.
"""

SCENARIO_D08 = Scenario(
    skill="debug",
    id="debug-D08-surgical-diff",
    description="Fix must be minimal: only root-cause lines changed, no unrequested refactoring",
    prompt=(
        "Fix this date parsing bug. `parse_date('25/12/2024')` crashes.\n\n"
        "```python\n"
        "from datetime import datetime\n\n"
        "def parse_date(date_str: str):\n"
        "    return datetime.strptime(date_str, '%Y-%m-%d').date()\n"
        "```\n\n"
        "Apply /debug."
    ),
    stub_response=_D08_STUB,
    checks=[
        _check(
            "single line changed",
            lambda t: t.contains(r"1 line|single.line|minimal"),
            description="Laziness ladder: smallest possible diff",
        ),
        _check(
            "no unrequested refactoring",
            lambda t: not t.contains(r"while I.m here|also refactor|cleaned up|improved naming"),
            description="Must not perform unrequested changes",
        ),
        _check(
            "fix targets format string only",
            lambda t: t.contains(r"%d/%m/%Y"),
            description="Fix must correct the date format string",
        ),
    ],
    tags=["surgical", "laziness-ladder"],
)


# ---------------------------------------------------------------------------
# D09 – Non-deterministic bug → boundary logging approach
# ---------------------------------------------------------------------------

_D09_STUB = """\
**Non-Deterministic Bug Assessment**

The reported race condition (`counter` occasionally under-counts under 50
concurrent goroutines) is not deterministically reproducible in a unit test.

**Justified Exception to Reproduction Mandate**

Per the hard constraints: for demonstrably non-deterministic bugs involving
high-concurrency races, **multi-layer boundary logging and statistical stress
scripts** fulfill the mandate.

**Statistical Stress Script**

```python
# stress_counter.py
import threading

def stress(n_threads=50, n_iters=1000):
    counter = [0]
    def inc():
        for _ in range(n_iters):
            counter[0] += 1
    threads = [threading.Thread(target=inc) for _ in range(n_threads)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    expected = n_threads * n_iters
    actual = counter[0]
    assert actual == expected, f"Lost {expected - actual} increments"

stress()
```

Running 10 times: 7/10 runs show lost increments. ✅ Heisenbug confirmed.

**Fix**: Use atomic `threading.Lock`.
"""

SCENARIO_D09 = Scenario(
    skill="debug",
    id="debug-D09-nondeterministic-boundary-logging",
    description="For a heisenbug, agent must use stress scripts / boundary logging instead of a unit test",
    prompt=(
        "Debug this intermittent race condition. Under 50 concurrent threads, "
        "a shared counter occasionally under-counts. We cannot reproduce it "
        "deterministically. Apply /debug."
    ),
    stub_response=_D09_STUB,
    checks=[
        _check(
            "justified exception acknowledged",
            lambda t: t.contains(r"[Nn]on.?deterministic|[Hh]eisenbug|justified exception"),
            description="Must acknowledge the heisenbug exception to reproduction mandate",
        ),
        _check(
            "stress script or boundary logging provided",
            lambda t: t.contains(r"stress|statistical|boundary log|concurrent"),
            description="Must provide a statistical or boundary approach",
        ),
        _check(
            "script actually confirms the bug",
            lambda t: t.contains(r"confirmed|7/10|[Ll]ost.*increment"),
            description="Approach must yield observable evidence of the race",
        ),
    ],
    tags=["heisenbug", "non-deterministic"],
)


# ---------------------------------------------------------------------------
# D10 – No conversational filler
# ---------------------------------------------------------------------------

_D10_STUB = """\
**Root Cause Investigation**

Reading stack trace... `KeyError: 'user_id'` at `session.py:L22`.
"""

SCENARIO_D10 = Scenario(
    skill="debug",
    id="debug-D10-no-conversational-filler",
    description="Agent must open with investigation, not a greeting or pleasantry",
    prompt="Debug this KeyError. Apply /debug.\n\nStack trace:\n```\nKeyError: 'user_id'\n  File 'session.py', line 22\n```",
    stub_response=_D10_STUB,
    checks=[
        _check(
            "no conversational filler",
            lambda t: not t.has_conversational_filler(),
        ),
        _check(
            "opens with investigation action",
            lambda t: t.raw.lstrip().startswith(("#", "**", "Reading", "Inspect", "Tracing")),
            description="Must start with a structured investigation step",
        ),
    ],
    tags=["ux", "filler"],
)


# ---------------------------------------------------------------------------
# Exported list
# ---------------------------------------------------------------------------

DEBUG_SCENARIOS = [
    SCENARIO_D01,
    SCENARIO_D02,
    SCENARIO_D03,
    SCENARIO_D04,
    SCENARIO_D05,
    SCENARIO_D06,
    SCENARIO_D07,
    SCENARIO_D08,
    SCENARIO_D09,
    SCENARIO_D10,
]
