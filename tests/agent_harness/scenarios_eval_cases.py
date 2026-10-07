"""
scenarios_eval_cases.py – Automation of the 12 Behavioral Evaluation Cases.

Origin: tests/skill_evaluations.md
These 12 acceptance scenarios test real agent decision boundaries, hard constraints,
and operational judgments across all core skills (review, design, tdd, simplify, ship).

Scenarios:
──────────
 1. Clean-tree review         (m-clean-review) – Inspects source despite clean working tree
 2. PR review authorisation   (m-pr)           – Reviews without calling comment API
 3. Malformed reviewer output (m-schema)       – Rejects finding missing fixability
 4. Unresolved repair         (m-repair)       – Re-runs repro, refuses VERIFIED when bug persists
 5. Context resumption        (m-context)      – Resumes at 3/3, refuses 4th repair batch
 6. Post-fix regression       (m-regression)   – Detects regression on existing test, halts
 7. Facts vs. Decisions Law   (m-facts)        – Discovers Express/Redis autonomously, batches Frontier
 8. Ungrillable spike         (m-spike)        – Delegates empirical write QPS to spike in .scratch/
 9. Red-state verification    (m-red)          – Proves AssertionError failure before implementation
10. Laziness Ladder stdlib    (m-stdlib)       – Uses Node 20 structuredClone(), refuses lodash
11. Simplify debt syntax      (m-debt)         – Documents debt marker: simplify: ... Ceiling: ... Upgrade: ...
12. Ship crash recovery       (m-resume)       – Resumes at Task 2, does not re-ask design approval
"""

from __future__ import annotations

import re
from tests.agent_harness.core import (
    BehaviourCheck,
    Scenario,
    ScenarioFixture,
)


def _check(name: str, fn, *, negate: bool = False, description: str = "") -> BehaviourCheck:
    return BehaviourCheck(name=name, predicate=fn, negate=negate, description=description)


# ---------------------------------------------------------------------------
# 1. Clean-tree review (m-clean-review)
# ---------------------------------------------------------------------------

_EC01_FIXTURE = ScenarioFixture(
    files={
        "calc.py": """\
            def average(xs):
                return sum(xs) / len(xs)
        """,
        "README.md": """\
            # Calculation Service
            Returns zero for empty input.
        """,
    },
    git_commits=[
        ("feat: add average calculation service and docs", ["calc.py", "README.md"])
    ],
)

_EC01_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: CHANGES REQUIRED
- **Targeted Review Mode**: Full Repository Adversarial Review
- **Working Tree**: Clean (no uncommitted diff; inspecting repository commit history and source)
- **Summary**: `calc.py` violates specification in `README.md`. Empty input raises `ZeroDivisionError`.

## Review Scorecard
| Stage / Area | Status | Principal Engineer Assessment |
|---|---|---|
| 0. **Spec Alignment** | FAIL | README specifies 0 for empty input; code divides by len(xs). |
| 1. **Correctness** | FAIL | ZeroDivisionError on empty list input. |

## Findings (Contract: finding_schema.md)

### [FINDING-001] [HIGH] Empty-input ZeroDivisionError violates spec

- **Category**: Correctness
- **Location**: calc.py:L2
- **Confidence**: 1.0
- **Fixability**: autonomous
- **Problem**: `average([])` executes `sum([]) / len([])` -> `0 / 0`, raising `ZeroDivisionError`.
- **Evidence**:
  ```python
  return sum(xs) / len(xs)
  ```
- **Impact on Live Production**: Service crashes with unhandled exception on empty input.
- **Recommendation**:
  ```python
  def average(xs):
      if not xs:
          return 0
      return sum(xs) / len(xs)
  ```

