# UX & Interface Engineering (`ux`)

> **Prime Directive**: UX is not visual styling. First establish user intent, flow, system states, a11y, error recovery, and interaction behavior; visual implementation comes afterward.

Production UX rules grounded in Norman (*Everyday Things*), Nielsen (Heuristics), Krug (*Don't Make Me Think*), WCAG 2.1/2.2 AA, and Frost (*Atomic Design*).

---

## 1. Operating Modes & Autopilot Execution
- **4 Modes**:
  - `/ux <feature>`: Full gated pipeline (Flow ➔ Spec ➔ Component ➔ Verify).
  - `/ux polish`: Fast-path (Inspect ➔ Context ➔ Audit ➔ Imp ➔ Fix ➔ Hlm ➔ Reconcile ➔ Verify).
  - `/ux audit`: Analysis only; zero file writes (heuristic & a11y checks).
  - `/ux component`: Targeted generation; direct component code synthesis.
- **Modifier (`--autopilot`)**: Bypasses interactive checkpoints for continuous CI/IDE execution.

---

## 2. State Completeness Law
- **Principle**: Every component must define all applicable states for its interaction model.
- **Views & Organisms**: Empty (onboarding CTA), Loading (skeleton/CLS), Populated (ideal), Partial/Stale (pagination/cache), Error/Recovery (actionable CTA), Unavailable/Forbidden (RBAC tooltip).
- **Controls & Atoms**: Default, Hover, Focus-visible, Pressed/Active, Disabled, Busy/Loading.
- **Compound States**: Selected (tabs), Checked/Indeterminate, Expanded/Collapsed (accordions), Invalid, Read-only (when applicable).

---

## 3. Accessibility & Semantics (WCAG 2.1/2.2 AA)
- **Native Elements Over Div Soup**: Always use `<button>`, `<a>`, `<dialog>`, `<form>`, `<nav>`, `<fieldset>` before ARIA role hacks.
- **Visible Focus Protection**: Never use `outline: none` without providing a high-contrast `:focus-visible` ring.
- **Icon Buttons**: Every icon-only button must have `aria-label`, `aria-labelledby`, or visually hidden text (`.sr-only`).
- **Contrast Ratios**: 4.5:1 minimum for body text; 3.0:1 for large text and UI components. Color is never the sole info carrier.
- **Focus Management**: Dialogs must trap keyboard focus and dismiss on `Escape`.

---

## 4. Cognitive Clarity & Usability (Krug / Norman)
- **Visual Hierarchy**: Scan path from Heading ➔ Visual ➔ Body ➔ Primary CTA.
- **Affordances & Signifiers**: Interactive elements must look clickable; non-interactive elements must never look clickable.
- **Zero Dead-End Errors**: Errors must provide actionable recovery CTAs (Retry/Back).
- **Destructive Actions**: Irreversible actions require explicit confirmation or non-blocking undo.
- **Design Tokens & Fidelity**: Detect & reuse existing tokens first. If none: Tailwind scale or CSS vars. Avoid arbitrary values when existing tokens satisfy; permit when justified by design system or visual constraint.

---

## 5. Verification Model (Option C)
- **Evidence-Backed**: Every decision produces rule citation, affected component, severity, fix, and verification method.
- **Executable Receipts**: Run `audit_ux.py --fail-on error`; emit UX FINAL REVIEW receipt (UX, A11y, Imp, Hlm, Decision).

---

## 6. Integrations & Layer Boundaries
- **Layer Model**: UX Core (requirements) ➔ Impeccable (visual craft) ➔ Hallmark (anti-slop critic) ➔ audit_ux.py (deterministic).
- **Critic & Precedence**: UX ➔ Impl ➔ Imp ➔ Hallmark. Hallmark critiques result; never dictates initial UX. P0 A11y ➔ UX ➔ Tokens ➔ Responsive ➔ Visual (Imp) ➔ Anti-Slop (Hlm).
- **Hallmark Context Policy**: Required, Recommended, Contextual, Ignore. Admin card-grid = Ignore; consumer landing = fix.
- **Degradation Law**: Imp missing ➔ UX + audit_ux continue. Hlm missing ➔ UX + Imp continue. Neither ➔ UX standalone. Missing tools NEVER fail UX.
- **Routing & Limits**: New: UX ➔ Imp ➔ Hlm. Polish: Imp ➔ opt Hlm. Admin: UX ➔ Imp. Max 2 passes. Preserve DESIGN.md.
