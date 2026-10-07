"""
scenarios_tdd.py – Regression scenarios for the /tdd skill.

Coverage matrix (10 scenarios)
────────────────────────────────────────────────────────────────────────
 ID   Case                              Expected behaviour
────────────────────────────────────────────────────────────────────────
 T01  Test written first                Production code only after Red
 T02  Iron Law enforced                 STOP if code written first
 T03  Red state verified                Failure is behavioral, not syntax
 T04  Minimum viable green              No speculative edge-case code
 T05  Refactor under green              Structure changed only when green
 T06  Hollow mock detected              Rejects mock-everything pattern
 T07  Assertless test rejected          Must assert observable state
 T08  DB engine not mocked              Ephemeral DB used for persistence
 T09  Characterisation wrap (legacy)    Wraps before refactoring
 T10  No conversational filler          Starts with test code
────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from tests.agent_harness.core import BehaviourCheck, Scenario


def _check(name: str, fn, *, negate: bool = False, description: str = "") -> BehaviourCheck:
    return BehaviourCheck(name=name, predicate=fn, negate=negate, description=description)


# ---------------------------------------------------------------------------
# T01 – Test written first, production code only after Red
# ---------------------------------------------------------------------------

_T01_STUB = """\
**🔴 Red Phase**

Writing the failing test first:

```python
# tests/test_discount.py
def test_apply_discount_ten_percent():
    assert apply_discount(100.0, 0.10) == 90.0
```

Running test:
```
FAILED tests/test_discount.py::test_apply_discount_ten_percent
  NameError: name 'apply_discount' is not defined
```

Wait — that's an import error, not a behavioral assertion failure. Writing the
import and minimal stub first so the test can reach the assertion:

```python
# discount.py
def apply_discount(price, rate):
    pass
```

Running again:
```
FAILED tests/test_discount.py::test_apply_discount_ten_discount
  AssertionError: assert None == 90.0
```
✅ Red — behavioral assertion failure confirmed.

**🟢 Green Phase**

```python
def apply_discount(price: float, rate: float) -> float:
    return price * (1 - rate)
```

Running:
```
1 passed in 0.02s
```
✅ GREEN.

**🔵 Refactor Phase**

No duplication. Structure clean. No changes needed.
"""

SCENARIO_T01 = Scenario(
    skill="tdd",
    id="tdd-T01-test-written-first",
    description="Production code must only be written after a failing test is confirmed Red",
    prompt=(
        "Implement `apply_discount(price, rate)` using TDD. "
        "It should return `price * (1 - rate)`. Apply /tdd."
    ),
    stub_response=_T01_STUB,
    checks=[
        _check(
            "test written before production code",
            lambda t: t.raw.index("Red Phase") < t.raw.index("Green Phase"),
            description="Red phase must precede Green phase in the trace",
        ),
        _check(
            "behavioral Red confirmed",
            lambda t: t.contains(r"AssertionError|assert.*==|behavioral"),
            description="Failure must be a behavioral assertion, not import error",
        ),
        _check(
            "green receipt present",
            lambda t: t.contains(r"\d+ passed"),
        ),
        _check(
            "refactor phase present",
            lambda t: t.contains(r"Refactor"),
        ),
        _check(
            "no conversational filler",
            lambda t: not t.has_conversational_filler(),
        ),
    ],
    tags=["critical", "test-first"],
)


# ---------------------------------------------------------------------------
# T02 – Iron Law enforced: code written first → STOP
# ---------------------------------------------------------------------------

_T02_STUB = """\
⛔ **Iron Law of Test-First Violated**

Production code was written before a failing test existed. This violates the
TDD Iron Law.

**Required action**: Revert the production code. Write the test first. Observe
the Red failure. Then write the minimum code to turn it Green.

Reverting `formatter.py` to its previous state (empty stub).

**🔴 Red Phase (corrected order)**

```python
def test_format_currency_usd():
    assert format_currency(9.99, "USD") == "$9.99"
```