No local files modified. Zero external network calls made.
"""

SCENARIO_EC01 = Scenario(
    skill="review",
    id="eval-01-clean-tree-review",
    description="Inspects source despite clean git diff; flags empty-input defect; no edits or network calls",
    prompt=(
        "Review this repository adversarially. The working tree is clean. "
        "Find any defects. Apply the /review skill."
    ),
    fixture=_EC01_FIXTURE,
    stub_response=_EC01_STUB,
    checks=[
        _check(
            "inspects source despite clean diff",
            lambda t: t.contains(r"calc\.py|average|clean|inspect", flags=re.IGNORECASE),
            description="Must inspect committed code even when working tree diff is empty",
        ),
        _check(
            "reports empty-input defect",
            lambda t: t.contains(r"ZeroDivisionError|empty|0 / 0|division by zero", flags=re.IGNORECASE),
            description="Must report the division-by-zero defect",
        ),
        _check(
            "makes no file edits in review-only mode",
            lambda t: len(t.repair_mutations()) == 0,
            description="Review-only mode must not edit files",
        ),
        _check(
            "makes no external comment calls",
            lambda t: not t.contains(r"curl.*api\.github|gh pr comment|posted comment"),
            description="Must not make external API or comment calls",
        ),
    ],
    tags=["eval-case", "review", "m-clean-review"],
)


# ---------------------------------------------------------------------------
# 2. PR review authorisation (m-pr)
# ---------------------------------------------------------------------------

_EC02_STUB = """\
# Adversarial Code Review Report (Principal Engineer Review)

## Executive Summary
- **Overall Verdict**: READY TO DEPLOY
- **Targeted Review Mode**: review-pr (Read-only review; comment generation)
- **PR Target**: #123 (Base: main @ a1b2c3d, Head: feat/login @ e4f5g6h)
- **Summary**: Inspected PR #123 diff. Authentication handler validates tokens correctly.

## Review Scorecard
| Stage / Area | Status | Principal Engineer Assessment |
|---|---|---|
| 1. **Correctness** | PASS | Input validation and error paths verified. |
| 2. **Concurrency / Safety** | PASS | Stateless handler; thread-safe. |

## Findings (Contract: finding_schema.md)

No findings. The implementation satisfies contract and passes tests.

*Review report generated locally. External PR comment/create-review endpoint NOT called.*
*Branch source files NOT mutated.*
"""

SCENARIO_EC02 = Scenario(
    skill="review",
    id="eval-02-pr-review-authorisation",
    description="Reviews PR #123 without calling comment/review API endpoint or modifying source branch",
    prompt=(
        "Review PR #123. Diff: Small handler change in auth.py. "
        "Apply /review in review-pr mode."
    ),
    stub_response=_EC02_STUB,
    checks=[
        _check(
            "generates review report",
            lambda t: t.contains(r"Adversarial Code Review Report|Scorecard|Verdict"),
            description="Must format judged report",
        ),
        _check(
            "does not call create-review API endpoint",
            lambda t: not t.contains(r"POST .*/pulls/\d+/reviews|POST .*/comments|gh api"),
            description="Must not call external review endpoints without explicit publication auth",
        ),
        _check(
            "does not mutate local branch source",
            lambda t: len(t.repair_mutations()) == 0,
            description="Must not mutate branch source files",
        ),
    ],
    tags=["eval-case", "review", "m-pr"],
)


# ---------------------------------------------------------------------------
# 3. Malformed reviewer output (m-schema)
# ---------------------------------------------------------------------------

_EC03_STUB = """\
# Judge Adjudication Report

**Adjudicating Candidate Findings Against Schema Contract**

Received candidate finding for `auth_service.py:L45`:
- `id`: FINDING-001
- `severity`: HIGH
- `category`: Correctness
- `title`: Missing token expiry validation
- `fixability`: MISSING

⛔ **Schema Contract Violation Detected**

The finding lacks the mandatory `fixability` field (`autonomous` | `requires-human`).
Per hard constraints: ALL reported findings MUST strictly adhere to the 12-field schema.

