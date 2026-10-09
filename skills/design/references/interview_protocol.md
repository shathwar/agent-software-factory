# Interview Protocol & Frontier Algorithm

This document defines the operational mechanics for executing an adversarial system design interview. Adherence to these rules guarantees an exhaustive, disciplined inquiry while avoiding cognitive fatigue.

---

## 1. The Design Tree & Frontier Mechanics

### What is the Design Tree?
A design tree represents the problem space as a directed acyclic graph (DAG) of architectural decisions.
- **Root decisions** are foundational: data models, primary state store, network boundaries.
- **Branch decisions** hang off root decisions: caching strategy, lock granularity, retry policies.
- **Leaf decisions** represent fine-grained tactical choices: library selection, metric naming, timeout values.

### Computing the Frontier
The **Frontier** is defined as:
$$\text{Frontier} = \{ D \in \text{Decisions} \mid \text{Prerequisites}(D) \subseteq \text{Settled Decisions} \land D \notin \text{Settled Decisions} \}$$

In plain terms:
- A decision belongs to the current frontier **if and only if all decisions it depends on have already been decided**.
- If Decision B depends on whether we choose PostgreSQL or Redis (Decision A), **Decision B CANNOT be asked in Round 1**. It belongs to a later round.
- Asking premature dependent questions forces the user to make hypothetical guesses that get invalidated later.

---

## 2. Round-Based Batching

### Why Rounds?
1. **Low Cognitive Switching**: One-by-one interrogation creates a high-friction ping-pong dynamic. Asking 20 disconnected questions at once creates overwhelming cognitive overload.
2. **Optimal Density**: A typical well-run session resolves 25–40 questions across 3–5 rounds.
3. **Number-based or Instant Single-Word Responses**: Because each question in a round is numbered and carries a recommended stance, the user can review the frontier in parallel and answer succinctly:
   ```text
   # Full approval in 1 second:
   LGTM
   # Or "Accept all"

   # Or targeted overrides:
   1. Recommended stance.
   2. Option B (we must avoid Kafka due to operational complexity).
   3. No, keep it synchronous with a 2-second timeout.
   ```
4. **Tiered Ceremony**: Not every change warrants 3–5 rounds.
   - **Tier 1 (Targeted / Low-Risk)**: 1 batched round max (or proceed directly if uncontested). Allows single uncontested options in ADRs.
   - **Tier 2 (Architectural / High-Risk)**: Full frontier tree exploration across the 5 systems domains.

### Structuring a Round
Every question in a round must include:
1. **Identifier & Title**: `❓ **Q[N]** - **<Concise Title>**: `
2. **Context & Trade-offs**: Why this decision matters now, what options exist, and the failure consequence of choosing poorly.
3. **The Recommended Stance line (`➡️`)**: An unambiguous technical recommendation backed by Senior Principal Engineering principles.

---

## 3. The Facts vs. Decisions Rule

| Category | Definition | Responsibility | Action |
|---|---|---|---|
| **Fact** | An empirical truth verifiable from the codebase, git history, configuration, or environment. | **Principal Architect (Agent)** | Inspect files, grep callers, check schemas, search docs. **Never ask the user.** |
| **Decision** | A choice between valid architectural trade-offs, consistency models, cost constraints, or business priorities. | **Author / Engineer (User)** | Formulate the question in the frontier round and wait for user response. |

### Handling Background Research
When a frontier question requires settling a code fact first:
- Do not stall the entire round.
- Settle the fact via file tools or a background sub-agent.
- Any decision that strictly depends on that fact waits for the *next* round; all other independent frontier decisions are asked *now*.

---

## 4. Detecting "Ungrillable" Questions

An ungrillable question is one where **dialogue cannot replace empirical evidence**:

### Indicators of Ungrillable Questions:
- *"Will this query complete under 5ms with 10M rows?"* (Needs an `EXPLAIN ANALYZE` on a representative dataset).
- *"How does the drag-and-drop interaction feel to the user?"* (Needs a visual spike or interactive wireframe).
- *"Does the third-party partner API support concurrent webhooks without dropping packets?"* (Needs an empirical sandbox probe).

### What to do when an Ungrillable Question is detected:
1. Explicitly label the question as `[UNGRILLABLE - EMPIRICAL SPIKE REQUIRED]`.
2. Do not let the user guess or talk through it endlessly.
3. Define the exact, timeboxed spike needed using [`spike`](../../spike/SKILL.md):
   > *"We cannot settle Q3 through discussion alone. Recommendation: Build a 30-minute throwaway prototype to benchmark XYZ, inspect the latency, and return to resume grilling."*
4. Freeze that specific branch and continue grilling the remaining independent branches.

---

## 5. The Confirmation Gate & Session Termination

The interview is complete when:
1. **Frontier is Empty**: Every branch of the design tree has been explored down to actionable technical clarity.
2. **No Hand-Waving Remains**: No ambiguous sentences like *"we will handle errors properly"* or *"we'll use caching where needed"* are left unpinned.
3. **Confirmation Gate**:
   - The agent summarizes all settled decisions in an Executive Synthesis table.
   - The agent asks the user for final confirmation:
     > *"We have resolved all open branches of the design tree. Please review the synthesis above. Do you confirm this represents our shared architectural agreement before I compile the final ADR?"*
4. **Compile ADR**:
   - Upon confirmation, write the document according to [`adr_template.md`](./adr_template.md).