Running:
```
FAILED tests/test_formatter.py::test_format_currency_usd
  AssertionError: assert None == '$9.99'
```
✅ Red confirmed.
"""

SCENARIO_T02 = Scenario(
    skill="tdd",
    id="tdd-T02-iron-law-enforced",
    description="If production code is written before tests, agent must STOP and revert",
    prompt=(
        "I already wrote the implementation first:\n\n"
        "```python\n"
        "# formatter.py\n"
        "def format_currency(amount, currency):\n"
        "    symbols = {'USD': '$', 'EUR': '€'}\n"
        "    return f\"{symbols[currency]}{amount:.2f}\"\n"
        "```\n\n"
        "Now write the tests. Apply /tdd."
    ),
    stub_response=_T02_STUB,
    checks=[
        _check(
            "Iron Law violation detected",
            lambda t: t.contains(r"[Ii]ron [Ll]aw|violated|code.*before.*test|test.*first.*violated"),
            description="Must call out the Iron Law violation",
        ),
        _check(
            "reverts or halts before writing more production code",
            lambda t: t.contains(r"[Rr]evert|corrected order|STOP"),
            description="Must revert and restart with test-first",
        ),
        _check(
            "Red phase follows revert",
            lambda t: t.contains(r"Red Phase|FAILED.*test_"),
        ),
    ],
    tags=["critical", "iron-law"],
)


# ---------------------------------------------------------------------------
# T03 – Red state must be behavioral failure, not syntax/import crash
# ---------------------------------------------------------------------------

_T03_STUB = """\
**🔴 Red Phase**

```python
from calculator import add

def test_add_two_numbers():
    assert add(2, 3) == 5
```

Running:
```
FAILED tests/test_calculator.py::test_add_two_numbers
  ImportError: cannot import name 'add' from 'calculator'
```

⚠️ Import error — not a behavioral failure. Writing minimal stub to allow
reaching the assertion:

```python
# calculator.py
def add(a, b):
    pass
```

Running again:
```
FAILED tests/test_calculator.py::test_add_two_numbers
  AssertionError: assert None == 5
```
✅ Behavioral Red confirmed — assertion failure, not import error.
"""

SCENARIO_T03 = Scenario(
    skill="tdd",
    id="tdd-T03-behavioral-red-verified",
    description="Red state must be an assertion failure, not a syntax or import error",
    prompt=(
        "Implement `add(a, b)` in calculator.py using /tdd. "
        "The function does not exist yet."
    ),
    stub_response=_T03_STUB,
    checks=[
        _check(
            "distinguishes import error from behavioral failure",
            lambda t: t.contains(r"ImportError|not.*behavioral|import error.*not"),
            description="Must note that import error ≠ behavioral Red",
        ),
        _check(
            "behavioral AssertionError confirmed",
            lambda t: t.contains(r"AssertionError|assert.*==.*5|behavioral.*Red"),
            description="Must achieve behavioral Red before proceeding",
        ),
    ],
    tags=["red-state", "behavioral"],
)


# ---------------------------------------------------------------------------
# T04 – Minimum viable green: no speculative code
# ---------------------------------------------------------------------------

_T04_STUB = """\
**🟢 Green Phase — Minimum Viable Implementation**

Failing test:
```python
def test_is_palindrome_simple():
    assert is_palindrome("racecar") is True
```

Minimum code to pass:
```python
def is_palindrome(s: str) -> bool:
    return s == s[::-1]
```

Running:
```
1 passed in 0.01s
```
✅ GREEN.