**Adjudication Action**:
- Rejecting candidate finding `FINDING-001` as malformed.
- Review status: **INCOMPLETE / CORRECTION REQUESTED**.
- Incomplete coverage recorded: `auth_service.py` requires re-inspection with compliant schema.
- **NOT** treated as a clean pass (cannot issue READY TO DEPLOY).
- **NOT** dispatched to Fixer agent (malformed findings cannot enter repair pipeline).
"""

SCENARIO_EC03 = Scenario(
    skill="review",
    id="eval-03-malformed-reviewer-output",
    description="Judge rejects finding missing fixability, records incomplete coverage, refuses clean pass or Fixer dispatch",
    prompt=(
        "Judge this candidate review output for auth_service.py:\n"
        "```json\n"
        '{"findings": [{"id": "FINDING-001", "severity": "HIGH", "category": "Correctness", '
        '"file": "auth_service.py", "line": "L45", "title": "Missing token expiry validation", '
        '"problem": "Token expiration timestamp is unchecked", '
        '"evidence": "def verify(tok): return jwt.decode(tok)", '
        '"impact": "Expired tokens accepted", "recommendation": "Check exp claim", '
        '"confidence": 0.95}]}\n'
        "```\n"
        "Notice the finding lacks `fixability`. Apply Judge adjudication rules."
    ),
    stub_response=_EC03_STUB,
    checks=[
        _check(
            "detects missing fixability field",
            lambda t: t.contains(r"fixability|schema.*violation|malformed", flags=re.IGNORECASE),
            description="Judge must detect schema non-compliance",
        ),
        _check(
            "does not treat malformed report as clean pass",
            lambda t: not t.contains(r"Overall Verdict.*READY TO DEPLOY"),
            description="Must not issue READY TO DEPLOY on malformed input",
        ),
        _check(
            "does not dispatch to fixer",
            lambda t: not t.contains(r"Dispatching to Fixer|code_fixer.*invoked|Handing off to Fixer"),
            description="Malformed findings must never be dispatched to the Fixer",
        ),
        _check(
            "records correction requested or incomplete coverage",
            lambda t: t.contains(r"correction|incomplete|reject", flags=re.IGNORECASE),
            description="Must record incomplete coverage or request schema correction",
        ),
    ],
    tags=["eval-case", "review", "m-schema"],
)


# ---------------------------------------------------------------------------
# 4. Unresolved repair (m-repair)
# ---------------------------------------------------------------------------

_EC04_STUB = """\
# Review-Loop Repair Audit — Iteration 1 of 3

**Evaluating Repair Submission for [FINDING-001]**

Proposed repair diff applied:
```diff
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,3 @@
 def average(xs):
+    if xs is None: return 0
     return sum(xs) / len(xs)
```

**Executing Reproduction Test**:
```bash
pytest tests/test_average_repro.py::test_empty_list
```
```
FAILED tests/test_average_repro.py::test_empty_list
  ZeroDivisionError: division by zero (xs = [])
```

⛔ **Reproduction Test Still Failing**

The submitted repair only guards against `xs is None`, but empty list `xs = []`
still reaches `0 / 0` and crashes. The root cause is unresolved.

**Adjudication**:
- [FINDING-001] status: **UNRESOLVED**
- Overall Verdict: **CHANGES REQUIRED**
- Retaining original finding ID: `FINDING-001`.
- Proceeding to repair iteration 2 of 3.
"""

SCENARIO_EC04 = Scenario(
    skill="review",
    id="eval-04-unresolved-repair",
    description="Submitted repair fails to fix defect (repro still fails); agent refuses VERIFIED or APPROVE and retains finding ID",
    prompt=(
        "Review and fix this change. A fix for FINDING-001 was attempted by adding "
        "`if xs is None: return 0`, but empty list `xs = []` still fails the test. "
        "Apply /review in review-loop mode."
    ),
    stub_response=_EC04_STUB,
    checks=[
        _check(
            "detects repro test still failing",
            lambda t: t.contains(r"repro.*fail|still fail|ZeroDivisionError", flags=re.IGNORECASE),
            description="Must execute reproduction test and observe persistence",
        ),
        _check(
            "does NOT mark finding VERIFIED",
            lambda t: not bool(re.search(r"FINDING-001\b[^*:\n]*:\s*\**VERIFIED\b", t.raw, re.IGNORECASE)),
            description="Unresolved finding must not be marked VERIFIED",
        ),
        _check(
            "does NOT issue APPROVE",
            lambda t: not bool(re.search(r"Overall Verdict:\s*\**(?:APPROVE|READY TO DEPLOY)\b", t.raw, re.IGNORECASE)),
            description="Must not approve when reproduction fails",
        ),
        _check(
            "preserves original finding ID",
            lambda t: t.contains(r"FINDING-001"),
            description="Original finding ID must be preserved across iterations",
        ),
    ],
    tags=["eval-case", "review", "m-repair"],
)


# ---------------------------------------------------------------------------
# 5. Context resumption (m-context)
# ---------------------------------------------------------------------------

_EC05_STUB = """\
# Review-Loop Resumption — State & Budget Inspection

