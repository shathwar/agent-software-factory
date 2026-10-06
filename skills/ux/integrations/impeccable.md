# Impeccable Integration Adapter

**Role**: Independent specialist for visual refinement, responsive visual quality, micro-typography, layout polish, and design system visual coherence.

**Orchestration Ownership**: The `ux` skill owns the end-to-end pipeline, user flow, interaction state matrix, accessibility baseline, and final arbitration. Impeccable acts strictly as a specialist advisor for visual craft and responsive refinement.

---

## 1. When to Invoke

Invoke Impeccable during **Phase 3 (Component Generation)** or during targeted UI polish tasks:
- **New Feature Pipeline**: After Phase 2 produces the UX contract and state matrix, and initial component code is generated.
- **Existing UI Polish (`/ux component`)**: When refactoring or polishing existing views, templates, or component libraries.
- **Surface Triggers**:
  - New features (`UX ➔ Impeccable ➔ Hallmark`)
  - Existing UI polish (`Impeccable ➔ optional Hallmark`)
  - Internal CRUD / admin (`UX ➔ Impeccable`)
  - Marketing / consumer-facing (`UX ➔ Impeccable ➔ Hallmark`)

---

## 2. The Rendered UI Pass Workflow

> [!IMPORTANT]
> **Inspect the Rendered UI, Not Merely Static Code**: Do not use Impeccable merely as another static AST checklist. Its strongest value is **visual inspection + refinement** of the rendered artifact (preview server, DOM layout snapshot, browser preview, or visual render).

The integrated lifecycle workflow is:

```text
Generate (Component code synthesized against UX contract & tokens)
   ↓
Run audit_ux.py (Deterministic static accessibility & token verification)
   ↓
Render application (Spin up dev server / render DOM snapshot or visual preview)
   ↓
Run Impeccable (Inspect rendered optical alignment, rhythm, responsive layout)
   ↓
Apply fixes (Surgical adjustments to CSS, tokens, spacing, typography)
   ↓
Render again (Confirm visual refinement and verify zero regressions)
```

Static ASTs cannot detect optical imbalances, subtle text clipping, awkward wrapping on specific viewport widths, or unbalanced whitespace between icon-label pairs. The rendered pass verifies the living UI.

---

## 3. Preserving Established Design Systems

Impeccable must respect the host project's architectural visual identity:

> **Core Directive**: Prefer the project's existing `DESIGN.md`, design tokens, and component system over introducing new visual conventions. Do not let the visual refinement layer destroy the project's established language.

- **`DESIGN.md` & Token Precedence**: If the project maintains a `DESIGN.md`, custom theme configuration, or component library tokens, Impeccable must compose using those existing primitives.
- **No Rogue Aesthetic Injections**: Never introduce uncoordinated font families, foreign color palettes, or arbitrary border radii that clash with the repository's design system.
- **Extension Over Replacement**: If a visual constraint requires an unrepresented value, extend the existing token scale coherently rather than hardcoding disconnected styles.

---

## 4. Inputs to Provide

Provide Impeccable with complete structural context to prevent blind styling:
1. **Component Source Code**: Full TSX, JSX, HTML, or Vue/Svelte template.
2. **Design System & Tokens**: Project `DESIGN.md`, detected CSS custom properties, Tailwind theme configuration, or component library tokens.
3. **UX Contract & State Matrix**: The 6 view states (Empty, Loading, Populated, Partial, Error, Unavailable) and control states (Hover, Focus-visible, Active, Disabled, Busy) to ensure all states are visually styled.
4. **Responsive Constraints**: Target breakpoints (mobile, tablet, desktop) and container query boundaries.
5. **Rendered State / Preview**: URL, port, or local rendering command for the live application.

---

## 5. Outputs to Expect