No speculative edge-case handling added. Unicode normalisation, empty string
handling, and case-insensitivity will be driven by future failing tests.
"""

SCENARIO_T04 = Scenario(
    skill="tdd",
    id="tdd-T04-minimum-viable-green",
    description="Green phase must write only the minimum code; no speculative edge cases",
    prompt=(
        "Make this test pass using /tdd:\n\n"
        "```python\n"
        "def test_is_palindrome_simple():\n"
        "    assert is_palindrome('racecar') is True\n"
        "```\n\n"
        "Write the minimum production code. Do not add undriven edge cases."
    ),
    stub_response=_T04_STUB,
    checks=[
        _check(
            "explicitly notes no speculative code added",
            lambda t: t.contains(r"speculative|future.*test|minimum|no.*edge.case"),
            description="Must note that speculative code is prohibited",
        ),
        _check(
            "implementation is minimal (no extra branches)",
            lambda t: not t.contains(r"if.*unicode|if.*empty|if.*case"),
            description="No undriven conditional branches in implementation",
        ),
        _check(
            "green receipt present",
            lambda t: t.contains(r"\d+ passed"),
        ),
    ],
    tags=["minimum-viable-green"],
)


# ---------------------------------------------------------------------------
# T05 – Refactor only under green tests
# ---------------------------------------------------------------------------

_T05_STUB = """\
**🔵 Refactor Phase**

All tests are green:
```
5 passed in 0.08s
```

Now safe to refactor. Extracting duplicated validation logic into a helper:

```python
def _validate_positive(n: int, name: str) -> None:
    if n <= 0:
        raise ValueError(f"{name} must be positive")
```

Running tests after refactor:
```
5 passed in 0.08s
```
✅ All green — refactor is safe. No regressions.
"""

SCENARIO_T05 = Scenario(
    skill="tdd",
    id="tdd-T05-refactor-under-green",
    description="Refactoring must happen only when all tests are green, with re-run verification",
    prompt=(
        "5 tests pass. Refactor the duplicated validation in inventory.py. Apply /tdd."
    ),
    stub_response=_T05_STUB,
    checks=[
        _check(
            "green verified before refactor begins",
            lambda t: (
                "5 passed" in t.raw and "Now safe to refactor" in t.raw
                and t.raw.index("5 passed") < t.raw.index("Now safe to refactor")
            ),
            description="Green receipt must appear before the refactor action statement",
        ),
        _check(
            "tests re-run after refactor",
            lambda t: t.raw.count("passed") >= 2,
            description="Suite must be re-run after structural change to confirm green",
        ),
    ],
    tags=["refactor", "green-protection"],
)


# ---------------------------------------------------------------------------
# T06 – Hollow mock rejected
# ---------------------------------------------------------------------------

_T06_STUB = """\
**Anti-Pattern Detected: Hollow Mock**

The proposed test:
```python
def test_send_email_calls_smtp(mocker):
    mock_smtp = mocker.patch('mailer.smtplib.SMTP')
    send_email("to@example.com", "Hi")
    mock_smtp.return_value.sendmail.assert_called_once()
```

This mocks `smtplib.SMTP` entirely and only verifies that a mock was called.
It does not assert on any **observable output or state transition** of the
system under test.

⛔ **Hollow Mock rejected.**

**Correct approach**: Assert on observable public outcomes, not internal call
chains. Use a `FakeSMTP` in-memory double that records sent messages:

```python
class FakeSMTP:
    sent = []
    def sendmail(self, from_, to, msg): self.sent.append((to, msg))

def test_send_email_records_recipient(monkeypatch):
    fake = FakeSMTP()
    monkeypatch.setattr("mailer.smtplib.SMTP", lambda *a, **kw: fake)
    send_email("to@example.com", "Hi")
    assert fake.sent == [("to@example.com", "Hi")]
```
"""

SCENARIO_T06 = Scenario(
    skill="tdd",
    id="tdd-T06-hollow-mock-rejected",
    description="Hollow mock pattern (asserting that a mock was called) must be detected and rejected",
    prompt=(
        "Is this a good TDD test? Apply /tdd to evaluate.\n\n"
        "```python\n"
        "def test_send_email_calls_smtp(mocker):\n"
        "    mock_smtp = mocker.patch('mailer.smtplib.SMTP')\n"
        "    send_email('to@example.com', 'Hi')\n"
        "    mock_smtp.return_value.sendmail.assert_called_once()\n"
        "```"
    ),
    stub_response=_T06_STUB,
    checks=[
        _check(
            "hollow mock pattern detected",
            lambda t: t.contains(r"[Hh]ollow [Mm]ock|verif.*mock|mock.*mock|mock.*called"),
            description="Must identify the hollow mock anti-pattern",
        ),
        _check(
            "proposes observable-outcome assertion",
            lambda t: t.contains(r"observable|FakeSMTP|in.memory|public outcome|assert.*sent"),
            description="Must redirect to asserting observable state",
        ),
        _check(
            "explicitly rejects the hollow test",
            lambda t: t.contains(r"reject|not.*acceptable|STOP|anti.pattern"),
        ),
    ],
    tags=["hollow-mock", "behavior-over-mocks"],
)


# ---------------------------------------------------------------------------
# T07 – Assertless test rejected
# ---------------------------------------------------------------------------

_T07_STUB = """\
**Anti-Pattern Detected: Assertless Test**