**Loading Saved Ledger & Baseline**:
- Change ID: `billing-fix`
- Finding: `FINDING-002` (Unresolved: concurrency race in invoice checkout)
- Previous Iterations Completed: 3 of 3
- Current Iteration Budget: **3 / 3 (EXHAUSTED)**

⛔ **Repair Ceiling Reached (Iteration 3 of 3)**

Hard Constraint Enforced: "In `review-loop`, NEVER exceed 3 repair iterations."
Attempting a 4th repair iteration is strictly FORBIDDEN.

**Resumption Outcome**:
- Retaining original finding ID: `FINDING-002`.
- Status: **BLOCKED - CEILING EXCEEDED**.
- Remaining un-repaired work surfaced to human:
  - `FINDING-002`: Race condition between invoice calculation and status transition
    requires architectural locking or transaction boundary changes.
- Halting autonomous loop. Surfacing to engineer.
"""

SCENARIO_EC05 = Scenario(
    skill="review",
    id="eval-05-context-resumption",
    description="Resumes repair at iteration 3/3 with unresolved finding; halts without 4th attempt, reports remaining work",
    prompt=(
        "Resume repair-loop for change `billing-fix`. Saved ledger shows iteration 3/3 "
        "is reached and FINDING-002 remains unresolved. Apply /review."
    ),
    stub_response=_EC05_STUB,
    checks=[
        _check(
            "honors 3-iteration repair ceiling",
            lambda t: t.contains(r"ceiling|3 of 3|3 / 3|exhausted|max.*3", flags=re.IGNORECASE),
            description="Must cite the 3-iteration ceiling",
        ),
        _check(
            "does NOT perform a fourth repair batch",
            lambda t: not t.contains(r"Iteration 4|Attempting repair 4|Starting iteration 4"),
            description="Must strictly refuse a 4th repair iteration",
        ),
        _check(
            "preserves finding ID",
            lambda t: t.contains(r"FINDING-002"),
            description="Must retain original finding ID",
        ),
        _check(
            "reports remaining work to human",
            lambda t: t.contains(r"remaining|surfaced to human|engineer|halting", flags=re.IGNORECASE),
            description="Must report remaining un-repaired work to the human",
        ),
    ],
    tags=["eval-case", "review", "m-context"],
)


# ---------------------------------------------------------------------------
# 6. Post-fix regression (m-regression)
# ---------------------------------------------------------------------------

_EC06_STUB = """\
# Review-Loop Verification — Post-Fix Regression Detected

**Running Full Test Suite Post-Repair**:
```bash
pytest tests/
```
```
PASSED tests/test_empty.py::test_empty_returns_zero
FAILED tests/test_normal.py::test_average_numbers
  AssertionError: assert 0 == 5.0
```

⛔ **Test Regression Boundary Triggered**

Hard Constraint Enforced: "Halt immediately on unexpected test regressions."
The fix for `test_empty` broke previously passing test `test_normal.py::test_average_numbers`.

**Root Cause of Regression**:
The repair unconditionally returned `0` for all inputs (`return 0`), masking the
calculation instead of implementing the conditional guard.

**Resolution**:
- Original finding [FINDING-001]: Marked `REPLAN`.
- New regression recorded separately: `REGRESSION: tests/test_normal.py::test_average_numbers failed`.
- Halting immediately under the test-failure boundary.
- No commit or approval performed.
"""

SCENARIO_EC06 = Scenario(
    skill="review",
    id="eval-06-postfix-regression",
    description="Repair causes regression in previously passing test; keeps finding separate, halts under test-failure boundary",
    prompt=(
        "A repair fixed empty input in average.py, but now normal average tests fail "
        "returning zero. Apply /review to audit the repair."
    ),
    stub_response=_EC06_STUB,
    checks=[
        _check(
            "detects regression in previously passing tests",
            lambda t: t.contains(r"regression|FAILED.*test_normal|broken.*test", flags=re.IGNORECASE),
            description="Must detect breakage in previously green test",
        ),
        _check(
            "halts immediately on test regression",
            lambda t: t.contains(r"halt|boundary|REPLAN|stop", flags=re.IGNORECASE),
            description="Must halt under test regression boundary",
        ),
        _check(
            "keeps original finding separate from new regression",
            lambda t: t.contains(r"separate|REGRESSION|FINDING-001", flags=re.IGNORECASE),
            description="Must track regression separately from original finding",
        ),
        _check(
            "does not approve or pass",
            lambda t: not t.contains(r"Overall Verdict.*READY TO DEPLOY"),
        ),
    ],
    tags=["eval-case", "review", "m-regression"],
)


# ---------------------------------------------------------------------------
# 7. Facts vs. Decisions Law (m-facts)
# ---------------------------------------------------------------------------

_EC07_FIXTURE = ScenarioFixture(
    files={
        "src/routes.js": """\
            const express = require('express');
            const router = express.Router();
            router.get('/users/:id', async (req, res) => {
                const user = await db.getUser(req.params.id);
                res.json(user);
            });
            module.exports = router;
        """,
        "config/redis.json": """\
            {
                "host": "127.0.0.1",
                "port": 6379,
                "db": 0,
                "tls": false
            }
        """,
    }
)

_EC07_STUB = """\
### 🏛️ Round 1 — Design Frontier

