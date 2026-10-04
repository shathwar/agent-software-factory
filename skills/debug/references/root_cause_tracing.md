# Backward Root-Cause Tracing Technique

Technique for tracing defective behavior and corrupted state backward from the crash site to the originating trigger.

---

## 1. The Causation Principle

> **Rule**: An exception occurs at the point of *impact*, not at the point of *causation*.

When a crash or assertion failure occurs:
- Frame 0 (crash line) is almost never where the bug originated. It is simply where invalid state finally became intolerable (e.g. `AttributeError: 'NoneType' object has no attribute 'execute'`).
- Fixing Frame 0 by adding `if obj is not None:` patches the symptom while leaving the corrupted state upstream to manifest elsewhere.

---

## 2. The 4-Step Backward Walk

```text
Crash Site (Frame 0)
    ▲
    │ 1. What variable is invalid?
    │
Caller (Frame 1)
    ▲
    │ 2. What passed that value into Frame 0?
    │
Upstream Caller (Frame 2)
    ▲
    │ 3. Where was that value originally computed, parsed, or mutated?
    │
State Origin (Frame N) ──▶ THE ROOT CAUSE: Fix here!
```

1. **Isolate the Corrupted Variable**: At the point of failure, name the exact variable or property that is missing, wrong type, or invalid.
2. **Ascend One Stack Frame**: Check the caller's arguments. Was the value already invalid when passed into the function?
3. **Repeat Until State Diverges from Invariants**: Continue moving up the call tree until you find the exact frame where the value was still valid *before* a computation, but invalid *after*.
4. **Fix at the Origin**: The bug is at the line that created or mutated the corrupted value, or at the missing invariant check at the system's ingestion boundary.

---

## 3. The "Five Whys" Causation Chain

To prevent stopping at intermediate symptoms, walk the causality chain backward using the "Five Whys" technique:

| Depth | Question | Example |
|---|---|---|
| **Why 1** | Why did the process crash or test fail? | Crash at `user.profile.avatar_url`: `NoneType` has no attribute `avatar_url`. |
| **Why 2** | Why was `profile` None? | `get_user_profile(user_id)` returned `None` instead of default object. |
| **Why 3** | Why did `get_user_profile` return None? | Database query returned empty result due to cache miss fallback bug. |
| **Why 4** | Why did the cache miss fallback fail? | Cache fallback assumed user record always exists in SQL if present in Redis. |
| **Why 5** | **Root Cause** | Incomplete transactional rollback deleted SQL row but left stale Redis key. |

### Post-Mortem Causality Template

When concluding root-cause investigation, document findings using this structure:

```markdown
### Root Cause Causality Chain (Five Whys)
1. **Symptom**: [Crash or assertion failure observed at point of impact]
2. **Intermediate State**: [Invalid variable or state in immediate caller]
3. **Propagating Fault**: [Function or subsystem that passed unvalidated state]
4. **Trigger**: [Specific edge case, concurrent event, or missing invariant check]
5. **Root Cause**: [Fundamental defect at origin of state creation/mutation]
```

---

## 4. The "Two Strikes, Rethink" Rule

If you form a hypothesis about where the bug is, test it, and your proposed fix does not resolve the issue:
- **Strike 1**: Refine your observation, check state assumptions.
- **Strike 2**: **STOP IMMEDIATELY**.
If two hypotheses fail at the same location, **your mental model of the system is incorrect**.
Do not attempt a third patch on that function. Step back, re-read the code from the entry point, inspect the actual runtime data flow, and form a fundamentally new hypothesis.