```python
def test_process_job():
    process_job({"id": 1, "type": "email"})
```

This test verifies only that the function "doesn't throw". It provides zero
protection against behavioural regressions — a completely wrong implementation
passes it.

⛔ **Assertless test rejected.** Per hard constraints: assert on observable
inputs, outputs, and state transitions.

**Corrected test**:
```python
def test_process_job_marks_completed():
    job = {"id": 1, "type": "email", "status": "pending"}
    result = process_job(job)
    assert result["status"] == "completed"
    assert result["processed_at"] is not None
```
"""

SCENARIO_T07 = Scenario(
    skill="tdd",
    id="tdd-T07-assertless-test-rejected",
    description="A test with no assertions must be rejected; agent must add observable assertion",
    prompt=(
        "Evaluate this TDD test. Apply /tdd.\n\n"
        "```python\n"
        "def test_process_job():\n"
        "    process_job({'id': 1, 'type': 'email'})\n"
        "```"
    ),
    stub_response=_T07_STUB,
    checks=[
        _check(
            "assertless anti-pattern detected",
            lambda t: t.contains(r"[Aa]ssertless|doesn.t throw|no assertion|zero protection"),
            description="Must identify the assertless test pattern",
        ),
        _check(
            "provides corrected test with assertion",
            lambda t: t.contains(r'assert result|assert.*status|assert.*completed'),
            description="Corrected test must assert on observable state",
        ),
    ],
    tags=["assertless", "tdd-antipattern"],
)


# ---------------------------------------------------------------------------
# T08 – DB engine must NOT be mocked; use ephemeral DB
# ---------------------------------------------------------------------------

_T08_STUB = """\
**Tier 2: Persistence & Wire TDD**

This test involves database queries — Tier 2 applies. Database engines must
NOT be mocked.

**Setting up ephemeral SQLite database:**

```python
import sqlite3, pytest

@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE)")
    yield conn
    conn.close()

def test_unique_email_constraint_enforced(db):
    db.execute("INSERT INTO users VALUES (1, 'alice@example.com')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO users VALUES (2, 'alice@example.com')")
```

Running with ephemeral in-memory SQLite:
```
1 passed in 0.04s
```
✅ Real SQL engine exercised. No mocking of database layer.
"""

SCENARIO_T08 = Scenario(
    skill="tdd",
    id="tdd-T08-db-engine-not-mocked",
    description="Persistence tests must use ephemeral DB (SQLite/Testcontainers), never mock the DB client",
    prompt=(
        "Write a TDD test for a unique email constraint in the users table. "
        "The repository uses SQLite. Apply /tdd."
    ),
    stub_response=_T08_STUB,
    checks=[
        _check(
            "uses ephemeral SQLite, not mock",
            lambda t: t.contains(r":memory:|sqlite3\.connect|Testcontainer"),
            description="Must use real in-memory DB, not Mock()",
        ),
        _check(
            "explicitly no mocking of DB",
            lambda t: not t.contains(r"mock.*sqlite|patch.*sqlite|mocker.*db"),
            description="DB client must not be mocked",
        ),
        _check(
            "real constraint exercised",
            lambda t: t.contains(r"IntegrityError|UNIQUE constraint"),
            description="Real DB must enforce the unique constraint",
        ),
    ],
    tags=["persistence", "ephemeral-db", "tier-2"],
)


# ---------------------------------------------------------------------------
# T09 – Legacy brownfield: characterisation wrap before refactor
# ---------------------------------------------------------------------------

_T09_STUB = """\
**Brownfield Onboarding Protocol**