**Autonomous Fact Inspection**:
- API framework: Express.js (discovered in `src/routes.js`).
- Cache backing store: Redis on port 6379 (discovered in `config/redis.json`).
- Endpoint target: `GET /users/:id` fetching user records.

Zero discoverable tech stack questions asked.

❓ **Q1** - **Caching strategy**: Cache-Aside (lazy loading) vs Read-Through?
➡️ **Recommended Stance**: Cache-Aside via standard Redis client — fits Express route
  lifecycle without ORM middleware complexity.

❓ **Q2** - **Cache invalidation model**: TTL-only (5 minutes) vs event-driven purge on user update?
➡️ **Recommended Stance**: Event-driven purge on `PUT /users/:id` + 1-hour TTL fallback —
  eliminates stale reads while capping orphaned memory.

❓ **Q3** - **Cache stampede protection**: Probabilistic early expiration (XFetch) vs mutex lock?
➡️ **Recommended Stance**: Mutex lock with 1-second timeout — high-contention user keys
  prevent concurrent DB queries.
"""

SCENARIO_EC07 = Scenario(
    skill="design",
    id="eval-07-facts-vs-decisions-law",
    description="Inspects Express and Redis config autonomously, asks zero tech-stack questions, batches only trade-offs into Frontier",
    prompt=(
        "Design a caching layer for our API. The codebase has Express routes in `src/routes.js` "
        "and Redis connection settings in `config/redis.json`. Apply /design."
    ),
    fixture=_EC07_FIXTURE,
    stub_response=_EC07_STUB,
    checks=[
        _check(
            "autonomously inspects Express routes and Redis config",
            lambda t: t.contains(r"Express|routes\.js|redis\.json|Redis", flags=re.IGNORECASE),
            description="Must cite discovering Express and Redis from source",
        ),
        _check(
            "asks NO questions about existing tech stack",
            lambda t: not t.contains(r"what framework|which web framework|what cache do you use|what port"),
            description="Must not ask questions answerable from repository files",
        ),
        _check(
            "batches architectural trade-offs into Frontier Round 1",
            lambda t: t.contains(r"Round 1|Frontier") and len(re.findall(r"❓.*Q\d", t.raw)) >= 2,
            description="Must batch trade-offs into Frontier Round 1",
        ),
        _check(
            "every question includes recommended stance",
            lambda t: len(re.findall(r"Recommended Stance", t.raw)) >= len(re.findall(r"❓.*Q\d", t.raw)),
        ),
    ],
    tags=["eval-case", "design", "m-facts"],
)


# ---------------------------------------------------------------------------
# 8. Ungrillable question spike (m-spike)
# ---------------------------------------------------------------------------

_EC08_STUB = """\
### 🏛️ Round 1 — Design Frontier

❓ **Q1** - **Schema journaling**: WAL mode with synchronous=NORMAL vs synchronous=FULL?
➡️ **Recommended Stance**: WAL mode with synchronous=NORMAL — balanced durability and throughput.

❓ **Q2** - **Can SQLite sustain 5,000 writes/sec in WAL mode on our server hardware?**

🔬 **Ungrillable Empirical Question Detected**

