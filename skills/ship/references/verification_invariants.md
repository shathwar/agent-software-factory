# Foundational Architectural Invariants: Verification & Convergence

This document establishes the **8 Foundational Architectural Invariants** of AgentFlow.

> **Core System Guarantee**:  
> *Autonomy is permitted to continue only while the system can demonstrate bounded progress toward a verifiable state.*

---

## The 8 Invariants

```
                   ┌─────────────────────────────────────────┐
                   │          Convergence Controller         │
                   │                                         │
                   │  attempts / budget / cycles / delta     │
                   │  repeated failures / oscillation / time │
                   └────────────────────┬────────────────────┘
                                        │
                                        ▼
      Claim ──────► Evidence ──────► Independent Verification
        ▲                                    │
        │                                    │
        └──────── Remediation (Fail) ◄───────┘
```
When verification succeeds:
```
VERIFIED ──► Convergence Controller (certify_convergence) ──► Gate Decision ──► PASS / DELIVERY_READY
```

---

### Invariant 1: No evidence → no verification
- **Axiom**: An independent verifier cannot verify the absence of evidence.
- **Enforcement**: If no test command, no evidence envelope, or empty claims are presented, the verifier rejects with `NOT_VERIFIED` or `INCONCLUSIVE`. Verification never fabricates or presumes evidence.
- **Failure Mode**: Bypassing evidence submission results in immediate rejection at Tier 1 (Structural) or Tier 2 (Grounding).

### Invariant 2: No independent verification → no gate pass
- **Axiom**: Agent self-attestation is insufficient to pass lifecycle phase gates.
- **Enforcement**: `validate_delivery_readiness` blocks any change that has failing or missing verification records in the ledger (`VERIFICATION_FAILED`). The engine executes out-of-band verification (e.g. `verify_review_grounding`, `execute_and_verify_tests`) prior to clearing gates.
- **Failure Mode**: If independent verification fails at any tier, delivery is blocked and remediation is routed to the appropriate craftsman.

### Invariant 3: VERIFIED ≠ PASS
- **Axiom**: Verification establishes a specific factual claim; the gate evaluates the complete holistic policy.
- **Enforcement**: An independent verifier only establishes whether a technical claim is true (e.g., "Tests exit with code 0", "Review quotes exist in source"). The phase gate evaluates the broader organizational policy:
  - All tasks in `tasks.md` completed ($N/N$)
  - Architecture Decision Record (ADR) accepted and fingerprint valid
  - Zero code debt
  - Clean git working tree
  - Passing Judge review
  - Certified convergence within budgets
- **Failure Mode**: A change with `VERIFIED` test execution will still be blocked at `TDD_ACTIVE` if tasks remain unfinished or at `DESIGN_APPROVAL_REQUIRED` if ADR is missing.

### Invariant 4: Every remediation attempt gets a new evidence set; don't mutate the evidence that caused the failure
- **Axiom**: Ledger history is append-only and immutable.
- **Enforcement**: When an agent fails a gate or verification, the failing evidence is preserved verbatim in the transaction ledger (`turns` history). Remediation appends a **new** turn with a fresh, distinct evidence set and increments the change revision counter ($r1 \to r2 \to r3$).
- **Failure Mode**: No in-place mutation of prior evidence is permitted; tampering with prior turns invalidates ledger integrity.

### Invariant 5: Every loop iteration is bounded and recorded
- **Axiom**: Unbounded loops are strictly prohibited in autonomous engineering.
- **Enforcement**: Every loop iteration records an auditable turn with an immutable ID (`turn-001`, `turn-002`), UTC timestamp, skill, inputs, evidence, and state delta. The `ConvergenceController` continuously monitors iteration counts and terminates cycles that exceed configured limits.
- **Failure Mode**: Turn counts exceeding `max_total_turns` (default 25) or remediation cycles exceeding `max_remediation_attempts` (default 3) immediately trigger autonomy halt.

### Invariant 6: No progress / oscillation / repeated failure → halt
- **Axiom**: The system must detect and halt non-converging trajectories.
- **Enforcement**: 5 dedicated stagnation detectors evaluate the closed loop:
  1. `SAME_EVIDENCE`: Identical evidence submitted consecutively.
  2. `SAME_FINDING`: Identical defect findings recurring without resolution.
  3. `SAME_PATCH`: Workspace diff / tree fingerprint unchanged across remediation turns.
  4. `SAME_VERIFIER_FAILURE`: Identical independent verifier failures recurring consecutively.
  5. `OSCILLATING_STATE`: Cyclical thrashing between conflicting states ($A \leftrightarrow B$).
- **Failure Mode**: Transitions immediately to `AUTONOMY_HALTED` with `reason = NON_CONVERGING_REMEDIATION`.

### Invariant 7: A halted workflow cannot silently transition to delivery
- **Axiom**: Once halted, autonomous advancement is locked.
- **Enforcement**: Both `determine_lifecycle_state` and `validate_delivery_readiness` evaluate halt blockers upfront. `ConvergenceController.certify_convergence` explicitly refuses certification while a halt blocker exists.
- **Recovery**: The only path to recovery is human intervention via `agentflow resume <change>`, which records human supervisory provenance in the ledger.

### Invariant 8: The final gate decision references the exact verified evidence and revision
- **Axiom**: A delivery approval is cryptographically and structurally bound to a single immutable snapshot.
- **Enforcement**: Delivery gate clearance and trailers bind to:
  - Exact revision counter (`Ship-Revision: r<N>`)
  - Exact commit SHA (`snapshot_sha`)
  - Exact working-tree fingerprint (`snapshot_fingerprint`)
- **Failure Mode**: Any unreviewed or post-verification modification to source files immediately invalidates the approval, resetting the state to `STALE` and blocking delivery.
