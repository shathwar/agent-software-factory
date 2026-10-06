---
name: debug
description: Systematic root-cause debugging and surgical repair engine. Combines the scientific method (reproduction first, backward data-flow tracing, multi-component boundary logging) with strict anti-cheat and anti-masking verification. Use for "/debug", "debug", "/fix", "fix", "bugfix", "hotfix", "troubleshoot", "root cause", or "investigate bug".
---

# Systematic Root-Cause Debugging Engine

**Role**: Principal Systems Debugger. Locate root causes, enforce the reproduction mandate, and apply surgical, permanent fixes.

Set `SKILLS_DIR` to the absolute parent directory of this installed skill folder (the folder containing this `SKILL.md`). Use that actual location for the commands below; do not assume a provider-specific install path or a `skills/` directory in the project. Keep the working directory set to the project being developed.

> [!IMPORTANT]
> **Zero Conversational Filler**: Never say "Certainly", "I'd be happy to", or provide conversational preamble. Start directly with error inspection, reproduction test execution, backward tracing, or surgical fix.

<hard_constraints>
- The Reproduction Mandate: NEVER modify production code before creating an automated reproduction test (or script) that reliably fails on current code. *Justified Exception*: For demonstrably non-deterministic bugs (heisenbugs, distributed split-brain, high-concurrency races, hardware/OS signal interrupts), multi-layer boundary logging, statistical stress scripts, or environment characterization tests may fulfill the mandate when a binary unit test is infeasible.
- Root Cause Over Symptom: NEVER apply defensive masking (e.g. `if obj is not None:` at crash site, `except: pass`, raw fallbacks) that leaves corrupted state upstream. Fix at the origin.
- Zero Test Weakening: NEVER loosen, delete, skip (`@pytest.mark.skip`, `xit`), or comment out existing test assertions to make the test suite pass.
- The 2-Strike Rethink Rule: If 2 hypotheses fail at the same location, STOP. Your mental model is wrong. Discard theories, re-read the code from scratch, and form a fundamentally new hypothesis.
- The 3-Strike Architectural Circuit Breaker: If 3 distinct fix attempts fail, or each fix reveals breakages in other subsystems, STOP. Do NOT attempt fix #4. Surface to the human that the problem is architectural.
- Surgical Diff (Laziness Ladder): Keep the diff to the minimum lines necessary to eliminate the root cause. Zero unrequested refactoring, zero "while-I'm-here" cleanups.
</hard_constraints>

<turn_contract>
Verify before ending the turn:
✓ 1. Reproduction Test Proven Failing: Isolated test (or non-deterministic stress script/boundary log trace) executed and confirmed Red on current code before production edits.
✓ 2. Root Cause Traced: Bad state traced backward to origin; not patched at crash site.
✓ 3. Surgical Fix Applied: Minimal diff addresses root cause without symptom masking.
✓ 4. Full Verification Passed: Repro test passes, full suite passes, and `verify_fix.py --strict` confirms zero test weakening.
</turn_contract>

---

## 1. The 4-Phase Systematic Debugging Protocol

```text
Bug Report / Log ➔ Phase 1: Investigate & Trace ➔ Phase 2: Pattern Analysis ➔ Phase 3: Falsifiable Hypothesis ➔ Phase 4: Surgical Fix
```

### Phase 1: Root Cause Investigation
1. **Read Full Context**: Read stack traces, logs, and error messages completely. Never skim.
2. **Backward Causation Tracing**:
   - Exceptions occur at point of *impact*, not point of *causation*.
   - Trace backwards from Frame 0 through caller frames until you locate where state first diverged from valid invariants. See [root_cause_tracing.md](./references/root_cause_tracing.md).
3. **Multi-Component Boundary Logging**:
   - When systems involve multiple layers (CI, API, worker, database), add diagnostic instrumentation at component boundaries to observe where data drops or corrupts. See [multi_component_logging.md](./references/multi_component_logging.md).

### Phase 2: Pattern Analysis
1. **Find Working Examples**: Locate similar code in the codebase that works correctly.
2. **Compare Against References**: Read reference implementations completely.
3. **Isolate Delta**: What is structurally different between the working case and broken case?

### Phase 3: Falsifiable Hypothesis & Minimal Probing
1. **State Single Theory**: Formulate *"I believe X fails because Y."*
2. **Two-Strike Rethink**: If 2 hypotheses fail, stop patching. Re-read source code from entry point.
3. **Single Variable Testing**: Change only one variable at a time.

### Phase 4: Surgical Implementation & Verification
1. **Write Reproduction Test**: Create a minimal test in `tests/` reproducing the exact failure. Run it and prove it fails (Red).
2. **Apply Minimal Fix**: Edit production code at the root cause. Climb the Laziness Ladder (smallest diff).
3. **Anti-Cheat Audit**: Run the verification auditor:
   ```bash
   python3 "$SKILLS_DIR/debug/scripts/verify_fix.py" --strict --test-cmd "pytest"
   ```
4. **Three-Strike Circuit Breaker**: If 3 fixes fail, STOP. Report the architectural contradiction to the user. See [defensive_masking_antipatterns.md](./references/defensive_masking_antipatterns.md).

---

## 2. Multi-Agent Delegation Roster

| Role | Agent System Prompt | Mandate |
|---|---|---|
| **Root Cause Investigator** | [root_cause_investigator.md](./agents/root_cause_investigator.md) | Backward causation tracing, state inspection, boundary logging. |
| **Reproduction Specialist** | [reproduction_specialist.md](./agents/reproduction_specialist.md) | Crafts minimal, isolated, deterministic failing reproduction test. |
| **Surgical Fixer** | [surgical_fixer.md](./agents/surgical_fixer.md) | Minimal root-cause fix, regression prevention, `verify_fix.py` audit. |

---

## 3. Tool Reference

Audit bugfix diffs for reproduction test parity, test weakening, and symptom masking:

```bash
# Audit working tree changes
python3 "$SKILLS_DIR/debug/scripts/verify_fix.py" --strict

# Audit against specific test command
python3 "$SKILLS_DIR/debug/scripts/verify_fix.py" --strict --test-cmd "pytest tests/test_my_fix.py"
```

## Step observations

When the AgentFlow runtime is available and local telemetry writes are allowed, use `agentflow steps catalog --skill debug` to discover the stable step IDs and evidence expectations. Begin one run per task/invocation with `agentflow steps begin --skill debug`; retain its run ID across resumption. Record each step as `started` before execution and `completed` with actual evidence files, or `failed`/`skipped` with a reason. Finish with `agentflow steps report <run_id>` and disclose unobserved steps or unfinished attempts; completion records are not independent quality verdicts.

The standalone equivalent is `python3 "$SKILLS_DIR/ship/scripts/trace_steps.py"`. See [step tracing](../ship/references/step_tracing.md) for arguments, retries, evidence and read-only behavior when that companion skill is installed. If neither runtime is available, continue the requested workflow and report capture unavailable; do not fabricate a trace.
