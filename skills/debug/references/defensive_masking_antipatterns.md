# Defensive Masking & Debugging Anti-Patterns

A catalog of forbidden symptom patches, anti-patterns, and anti-cheat violations.

---

## 1. Forbidden Symptom Patches

| Forbidden Anti-Pattern | Why It Is Rejected | The Correct Root-Cause Fix |
|---|---|---|
| `if obj is not None:` (at crash site) | Masks upstream null creation; leaves corrupted state in memory | Trace why `obj` was None and ensure the constructor/loader fulfills the contract |
| `try: ... except Exception: pass` | Swallows errors silently; causes mysterious downstream failures | Allow exception to bubble up, or catch only specific typed exceptions and handle explicitly |
| `time.sleep(2.0)` (for race conditions) | Flaky, slow, and hides concurrency flaws | Use condition polling, synchronization primitives, or explicit completion callbacks |
| Fallback defaults on unexpected errors | Hides data corruption and prevents detection of regressions | Fail fast at the boundary; validate schemas strictly upon ingestion |

---

## 2. Forbidden Test-Cheat Anti-Patterns

- ❌ **Deleting or Commenting Out Assertions**: Never remove an assertion from an existing test to make the test suite pass.
- ❌ **Adding `@pytest.mark.skip` / `xit()`**: Never disable a failing test instead of fixing the underlying code.
- ❌ **Loosening Invariants**: Changing `assert result == 42` to `assert result is not None` to disguise wrong calculations.
- ❌ **Over-Mocking the Failure**: Mocking away the component that threw the error instead of fixing the component.

---

## 3. The 3-Strike Architectural Circuit Breaker

When attempting to fix a bug:
- **Attempt 1 Failed**: Analyze the new failure evidence.
- **Attempt 2 Failed**: Re-evaluate the hypothesis from scratch (Two-Strike Rethink).
- **Attempt 3 Failed**: **STOP ALL FIX ATTEMPTS**.

If 3 distinct fixes have failed, or if each fix reveals a new breakage in a different subsystem:
**The problem is not a bug; it is an architectural flaw.**
Continuing to guess and patch will only produce spaghetti code. STOP immediately and report the architectural contradiction to the human engineer.