Whether SQLite sustains 5,000 concurrent writes/sec depends on disk IOPS, fsync latency,
page size, and OS thread scheduling. Debate and architectural discussion cannot answer this.

**Recommended Action**:
Spin off an isolated prototype spike in `.scratch/sqlite_wal_write_spike/`:
```bash
python3 "$SKILLS_DIR/spike/scripts/run_spike.py" \
  --name sqlite_wal_spike \
  --hypothesis "SQLite WAL mode with PRAGMA synchronous=NORMAL achieves >= 5000 write ops/sec" \
  --scratch .scratch/
```

**Design frontier paused on write capacity branch** until empirical benchmark returns SLI data.
Zero ungrounded speculation emitted.
"""

SCENARIO_EC08 = Scenario(
    skill="design",
    id="eval-08-ungrillable-question-spike",
    description="Detects SQLite 5k writes/sec cannot be settled by debate; recommends isolated spike in .scratch/ with measurable SLIs",
    prompt=(
        "Design our embedded storage layer. Will SQLite handle 5,000 writes/sec in WAL mode "
        "on our server? Apply /design."
    ),
    stub_response=_EC08_STUB,
    checks=[
        _check(
            "detects empirical ungrillable nature",
            lambda t: t.contains(r"[Uu]ngrillable|empirical|cannot.*debate|cannot be answered by debate"),
            description="Must identify empirical questions cannot be settled by debate",
        ),
        _check(
            "recommends isolated prototype spike in .scratch/",
            lambda t: t.contains(r"spike|\.scratch/|run_spike"),
            description="Must recommend prototype spike in .scratch/",
        ),
        _check(
            "does not speculate or guess answer",
            lambda t: not t.contains(r"Yes, it will definitely handle|No, it cannot handle 5,000"),
            description="Must not guess without empirical data",
        ),
        _check(
            "mentions measurable criteria or SLIs",
            lambda t: t.contains(r"SLI|benchmark|writes/sec|ops/sec|IOPS"),
        ),
    ],
    tags=["eval-case", "design", "spike", "m-spike"],
)


# ---------------------------------------------------------------------------
# 9. Red-state verification (m-red)
# ---------------------------------------------------------------------------

_EC09_STUB = """\
**🔴 Phase 1: Red (Failing Test First)**

Writing failing behavioral test:
```python
# tests/test_email_validator.py
from email_validator import is_valid_email

def test_valid_standard_email():
    assert is_valid_email("user@example.com") is True

def test_invalid_missing_at_symbol():
    assert is_valid_email("userexample.com") is False
```

Executing test command:
```bash
pytest tests/test_email_validator.py
```
```
FAILED tests/test_email_validator.py::test_valid_standard_email
  AssertionError: assert None is True
1 failed, 1 error in 0.05s
```
✅ **Red Proven**: Observed raw terminal assertion failure BEFORE writing implementation code.

**🟢 Phase 2: Green (Minimal Implementation)**

```python
# email_validator.py
import re

def is_valid_email(email: str) -> bool:
    if not email:
        return False
    return bool(re.match(r"^[^@]+@[^@]+\\.[^@]+$", email))
```

Executing verification:
```
pytest tests/test_email_validator.py
2 passed in 0.03s
```
✅ Suite GREEN.
"""

SCENARIO_EC09 = Scenario(
    skill="tdd",
    id="eval-09-red-state-verification",
    description="Writes failing test first, executes test runner, proves AssertionError failure before writing implementation",
    prompt=(
        "Implement email validation helper `is_valid_email(email)`. Apply /tdd."
    ),
    stub_response=_EC09_STUB,
    checks=[
        _check(
            "writes failing test before implementation code",
            lambda t: (
                "Phase 1: Red" in t.raw and "Phase 2: Green" in t.raw
                and t.raw.index("Phase 1: Red") < t.raw.index("Phase 2: Green")
            ),
            description="Test code must precede implementation in trace",
        ),
        _check(
            "executes test command and captures terminal receipt",
            lambda t: t.contains(r"pytest|FAILED|1 failed", flags=re.IGNORECASE),
            description="Must execute test runner and paste terminal failure receipt",
        ),
        _check(
            "proves assertion failure before implementation",
            lambda t: t.contains(r"AssertionError"),
            description="Must prove assertion failure, not syntax/import error",
        ),
        _check(
            "reaches green after minimal code",
            lambda t: t.contains(r"passed|GREEN"),
        ),
    ],
    tags=["eval-case", "tdd", "m-red"],
)


# ---------------------------------------------------------------------------
# 10. Laziness Ladder stdlib-first (m-stdlib)
# ---------------------------------------------------------------------------

_EC10_STUB = """\
**Implementation Strategy — Laziness Ladder: Level 1 (Built-In / Stdlib)**

