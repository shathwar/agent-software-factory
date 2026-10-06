# UX Architecture & Layer Boundaries

The `ux` skill maintains a strict separation of concerns across four layers. The core UX skill and its references focus purely on **high-level requirements and orchestration**; they do not duplicate the specialist rule repositories of external tools.

```text
UX Core
    ↓ (high-level requirements)
Impeccable
    ↓ (visual implementation expertise)
Hallmark
    ↓ (anti-slop expertise)
audit_ux.py
    ↓ (deterministic checks)
```

---

## 1. UX Core: High-Level Requirements

**Owner**: `ux` skill & `skills/ux/references/`  
**Focus**: User intent, information architecture, mental models, interaction flows, accessibility contracts, and state completeness.

- **Primary Questions**:
  - What is the user trying to accomplish in $\le 3$ clicks?
  - Does the interface conform to Jakob Nielsen's 10 Usability Heuristics and Steve Krug's cognitive friction tests?
  - Are all states defined for the component's interaction model (Empty, Loading, Populated, Partial, Error/Recovery, Unavailable)?
  - Is error recovery immediate, clear, and actionable?
- **What UX Core Does NOT Do**: It does not specify micro-typography tracking, CSS optical alignment, or brand aesthetic flair.

---

## 2. Impeccable: Visual Implementation Expertise

**Owner**: External specialist skill ([pbakaus/impeccable](https://github.com/pbakaus/impeccable))  
**Focus**: Visual craft, optical balance, layout rhythm, micro-typography, and responsive adaptation.

- **Primary Questions**:
  - Are whitespace increments adhering to a consistent 4/8pt spacing rhythm?
  - Are font size, line-height (leading), measure (45–75ch), and tracking optically balanced?
  - Do icons vertically center with adjacent text?
  - Does the layout wrap fluidly without awkward text clipping or horizontal overflow?
- **Integration**: Invoked via subagent (`/impeccable polish <target>`) on the living rendered UI artifact. Bounded to a strict maximum of 2 refinement passes. Preserves the host project's root `DESIGN.md`.
- **Reference**: Consult [integrations/impeccable.md](../integrations/impeccable.md). The UX skill does not duplicate Impeccable's 60 detector rules.

---

## 3. Hallmark: Anti-Slop Expertise

**Owner**: External specialist skill ([nutlope/hallmark](https://github.com/nutlope/hallmark))  
**Focus**: Structural originality, editorial craft, and eliminating generic AI design clichés.

- **Primary Questions**:
  - Does the view suffer from predictable AI tropes (purple gradients, uniform 3-card grids, unearned glassmorphism, glowing borders)?
  - Would asymmetric layout hierarchy (e.g. 60/40 split) better guide visual attention on flagship views?
- **Integration**: Invoked as a **final structural critic** *after* implementation and visual polish are complete (`UX ➔ Implementation ➔ Impeccable ➔ Hallmark`). Hallmark critiques the result; it never dictates the initial UX.
- **Actionability Policy**: Evaluated context-sensitively (`Required`, `Recommended`, `Contextual`, `Ignore`). Familiar platform conventions on operational views are protected; novelty never overrides cognitive clarity.
- **Reference**: Consult [integrations/hallmark.md](../integrations/hallmark.md). The UX skill does not duplicate Hallmark's internal heuristic checklists.

---

## 4. audit_ux.py: Deterministic Checks

**Owner**: Deterministic AST scanner (`skills/ux/scripts/audit_ux.py` / `src/ship/tools/ux.py`)  
**Focus**: Fast, objective, machine-verifiable accessibility and semantic rules.

- **Primary Checks**:
  - Non-native interactive elements (`<div>`, `<span>`) missing keyboard listeners (UX-001).
  - Suppressed focus outlines (`outline: none`) lacking visible replacement indicators (UX-002).
  - Icon-only buttons lacking accessible names via `aria-label` or `sr-only` text (UX-003).
  - Form controls lacking accessible label associations (UX-014).
  - Dead-end errors lacking actionable recovery paths (UX-005).
  - Unjustified arbitrary dimensional overrides (UX-021).
- **Execution**: Zero external dependencies (Python 3.10+ standard library). Emits exit code 1 on blocking errors (`--fail-on error`). Emits raw terminal receipts for Option C verification.
