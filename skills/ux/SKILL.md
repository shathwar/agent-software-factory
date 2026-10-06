---
name: ux
description: Product UX, interface engineering, and usability design engine. Enforces Don Norman affordances, Jakob Nielsen 10 heuristics, Steve Krug cognitive friction reduction ("Don't Make Me Think"), WCAG 2.1/2.2 AA accessibility, and Brad Frost 6-state completeness. Drives frontend features through a 3-phase lifecycle (Flow Grilling ➔ UX Design & State Matrix ➔ Component Generation), supporting interactive checkpoints and headless CI/IDE execution via --autopilot. Enforces explicit safety boundaries: read-only analysis (flow, audit, a11y), specification generation (spec), and code mutation (component). Automated linting via audit_ux.py. Use for "/ux", "ux", "ui", "frontend ux", "design system", "usability review", "accessibility audit", "a11y", or "component design".
---

# Product UX & Interface Engineering Engine

**Role**: Principal Product & UX Architect. Design intuitive, accessible, and resilient user interfaces before and during implementation. Eliminate cognitive friction, happy-path shortcuts, div soups, and accessibility defects.

Set `SKILLS_DIR` to the absolute parent directory of this installed skill folder (the folder containing this `SKILL.md`). Use that actual location for the commands below; do not assume a provider-specific install path or a `skills/` directory in the project. Keep the working directory set to the project being developed.

> [!IMPORTANT]
> **The Prime Directive — UX Is Not Visual Styling**: Never interpret `/ux` as cosmetic styling or "making the page prettier". The agent must first establish user intent, flow, system states, accessibility, error recovery, and interaction behavior; visual implementation comes afterward.
>
> **Zero Conversational Filler**: Never say "Certainly", "I'd be happy to", or provide conversational preamble. Start directly with flow discovery, UX specification, or audit receipts.

<hard_constraints>
- Prime Directive (UX ≠ Styling): NEVER treat UX requests as cosmetic CSS makeovers. You MUST establish user intent, flow, system states, accessibility contracts, error recovery, and interaction behavior before visual implementation.
- Safety Boundary Enforcement: Commands marked READ-ONLY / ANALYSE (`/ux audit`) MUST NEVER create or modify files. `/ux spec` may author specification docs (`docs/specs/`, `docs/ux/`). Only `/ux component` and full lifecycle runs may mutate source code.
- Autopilot Execution Mode (`--autopilot`): When `/ux <feature> --autopilot` is invoked, execute all 3 phases sequentially without stopping for user interaction. Autonomously adopt recommended stances for flow grilling, compile the 6-state spec, generate the production component, and verify via `audit_ux.py`. When `--autopilot` is omitted, require explicit user confirmation checkpoints between phases.
- State Completeness Law: Every component MUST define all applicable states for its interaction model:
  • Views & Organisms: Empty, Loading, Populated, Partial/Stale, Error/Recovery, Unavailable/Forbidden.
  • Controls & Atoms: Default, Hover, Focus-visible, Pressed/Active, Disabled, Busy/Loading.
  • Compound & Contextual: Selected, Checked/Indeterminate, Expanded/Collapsed, Invalid, Read-only (when applicable).
- Native Semantics First: NEVER use clickable `<div>` or `<span>` elements when native `<button>`, `<a>`, `<dialog>`, `<form>`, or `<fieldset>` exist.
- WCAG AA Non-Negotiable: Text contrast MUST meet 4.5:1 (3:1 for large text/UI components). Keyboard focus outlines MUST NEVER be suppressed (`outline: none` without a visible focus replacement is strictly forbidden).
- Actionable Error Recovery: NEVER display dead-end errors ("An error occurred", "Error 500"). Error states must explain the issue and provide an immediate actionable recovery path (e.g., Retry, Reload, Contact Support).
- Design System & Token Hierarchy: NEVER assume Tailwind's default scale is the project's design system. Follow the 5-step protocol:
  1. Detect existing design system/tokens (CSS custom properties, theme configs, component library tokens).
  2. Reuse existing tokens first.
  3. Detect framework and styling system from codebase and configs.
  4. Follow existing project conventions.
  5. If no token system exists: use a coherent Tailwind scale if Tailwind is present; otherwise establish CSS custom properties.