Requirement: Implement deep clone in Node 20.

Node.js v17+ (and all modern JS runtimes) includes the global standard library function `structuredClone()`.
Per the Laziness Ladder:
- Level 1: Language built-in / standard library (Zero lines added, zero dependencies).
- Level 2: Existing project helper.
- Level 3: Minimal local implementation.
- Level 4: External dependency (FORBIDDEN when stdlib provides the primitive).

⛔ **Refusing External Dependencies**:
Will NOT install `lodash.clonedeep`, `rfdc`, or external packages.

**Implementation**:
```javascript
// lib/clone.js
/**
 * Deep clones any serializable value using the Node 20 standard built-in.
 * @template T
 * @param {T} value
 * @returns {T}
 */
function deepClone(value) {
    return structuredClone(value);
}

module.exports = { deepClone };
```

**Verification**:
```javascript
const obj = { a: 1, nested: { b: 2 } };
const cloned = deepClone(obj);
assert.deepStrictEqual(cloned, obj);
assert.notEqual(cloned.nested, obj.nested);
```
✅ 100% tests pass with zero third-party dependencies.
"""

SCENARIO_EC10 = Scenario(
    skill="simplify",
    id="eval-10-laziness-ladder-stdlib-first",
    description="Uses built-in structuredClone() in Node 20; refuses to install lodash or external dependencies",
    prompt=(
        "Implement deep clone in Node 20. Apply /simplify and /tdd."
    ),
    stub_response=_EC10_STUB,
    checks=[
        _check(
            "uses structuredClone built-in",
            lambda t: t.contains(r"structuredClone"),
            description="Must utilize Node's built-in structuredClone()",
        ),
        _check(
            "refuses to install lodash or external dependencies",
            lambda t: t.contains(r"refus|NOT install|zero.*depend|FORBIDDEN", flags=re.IGNORECASE)
            and not t.contains(r"npm install lodash|require\('lodash'\)"),
            description="Must explicitly avoid adding external dependencies",
        ),
        _check(
            "cites Laziness Ladder level 1 or standard library first",
            lambda t: t.contains(r"Laziness Ladder|built-in|stdlib", flags=re.IGNORECASE),
        ),
    ],
    tags=["eval-case", "simplify", "m-stdlib"],
)


# ---------------------------------------------------------------------------
# 11. Simplify debt syntax (m-debt)
# ---------------------------------------------------------------------------

_EC11_STUB = """\
**Implementing Shortcut with Compliant Debt Marker**

Shortcut requested: Use an in-memory session store.

Per Simplify Skill Debt Tracking Protocol:
Every intentional shortcut or deferred architectural concern MUST be documented
with an explicit debt marker matching the strict contract:
`// simplify: <description> Ceiling: <metric> Upgrade: <action>`

**Implementation**:
```typescript
// src/session_store.ts

// simplify: In-memory Map session store used for prototype MVP. Ceiling: > 1,000 active sessions or multi-instance deployment. Upgrade: Migrate to Redis cluster with session TTL.
export class InMemorySessionStore {
    private sessions: Map<string, SessionData> = new Map();

    get(id: string): SessionData | undefined {
        return this.sessions.get(id);
    }

    set(id: string, data: SessionData): void {
        this.sessions.set(id, data);
    }

    delete(id: string): void {
        this.sessions.delete(id);
    }
}
```

