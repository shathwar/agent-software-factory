# Hallmark Integration Adapter

**Role**: Independent specialist for anti-slop enforcement, structural visual originality, eliminating generic AI design clichés, and introducing editorial craft.

**Orchestration Ownership**: The `ux` skill owns user goal definition, cognitive friction reduction, navigation models, accessibility contracts, and final decision authority. Hallmark acts strictly as an advisory specialist to purge generic AI defaults without eroding usability.

---

## 1. When to Invoke

Invoke Hallmark during **Phase 3 (Component Generation)** when visual originality and brand distinction matter:
- **New Feature Pipeline**: For novel consumer-facing or brand-critical interfaces after UX architecture is settled.
- **Surface Triggers**:
  - Marketing / consumer-facing (`UX ➔ Impeccable ➔ Hallmark`)
  - New features (`UX ➔ Impeccable ➔ Hallmark`)
  - Redesigns / visual overhauls (`Impeccable ➔ optional Hallmark`)
  - Internal CRUD / admin: **Only if visual differentiation matters**; otherwise skip.

---

## 2. Inputs to Provide

Provide Hallmark with product positioning and structural context:
1. **Component Source Code & Rendered Tree**: The generated layout, DOM hierarchy, and styling classes.
2. **Product & Brand Context**: Market domain (e.g. high-density developer tool, editorial publication, consumer SaaS, financial portal) and desired personality.
3. **UX Contract & Mental Model**: The user's primary mental model and expected interaction patterns to ensure originality does not introduce cognitive friction.
4. **Design Tokens & Palette Constraints**: Established brand colors and typography scale to prevent rogue style divergence.

---

## 3. Outputs to Expect

Expect critique and alternatives targeting generic AI stereotypes:
- **AI Trope Detection**: Identifies clichés such as uniform 3-card grids, centered purple gradient hero sections, ubiquitous glowing border buttons, and floating glassmorphism cards without purpose.
- **Structural Layout Variety**: Asymmetric grid suggestions, editorial typographic pacing, varied card proportions, and distinctive section dividers.
- **Palette & Surface Guidance**: Grounded color combinations, high-craft neutral ramps, and intentional contrast rather than "safe" generic purple/indigo AI defaults.
- **Component Personality**: Tailored UI signifiers that match the specific domain rather than looking like an off-the-shelf component library demo.

---

## 4. Actionable Findings

Findings are actionable when they eliminate clichés without harming usability:
- **Template Sameness**: Every container having the exact same aspect ratio, background surface, and drop shadow regardless of content hierarchy.
- **Predictable AI Defaults**: Purple/violet gradients on primary buttons, centered marketing copy with generic badge headers ("✨ The Future of...").
- **Hollow Visual Novelty**: Gimmicky animations or decorative shapes that add no semantic value.
- **Unearned Symmetry**: Forcing content into rigid symmetric columns where an asymmetric hierarchy (e.g. 60/40 split with clear primary focus) would better guide the eye.

---

## 5. Severity Mapping & Critique Normalization

All Hallmark findings must be normalized into the unified UX Critique Contract:

```yaml
finding:
  source: hallmark
  rule_id: HLM-xxx
  severity: P2 | P3
  category: slop | visual
  evidence: "<exact code snippet or pattern identified>"
  recommendation: "<concrete alternative layout or styling pattern>"
  confidence: 0.80
```

### Severity Tiers:
- **`P2` (Medium / Anti-Slop Violation)**: Egregious AI cliché on a flagship or consumer-facing view (e.g. purple gradient card soup, generic template look).
- **`P3` (Low / Distinctiveness Suggestion)**: Opportunity for stronger typographic character, asymmetric layout pacing, or unique border treatment.

> [!IMPORTANT]
> **Hallmark Never Emits `P0` or Overrules `P1`**: Anti-slop suggestions never override accessibility contracts, cognitive clarity, or established design system tokens. Hallmark findings are advisory and subordinate to UX correctness.

---

## 6. When to Skip

Skip Hallmark to conserve token budgets and avoid pointless friction:
- **Accessibility-Only Workflows (`/ux a11y`, `audit_ux.py`)**: Dedicated a11y repairs.
- **Internal CRUD / Admin Dashboards**: Administrative tables, settings pages, and developer dashboards where familiar platform patterns reduce cognitive load and increase task speed.
- **Atomic Controls & System Utilities**: Checkboxes, buttons, dropdowns, modal shells, and form fields where standard platform conventions must be preserved.
- **Existing Design System Compliance**: When the codebase strictly mandates exact design system component reuse (e.g. corporate enterprise library).

---

## 7. Handling Unavailable Tooling

If Hallmark is not installed in the agent host or environment:
1. **Autonomous Graceful Fallback**: The `ux` skill applies its built-in anti-slop guidelines: Krug's cognitive friction test, native platform semantics, avoiding gratuitous decoration, and adhering strictly to project design tokens.
2. **Pipeline Non-Blocking**: The absence of Hallmark MUST NOT fail the build or stop `--autopilot` execution.
3. **Execution Record**: Log `hallmark: skipped (tooling unavailable; applied core UX anti-slop rules)`.