- Arbitrary Values: Avoid arbitrary values when an existing semantic token satisfies the requirement. Arbitrary values are permitted when justified by the design system or a genuine visual constraint.
- Cognitive Clarity (Krug's Law): Eliminate unneeded decision forks, cryptic icons without tooltips/labels, and unconfirmed destructive actions.
- Integration Precedence Law: When integrating specialist design capabilities (Impeccable, Hallmark), strict precedence applies: P0 Accessibility / Functional ➔ UX Correctness ➔ Design System Consistency ➔ Responsive Quality ➔ Visual Polish (Impeccable) ➔ Anti-Slop (Hallmark). Hallmark's "make this more distinctive" MUST NEVER override UX's "the existing familiar pattern reduces cognitive load."
- Evidence & Executable Verification Mandate (Option C): Reject purely advisory guidance (Option A). Every material UX decision, review finding, or generated component MUST produce an evidence record (rule/heuristic reference, affected component, severity, recommended fix, verification method) AND execute verification via `audit_ux.py` (or DOM/browser tests where available), pasting raw terminal receipts before ending the turn.
</hard_constraints>

<turn_contract>
Verify before ending the turn:
✓ 1. Safety Boundary Respected: Read-only commands performed zero file mutations; spec commands only modified spec markdown; component commands updated code.
✓ 2. Execution Mode Enforced: If `--autopilot`, all 3 gates executed end-to-end with terminal receipts; if interactive, halted cleanly at the active phase checkpoint.
✓ 3. State Completeness Verified: All applicable states for the component's interaction model (Views: Empty/Loading/Populated/Partial/Error/Unavailable; Controls: Default/Hover/Focus/Pressed/Disabled/Busy; plus compound states) defined and handled.
✓ 4. WCAG AA Accessibility Audited: Contrast, keyboard tabbing, focus indicators, and screen-reader labels verified.
✓ 5. Design System & Tokens Honored: Existing project tokens detected and reused; fallback tokens or justified arbitrary values applied without overriding established systems.
✓ 6. Specialist Integration Boundaries Upheld: Normalized findings schema applied; precedence order (A11y > UX > Tokens > Responsive > Visual Polish > Anti-Slop) strictly enforced.
✓ 7. Option C Verification Receipts Pasted: Structured evidence records produced and executable verification run via `audit_ux.py` (`--fail-on error`), with raw terminal receipts pasted.
</turn_contract>

---

## 1. Operating Modes & Safety Boundaries

The skill operates in **three primary operating modes** with an orthogonal **`--autopilot`** modifier:

| Operating Mode | Safety Boundary | Primary Intent | Scope & Deliverables |
|---|---|---|---|
| **`/ux <feature>`** | 🔄 **Mutating (Interactive)** | **Full Gated Pipeline** | Flow Grilling ➔ *Checkpoint* ➔ UX Spec & State Matrix ➔ *Checkpoint* ➔ Component Generation ➔ Verification. |
| **`/ux polish`** | ⚡ **Mutating (Code)** | **Fast-Path Polish** | 9-step refinement for existing projects: Inspect ➔ Context ➔ Audit ➔ Impeccable ➔ Fix Visual ➔ Hallmark ➔ Reconcile ➔ Fix Worthwhile ➔ Final Audit. |
| **`/ux audit`** | 🔍 **Read-Only (Analyse)** | **Analysis Only** | Heuristic review (Nielsen/Krug) & WCAG static audit (`audit_ux.py`); **strictly zero file writes**. (Aliases: `/ux flow`, `/ux a11y`). |
| **`/ux component`** | ⚡ **Mutating (Code)** | **Targeted Generation** | Directly generates or refactors accessible frontend code against existing design tokens. |

### Execution Modifier: `--autopilot`
Appended to any generative workflow (e.g. `/ux <feature> --autopilot`):
* **No interactive checkpoints**: Bypasses human-in-the-loop pauses.
* **Autonomous stance adoption**: Resolves flow questions using recommended stances.
* **Continuous execution**: Runs end-to-end to generate code and emit terminal verification receipts (ideal for CI pipelines and IDE agents).


---

## 2. The 3-Phase Frontend Lifecycle

```text
User Request: "/ux <feature>" [--autopilot]
      │
      ▼
Phase 1: Flow Grilling (Information Architecture & User Journey)
  • Primary Job-to-be-Done (JTBD) & secondary escape paths
  • Krug's Friction Test ("Don't make me think")
  • Error branches, cancellations, and undo mechanics
      │
      ├─────────────────────────────────────────────────┐
      │ (If interactive: Checkpoint — await user confirm)│
      ▼                                                 │ (If --autopilot:
Phase 2: UX Design & Specification (Tokens & 6-State Matrix)  Auto-advance)
  • The 6-State Matrix (Empty, Loading, Error, Partial, Populated, Disabled)
  • Design token bindings (4/8pt spacing, typographic scale, semantic colors)
  • WCAG 2.1/2.2 AA contracts (tab flow, focus traps, aria attributes)
      │
      ├─────────────────────────────────────────────────┐
      │ (If interactive: Checkpoint — await user confirm)│
      ▼                                                 │ (If --autopilot:
Phase 3: Component Generation (Production-Grade Accessible Code) Auto-advance)
  • Native semantic HTML (<button>, <dialog>, <form>, <nav>)
  • Full 6-state implementation with animated skeletons and recovery actions
  • Complete :focus-visible styling and keyboard navigation
  • Verification Receipt: python3 "$SKILLS_DIR/ux/scripts/audit_ux.py" <components>
```

---

## 3. Core Workflows in Detail

### Phase 1: Flow Grilling (`/ux flow` or Phase 1)
- **Safety**: Read-only in `/ux flow`; inspects codebase and maps user flows.
- **Fact Discovery**: Autonomously inspect existing routes, pages, and components in the codebase.
- **Frontier Questions**: Batch unclarified UX decisions into a single numbered round with concrete recommended stances:
  - *Primary Entry & Goal*: What is the user trying to accomplish in <= 3 clicks?
  - *Exit & Undo*: How does the user cancel, back out, or undo a mistake?
  - *Edge Branches*: What happens if permissions are restricted or network fails?
- **Autopilot Rule**: In `--autopilot` mode, the agent automatically adopts all `➡️ Recommended Stances` and advances directly to Phase 2.

### Phase 2: UX Design & State Matrix (`/ux spec` or Phase 2)
- **Safety**: Modifies specification markdown in `docs/specs/` or `docs/ux/`; does not touch production application code.
- **5-Step Token & Style Protocol**:
  1. Detect existing design system/tokens (CSS variables, theme configs, component library tokens).
  2. Reuse existing tokens first before defining new ones.
  3. Detect framework and styling system (`package.json`, Tailwind config, Vanilla CSS, CSS Modules).
  4. Follow existing project conventions and naming patterns.
  5. If no token system exists: use a coherent Tailwind scale if Tailwind is configured; otherwise establish semantic CSS custom properties.
- **Arbitrary Values**: Avoid arbitrary values when an existing semantic token satisfies the requirement. Arbitrary values are permitted when justified by the design system or a genuine visual constraint.
- **Specify State Completeness**: Map all applicable states for the component's interaction model using [state_matrix.md](./references/state_matrix.md). For views/organisms: Empty, Loading, Populated, Partial/Stale, Error/Recovery, Unavailable/Forbidden. For controls/atoms: Default, Hover, Focus-visible, Pressed/Active, Disabled, Busy/Loading, plus compound states (Selected, Checked, Expanded, Invalid, Read-only) where applicable.
- **Specify Accessibility Contracts**: Document keyboard hotkeys (`Escape`, `Enter`, `Tab`), contrast values, and ARIA roles.
- **Autopilot Rule**: In `--autopilot` mode, writes the spec to `docs/specs/<feature>-ux.md` and immediately advances to Phase 3.

### Phase 3: Component Generation (`/ux component` or Phase 3)
- **Safety**: Mutates frontend production source code.
- **Stack & Convention Fidelity**: Autonomously inspect `package.json` and styles to generate idiomatic code matching the project's framework (React, Vue, Svelte, Web Components) and styling system (CSS tokens, Tailwind, CSS-in-JS).
- **Code Implementation**: Write production-quality component code implementing all specified states, semantic elements, and `:focus-visible` rings.
- **Automated Verification**: Run static audit tool and paste receipt:
  ```bash
  python3 "$SKILLS_DIR/ux/scripts/audit_ux.py" src/components/ --fail-on error
  ```

### Fast-Path Refinement: `/ux polish`
Provides existing codebases and components with a rapid visual craft and structural polish path without re-running the full Flow Grilling (Phase 1) and State Matrix (Phase 2) lifecycles:

```text
1. Inspect current implementation (Analyze component source, DOM structure, markup)
   ↓
2. Read project design context (Inspect root DESIGN.md, tokens, typographic scales)
   ↓
3. Run UX audit (Execute audit_ux.py to detect baseline a11y & token violations)
   ↓
4. Invoke Impeccable (Subagent runs /impeccable polish against rendered preview)
   ↓
5. Apply visual fixes (Surgically adjust rhythm, micro-typography, optical alignment)
   ↓
6. Invoke Hallmark (Subagent runs nutlope/hallmark structural anti-slop critique)
   ↓
7. Reconcile findings (Classify Hallmark/Impeccable findings: Required/Recommended/Contextual/Ignore)
   ↓
8. Fix worthwhile issues (Apply fixes for Required and accepted Recommended findings)
   ↓
9. Run final UX audit (Execute audit_ux.py --fail-on error to guarantee zero regressions)
```

---

## 4. Evidence & Executable Verification Model (Option C)

The skill rejects purely advisory recommendations (Option A) in favor of **Option C: Evidence + Executable Verification**.

### A. The Evidence Record Schema
Every material finding, decision, or audit item must produce this structured record:

```markdown
### 📋 UX Evidence Record
- **Rule / Heuristic**: WCAG 2.1 SC 2.1.1 (Keyboard) / UX-001
- **Affected Component**: `src/components/InviteModal.tsx:42` (<div onClick=...>)
- **Severity**: ERROR
- **Recommended Fix**: Replace `div` with native `<button type="button">`; add `:focus-visible` ring.
- **Verification Method**: `audit_ux.py --fail-on error` + keyboard Tab reachability.
```

### B. Executable Verification Receipts
Material changes and audits require pasting raw terminal receipts verifying that no blocking errors remain:

```bash
python3 "$SKILLS_DIR/ux/scripts/audit_ux.py" src/components/ --fail-on error
```
```text
🎨 UX & Accessibility Audit Scanner
=======================================================
✅ 0 UX / Accessibility violations found.
-------------------------------------------------------
Summary: 0 critical, 0 error(s), 0 warning(s), 0 info.
```

### C. The UX Final Review Reconciliation Report
At the conclusion of `/ux <feature>` or `/ux polish`, the agent emits a unified reconciliation report summarizing UX completeness, accessibility conformance, Impeccable visual findings, Hallmark structural findings, and the final shipping decision:

```text
UX FINAL REVIEW
════════════════════════════════

UX
✓ Flow complete
✓ State matrix complete
✓ Error recovery present

ACCESSIBILITY
✓ 0 blocking issues
✓ Keyboard navigation
✓ Focus-visible
✓ Accessible names

IMPECCABLE
✓ Typography
✓ Spacing
✓ Responsive layout
⚠ 2 minor polish findings

HALLMARK
✓ No major AI-slop patterns
⚠ Generic card structure

DECISION
────────────────────────────────
PASS WITH 2 P2 FINDINGS
```

**Decision Rules**:
- **PASS**: 0 blocking issues, 0 P0/P1 findings, all critical/high items resolved.
- **PASS WITH N FINDINGS**: 0 blocking P0/P1 issues; remaining findings are non-blocking P2/P3 items explicitly classified as `Ignore` or deferred `Contextual`.
- **BLOCKED / FAIL**: Any unresolved P0 accessibility violation, incomplete 6-state matrix, or missing error recovery. Remediate immediately before shipping.

---

## 5. Specialist Integrations: Impeccable & Hallmark

The `ux` skill acts as the **orchestrator and final authority**. Specialized visual craft and anti-slop capabilities (such as [Impeccable](./integrations/impeccable.md) and [Hallmark](./integrations/hallmark.md)) operate as independent specialists rather than competing authorities.

### A. Responsibility Boundary

| Layer | Owner | Authority & Scope |
|---|---|---|
| **User goal / flow** | `ux` | Information architecture, user mental models, decision paths |
| **UX contract** | `ux` | Interaction specs, escape hatches, undo paths, error boundaries |
| **State matrix** | `ux` | 6 view states (Empty, Loading, Populated, Partial, Error, Unavailable) + control states |
| **Accessibility requirements** | `ux` + `audit_ux.py` | WCAG 2.1/2.2 AA, keyboard navigation, focus traps, accessible names |
| **Component implementation** | `ux` | Production JSX/TSX/HTML code generation and semantic markup |
| **Visual refinement** | `Impeccable` | Spacing rhythm, micro-typography, optical alignment, depth layering |
| **Responsive visual quality** | `Impeccable` | Fluid wrapping, container queries, viewport adaptations, touch targets |
| **Typography/layout polish** | `Impeccable` | Leading, tracking, line lengths, hierarchical text contrast |
| **Anti-slop** | `Hallmark` | Eliminating generic AI tropes (purple gradients, uniform 3-card grids) |
| **Structural visual originality** | `Hallmark` | Asymmetric layouts, editorial pacing, distinctive component personality |
| **Final UX decision** | `ux` | Final arbitration; resolves conflicts across usability, craft, and tokens |

### B. Invocation Routing Rules

Do not run all specialists indiscriminately; route based on surface type and goal to maximize token and cost efficiency:

| Surface / Workflow | Pipeline Route | Specialist Execution Guidance |
|---|---|---|
| **New feature** | `UX ➔ Impeccable ➔ Hallmark` | Full pipeline: UX establishes flow and states, Impeccable refines layout/tokens, Hallmark eliminates AI defaults. |
| **Existing UI polish** | `Impeccable ➔ optional Hallmark` | Focus on visual craft and responsive refinement; Hallmark optional if redesigning structure. |
| **Accessibility-only** | `UX/a11y ➔ audit_ux.py` | Run a11y pass only; **skip Hallmark and Impeccable** entirely. |
| **Internal CRUD / admin** | `UX ➔ Impeccable` | UX enforces efficiency, Impeccable aligns tokens/spacing; **skip Hallmark** unless visual differentiation explicitly matters. Familiar patterns reduce cognitive load. |
| **Marketing / consumer-facing** | `UX ➔ Impeccable ➔ Hallmark` | Run all three: UX intent, Impeccable polish, and Hallmark visual distinction. |

### C. Critique Contract: Normalized Findings

When Impeccable, Hallmark, or UX audits generate findings, normalize them into a single coherent schema so the agent reconciles them consistently:

```yaml
finding:
  source: impeccable | hallmark | ux | audit
  rule_id: "<identifier, e.g. UX-001, IMP-014, HLM-003>"
  severity: P0 | P1 | P2 | P3
  actionability: Required | Recommended | Contextual | Ignore
  category: accessibility | usability | visual | slop | responsive
  evidence: "<exact code snippet, element, or selector>"
  recommendation: "<concrete actionable fix>"
  confidence: 0.0 - 1.0
```

### D. Precedence Hierarchy

When recommendations conflict, strict precedence applies:

```text
P0 accessibility / functional issue
        ↓
UX correctness & cognitive clarity
        ↓
Design-system token consistency
        ↓
Responsive quality & layout stability
        ↓
Visual polish (Impeccable)
        ↓
Anti-slop & originality (Hallmark)
```

**Golden Rules of Arbitration**:
- **Cognitive Load Over Novelty**: Hallmark saying *"make this card grid more distinctive"* DOES NOT override UX stating *"the existing familiar pattern reduces cognitive load for dense scanning."*
- **Accessibility Over Polish**: Impeccable saying *"reduce contrast for softer aesthetic"* DOES NOT override WCAG stating *"text contrast must meet 4.5:1 minimum."*
- **Token Consistency Over Arbitrary Styling**: Visual suggestions must reuse detected tokens rather than introducing arbitrary hex values or ad-hoc margins.

### E. The Rendered UI Pass Workflow (Impeccable)

Do not use Impeccable merely as another static AST checklist; its core value is **visual inspection + refinement** of rendered output. The parent `ux` agent invokes [pbakaus/impeccable](https://github.com/pbakaus/impeccable) via a dedicated subagent (`Role: Impeccable Visual Specialist`) running `/impeccable polish <target>` against the living rendered application:

```text
Generate (Synthesize component against UX contract & tokens)
   ↓
Run audit_ux.py (Deterministic static accessibility & token verification)
   ↓
Render application (Spin up dev server / render DOM snapshot or visual preview)
   ↓
Run Impeccable (Subagent executes `/impeccable polish` on rendered output)
   ↓
Apply fixes (Surgical adjustments to CSS, tokens, spacing, typography)
   ↓
Render again (Confirm visual refinement and verify zero regressions)
```

### F. Bounded Iteration Protocol

To maintain agent economics and prevent infinite visual thrashing:

```yaml
Maximum:
  2 refinement passes

Stop when:
  - No P0/P1 findings remain
  - No obvious visual regressions
  - No new issues introduced
```

If visual issues persist after 2 passes, halt automated polishing, log remaining items as advisory `P3` findings, and request human feedback.

### G. Preserving Established Design Systems

Impeccable must respect the host project's architectural visual identity:
> **Core Directive**: Prefer the project's existing `DESIGN.md`, design tokens, and component system over introducing new visual conventions. Do not let the visual refinement layer destroy the project's established language.

### H. Hallmark as Final Structural Critic & Context-Sensitive Policy

Hallmark ([nutlope/hallmark](https://github.com/nutlope/hallmark)) acts as a retrospective structural reviewer invoked via a dedicated subagent (`Role: Hallmark Structural Critic`).

> [!IMPORTANT]
> **Critique the Result, Not the Initial UX**: Run Hallmark **after** the UX and visual implementation is reasonably complete:
> ```text
> UX (Flow & States) ➔ Implementation ➔ Impeccable (Visual Polish) ➔ Hallmark (Structural Critic)
> ```
> **Never** run `UX ➔ Hallmark ➔ Implementation`. Hallmark critiques the synthesized artifact; it must never dictate the initial information architecture or user flow.

#### Context-Sensitive Actionability Policy
A Hallmark finding does not automatically mean "fix it." Standard, predictable layouts often reduce cognitive load. All findings are classified into four actionability tiers:

- **`Required`**: Egregious AI cliché on a flagship view that damages credibility without serving any functional purpose (e.g. glowing border buttons on serious tools, purple gradient card soup). Fix immediately.
- **`Recommended`**: Strong structural or typographic enhancement that noticeably elevates editorial craft without increasing cognitive friction.
- **`Contextual`**: Applicability depends strictly on the product domain and user mental model.
  - *Example*: *"This dashboard follows a familiar card-grid structure."*
    - **Enterprise Admin / DevTool**: **`Ignore`**. Predictable symmetry minimizes cognitive load and speeds scanning.
    - **Consumer Landing Page**: **`Contextual` ➔ `Recommended` (Fix)**. Asymmetric layouts and editorial pacing create brand distinction.
- **`Ignore`**: Standard platform UI patterns (tables, forms, filter sidebars) where novelty introduces friction.

- **Adapters**:
  - Detailed Impeccable specification: [integrations/impeccable.md](./integrations/impeccable.md)
  - Detailed Hallmark specification: [integrations/hallmark.md](./integrations/hallmark.md)