Existing untested legacy code detected in `legacy_pricing.py`. Per TDD
hard constraints: **never revert or blindly refactor untested legacy code**.

**Step 1: Golden Master (Characterisation Wrapping)**

Calling existing function with representative inputs to lock current behaviour:

```python
# tests/test_legacy_pricing_characterisation.py
from legacy_pricing import calculate_price

def test_current_behaviour_standard_item():
    assert calculate_price(item_id=1, qty=5) == 49.95

def test_current_behaviour_bulk_discount():
    assert calculate_price(item_id=1, qty=100) == 879.0
```

Running — all pass (locks baseline). ✅

**Step 2: New failing test for desired fix**

```python
def test_zero_quantity_raises_value_error():
    with pytest.raises(ValueError, match="qty must be positive"):
        calculate_price(item_id=1, qty=0)
```

Running — FAILED. ✅ Red.

**Step 3: Minimal fix under characterisation protection**

Added guard at top of `calculate_price`. Both characterisation tests and new
test pass. ✅
"""

SCENARIO_T09 = Scenario(
    skill="tdd",
    id="tdd-T09-brownfield-characterisation-wrap",
    description="Legacy untested code must be wrapped in characterisation tests before any refactoring",
    prompt=(
        "There is untested legacy code in `legacy_pricing.py`. I need to add "
        "a guard: `calculate_price(qty=0)` should raise ValueError. Apply /tdd "
        "using the brownfield onboarding protocol."
    ),
    stub_response=_T09_STUB,
    checks=[
        _check(
            "characterisation test written first",
            lambda t: t.contains(r"[Cc]haracterisation|[Gg]olden [Mm]aster|lock.*behaviour|baseline"),
            description="Must wrap legacy code in characterisation tests before touching it",
        ),
        _check(
            "does not revert legacy code",
            # The stub says "never revert or blindly refactor" (the prohibition);
            # we only fail if the agent actually reverts the file.
            lambda t: not t.contains(r"Reverting.*legacy|Deleted.*legacy_pricing|rewriting.*legacy"),
            description="Must not actually revert or delete the legacy file",
        ),
        _check(
            "new failing test then fix",
            lambda t: t.contains(r"FAILED.*✅ Red|FAILED.*Red|Running.*FAILED|test.*fail.*fix|Step 2.*fail"),
            description="New behaviour test must fail before fix is applied",
        ),
    ],
    tags=["brownfield", "legacy", "characterisation"],
)


# ---------------------------------------------------------------------------
# T10 – No conversational filler
# ---------------------------------------------------------------------------

_T10_STUB = """\
**🔴 Red Phase**

```python
def test_multiply():
    assert multiply(3, 4) == 12
```

Running: FAILED — `NameError: multiply`. Adding stub.
FAILED — `AssertionError: assert None == 12`. ✅ Behavioral Red.
"""

SCENARIO_T10 = Scenario(
    skill="tdd",
    id="tdd-T10-no-conversational-filler",
    description="Agent must open with test code immediately, not a greeting",
    prompt="Implement `multiply(a, b)` using /tdd.",
    stub_response=_T10_STUB,
    checks=[
        _check(
            "no conversational filler",
            lambda t: not t.has_conversational_filler(),
        ),
        _check(
            "opens with test code or Red Phase header",
            lambda t: t.raw.lstrip().startswith(("#", "**", "```")),
            description="Must start with structured TDD content",
        ),
    ],
    tags=["ux", "filler"],
)


# ---------------------------------------------------------------------------
# Exported list
# ---------------------------------------------------------------------------

TDD_SCENARIOS = [
    SCENARIO_T01,
    SCENARIO_T02,
    SCENARIO_T03,
    SCENARIO_T04,
    SCENARIO_T05,
    SCENARIO_T06,
    SCENARIO_T07,
    SCENARIO_T08,
    SCENARIO_T09,
    SCENARIO_T10,
]
