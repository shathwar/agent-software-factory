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

## 2. Inputs to Provide

Provide Impeccable with complete structural context to prevent blind styling:
1. **Component Source Code**: Full TSX, JSX, HTML, or Vue/Svelte template.
2. **Design Tokens & Theme**: Detected CSS custom properties, Tailwind theme configuration, or component library tokens.
3. **UX Contract & State Matrix**: The 6 view states (Empty, Loading, Populated, Partial, Error, Unavailable) and control states (Hover, Focus-visible, Active, Disabled, Busy) to ensure all states are visually styled.
4. **Responsive Constraints**: Target breakpoints (mobile, tablet, desktop) and container query boundaries.
5. **Information Hierarchy**: Primary user goal, scanning anchors, and intended visual hierarchy.

---

## 3. Outputs to Expect

Expect structured visual refinement recommendations:
- **Micro-Typography**: `line-height` (leading), `letter-spacing` (tracking), font weight balance, and measure (45–75 character line lengths).
- **Spacing Rhythm & Optical Alignment**: Consistent 4/8pt spacing scale adherence, optical vertical centering of icons with text, balanced button padding.
- **Responsive Visual Quality**: Fluid scaling, flex/grid wrapping behavior, container query adaptations, touch target sizing (>= 44x44px).
- **Surface & Depth Hierarchy**: Subtle elevation, border contrast, background surface layering, and visual containment.
- **Micro-Interactions**: Transition timing curves (150–250ms), hover elevation deltas, and active press states.

---

## 4. Actionable Findings

Findings are actionable if they improve visual craft without breaking functional UX:
- **Spacing Inconsistencies**: Mixing ad-hoc padding values (`p-3`, `p-4`, `p-5`) where a strict rhythmic scale should apply.
- **Optical Misalignments**: Icon and text baseline mismatches, uneven horizontal/vertical padding on pill badges or buttons.
- **Unreadable Typography**: Overly wide text containers (>80ch), low heading-to-body contrast ratios, or missing leading on multi-line headers.
- **Responsive Clumping & Overflow**: Awkward line breaks, clipped containers, or overflowing tables on small viewports.
- **Muddy Visual Hierarchy**: Primary actions lacking visual dominance over secondary or tertiary actions.

---

## 5. Severity Mapping & Critique Normalization

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

## 6. When to Skip

Skip Impeccable to preserve token budget and speed when:
- **Read-Only Flow Analysis (`/ux flow`)**: Information architecture and user journey phases prior to visual design.
- **Accessibility-Only Audits (`/ux a11y`, `audit_ux.py`)**: Dedicated WCAG compliance passes where visual restyling is out of scope.
- **Headless / Non-Visual Code**: Data hooks, state stores, form validation logic, or API wrappers.
- **Performance Diffs**: Refactors that preserve pixel-identical output.

---

## 7. Handling Unavailable Tooling

If Impeccable is not installed in the agent host or environment:
1. **Autonomous Graceful Fallback**: The `ux` skill applies its built-in visual guidelines ([`heuristics_rubric.md`](../references/heuristics_rubric.md) Heuristic 8: Aesthetic and Minimalist Design) and the 5-step design token hierarchy.
2. **Pipeline Non-Blocking**: The absence of Impeccable MUST NOT fail the build or stop `--autopilot` execution.
3. **Execution Record**: Log `impeccable: skipped (tooling unavailable; applied core UX visual standards)`.