Expect structured visual refinement recommendations:
- **Micro-Typography**: `line-height` (leading), `letter-spacing` (tracking), font weight balance, and measure (45–75 character line lengths).
- **Spacing Rhythm & Optical Alignment**: Consistent 4/8pt spacing scale adherence, optical vertical centering of icons with text, balanced button padding.
- **Responsive Visual Quality**: Fluid scaling, flex/grid wrapping behavior, container query adaptations, touch target sizing (>= 44x44px).
- **Surface & Depth Hierarchy**: Subtle elevation, border contrast, background surface layering, and visual containment.
- **Micro-Interactions**: Transition timing curves (150–250ms), hover elevation deltas, and active press states.

---

## 6. Actionable Findings

Findings are actionable if they improve visual craft without breaking functional UX:
- **Spacing Inconsistencies**: Mixing ad-hoc padding values (`p-3`, `p-4`, `p-5`) where a strict rhythmic scale should apply.
- **Optical Misalignments**: Icon and text baseline mismatches, uneven horizontal/vertical padding on pill badges or buttons.
- **Unreadable Typography**: Overly wide text containers (>80ch), low heading-to-body contrast ratios, or missing leading on multi-line headers.
- **Responsive Clumping & Overflow**: Awkward line breaks, clipped containers, or overflowing tables on small viewports.
- **Muddy Visual Hierarchy**: Primary actions lacking visual dominance over secondary or tertiary actions.

---

## 7. Bounded Iteration Protocol

To maintain agent economics and prevent infinite visual thrashing:

```yaml
Maximum:
  2 refinement passes

Stop when:
  - No P0/P1 findings remain
  - No obvious visual regressions
  - No new issues introduced
```

1. **Pass 1 (Primary Refinement)**: Ingest rendered preview ➔ identify spacing, typographic, and responsive flaws ➔ apply fixes.
2. **Pass 2 (Verification & Convergence)**: Re-render ➔ verify fixes resolved the issues without introducing regressions.
3. **Circuit Breaker**: If visual issues persist after Pass 2, halt automated polishing, record remaining items as advisory `P3` findings, and request human feedback.

---

## 8. Severity Mapping & Critique Normalization

All Impeccable findings must be normalized into the unified UX Critique Contract:

```yaml
finding:
  source: impeccable
  rule_id: IMP-xxx
  severity: P1 | P2 | P3
  category: visual | responsive
  evidence: "<exact code snippet or computed style>"
  recommendation: "<concrete CSS / token fix>"
  confidence: 0.85
```

### Severity Tiers:
- **`P1` (High)**: Severe layout breakdown, unreadable typography, overlapping elements, or broken mobile viewport rendering.
- **`P2` (Medium)**: Spacing scale violation, optical misalignment, poor visual hierarchy between primary and secondary actions.
- **`P3` (Low / Polish)**: Micro-interaction timing curve suggestion, subtle border-color adjustment, or minor elevation tweak.

*(Note: Impeccable never emits `P0`. `P0` is reserved strictly for accessibility blockers or functional failures).*

---

## 9. When to Skip

Skip Impeccable to preserve token budget and speed when:
- **Read-Only Flow Analysis (`/ux flow`)**: Information architecture and user journey phases prior to visual design.
- **Accessibility-Only Audits (`/ux a11y`, `audit_ux.py`)**: Dedicated WCAG compliance passes where visual restyling is out of scope.
- **Headless / Non-Visual Code**: Data hooks, state stores, form validation logic, or API wrappers.
- **Performance Diffs**: Refactors that preserve pixel-identical output.

---

## 10. Handling Unavailable Tooling

If Impeccable is not installed in the agent host or environment:
1. **Autonomous Graceful Fallback**: The `ux` skill applies its built-in visual guidelines ([`heuristics_rubric.md`](../references/heuristics_rubric.md) Heuristic 8: Aesthetic and Minimalist Design) and the 5-step design token hierarchy.
2. **Pipeline Non-Blocking**: The absence of Impeccable MUST NOT fail the build or stop `--autopilot` execution.
3. **Execution Record**: Log `impeccable: skipped (tooling unavailable; applied core UX visual standards)`.