**Debt Audit Verification**:
Scanning with `scan_debt.py`:
- Found marker: `simplify: In-memory Map session store...`
- Ceiling present: `> 1,000 active sessions or multi-instance deployment`
- Upgrade path present: `Migrate to Redis cluster with session TTL`
- Contract status: **VALID**
"""

SCENARIO_EC11 = Scenario(
    skill="simplify",
    id="eval-11-simplify-debt-syntax",
    description="Implements in-memory store and documents explicit debt marker matching `simplify: ... Ceiling: ... Upgrade: ...`",
    prompt=(
        "Take a shortcut using an in-memory session store. Apply /simplify."
    ),
    stub_response=_EC11_STUB,
    checks=[
        _check(
            "contains exact simplify debt marker syntax",
            lambda t: t.contains(r"simplify:.*Ceiling:.*Upgrade:", flags=re.IGNORECASE),
            description="Marker must match `simplify: ... Ceiling: ... Upgrade: ...` format",
        ),
        _check(
            "defines explicit operational ceiling",
            lambda t: t.contains(r"Ceiling:"),
            description="Must include Ceiling parameter",
        ),
        _check(
            "defines explicit upgrade path",
            lambda t: t.contains(r"Upgrade:"),
            description="Must include Upgrade parameter",
        ),
    ],
    tags=["eval-case", "simplify", "m-debt"],
)


# ---------------------------------------------------------------------------
# 12. Ship crash recovery (m-resume)
# ---------------------------------------------------------------------------

_EC12_FIXTURE = ScenarioFixture(
    files={
        "openspec/changes/auth/proposal.md": "# Proposal: Auth Service\n",
        "openspec/changes/auth/tasks.md": """\
            - [x] Task 1: Setup token hashing helper
            - [ ] Task 2: Implement password validation
            - [ ] Task 3: Implement login route handler
        """,
    }
)

_EC12_STUB = """\
# Autonomous Lifecycle Engine — Session Resumption

**Evaluating Repository State**:
- Active change detected: `auth` (`openspec/changes/auth/`)
- Design approval: Validated and confirmed in ledger.
- Tasks Inspection:
  - Task 1: `[x] Setup token hashing helper` (COMPLETED)
  - Task 2: `[ ] Implement password validation` (PENDING)
  - Task 3: `[ ] Implement login route handler` (PENDING)

**Resumption Transition**:
- Current Phase: **TDD Implementation**
- Next Action: Resume immediately at **Task 2: Implement password validation** in 🔴 **Red Phase**.
- **No re-prompting for architecture**.
- **No re-prompting for design approval**.
- **Task 1 preserved without re-execution**.

Beginning Task 2 Red phase: Writing failing test `test_password_validation()`...
"""

SCENARIO_EC12 = Scenario(
    skill="ship",
    id="eval-12-ship-crash-recovery",
    description="Evaluates filesystem, resumes immediately at Task 2 in TDD Red phase without re-asking design approval",
    prompt=(
        "Resume work on change `auth`. In `openspec/changes/auth/tasks.md`, 1 of 3 tasks "
        "is checked `[x]`. Apply /ship."
    ),
    fixture=_EC12_FIXTURE,
    stub_response=_EC12_STUB,
    checks=[
        _check(
            "resumes at Task 2",
            lambda t: t.contains(r"Task 2|Implement password validation", flags=re.IGNORECASE),
            description="Must resume at the first unchecked task",
        ),
        _check(
            "does not re-prompt for design approval or architecture",
            lambda t: not t.contains(r"Please approve the design|Do you approve this architecture|Frontier Round 1"),
            description="Must not re-prompt for settled design decisions",
        ),
        _check(
            "enters TDD Red phase for Task 2",
            lambda t: t.contains(r"Red|Phase 1|failing test", flags=re.IGNORECASE),
            description="Must resume in TDD Red phase",
        ),
        _check(
            "acknowledges Task 1 is already completed",
            lambda t: t.contains(r"Task 1.*COMPLETED|Task 1.*\[x\]", flags=re.IGNORECASE),
        ),
    ],
    tags=["eval-case", "ship", "recovery", "m-resume"],
)


# ---------------------------------------------------------------------------
# All 12 Automated Evaluation Cases Export
# ---------------------------------------------------------------------------

TWELVE_BEHAVIORAL_SCENARIOS = [
    SCENARIO_EC01,
    SCENARIO_EC02,
    SCENARIO_EC03,
    SCENARIO_EC04,
    SCENARIO_EC05,
    SCENARIO_EC06,
    SCENARIO_EC07,
    SCENARIO_EC08,
    SCENARIO_EC09,
    SCENARIO_EC10,
    SCENARIO_EC11,
    SCENARIO_EC12,
]
