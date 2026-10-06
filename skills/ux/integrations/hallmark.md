# Hallmark Integration Adapter

**Upstream Skill**: [nutlope/hallmark](https://github.com/nutlope/hallmark) — AI frontend design critic, anti-slop engine, and structural visual originality analyzer.

**Role**: Independent specialist for anti-slop enforcement, structural visual originality, eliminating generic AI design clichés, and introducing editorial craft.

**Orchestration Ownership**: The `ux` skill owns user goal definition, cognitive friction reduction, navigation models, accessibility contracts, and final decision authority. Hallmark acts strictly as an advisory specialist to purge generic AI defaults without eroding usability.

---

## 1. When to Invoke: Final Structural Critic

> [!IMPORTANT]
> **Hallmark Critiques the Result, Not the Initial UX**: Run Hallmark **after** the UX and visual implementation is reasonably complete. Hallmark must critique the concrete synthesized result, never dictate the initial information architecture or user flow.
>
> Correct Pipeline Sequence:
> ```text
> UX (Flow & State Matrix)
>  ↓
> Implementation (Accessible Production Code)
>  ↓
> Impeccable (Optical Balance, Rhythm & Micro-Typography)
>  ↓
> Hallmark (Final Structural Anti-Slop Critique)
> ```
>
> **Anti-Pattern to Avoid**: Never run `UX ➔ Hallmark ➔ Implementation`. Hallmark is a retrospective structural reviewer; letting it drive initial specification produces visually idiosyncratic interfaces that violate platform mental models and increase cognitive load.

### Surface Triggers:
- **New Feature Pipeline**: For novel consumer-facing or brand-critical interfaces after UX and visual polish are complete (`UX ➔ Implementation ➔ Impeccable ➔ Hallmark`).
- **Fast-Path Polish (`/ux polish`)**: Step 6 of the polish lifecycle (`Inspect ➔ Context ➔ Audit ➔ Impeccable ➔ Fix Visual ➔ Hallmark ➔ Reconcile ➔ Fix Worthwhile ➔ Final Audit`).
- **Marketing / Consumer-Facing**: High-priority check for distinctive visual character and editorial layout.
- **Internal CRUD / Admin**: **Skip Hallmark by default**; familiar platform patterns reduce cognitive load and accelerate task completion. Only invoke if visual differentiation explicitly matters.

---

## 2. Subagent Invocation Specification

When the parent `ux` agent initiates the final structural critique, it invokes Hallmark as a delegated specialist subagent:

### A. Subagent Invocation Schema
Using the agent's subagent execution tool (`invoke_subagent`):

```json
{
  "Role": "Hallmark Structural Critic",
  "TypeName": "self",
  "Prompt": "Execute Hallmark structural critique (nutlope/hallmark) on the rendered UI for `<component_path>`. Ground yourself in the product domain (<domain>) and root `DESIGN.md`. Inspect the implementation for generic AI-slop clichés, unearned symmetry, template sameness, and purple-gradient tropes. Classify all findings using the Context-Sensitive Actionability tiers (Required, Recommended, Contextual, Ignore). Reconcile against cognitive clarity precedence. Normalize findings into the UX Critique Contract schema."
}
```

---

## 3. Context-Sensitive Hallmark Policy

> [!IMPORTANT]
> **A Hallmark Finding Does Not Automatically Mean "Fix It"**: Anti-slop and distinctiveness critiques must be evaluated in context. Standard, predictable layout patterns often represent optimal usability.

Every Hallmark finding must be classified into one of four actionability tiers:

| Tier | Policy & Criteria | Typical Application |
|---|---|---|
| **`Required`** | Critical structural flaw or egregious AI slop cliché on a flagship view that damages credibility without serving any functional or cognitive purpose. | Purple gradient hero soup, meaningless floating glassmorphism cards, glowing border buttons on serious products. |
| **`Recommended`** | Meaningful structural or typographic enhancement that noticeably elevates design craft without compromising user flow, mental models, or established tokens. | Asymmetric layout splits (60/40), editorial typographic contrast, distinct section divider treatment. |
| **`Contextual`** | Applicability depends strictly on the application domain, target audience, and user mental model. | Card-grid structure, standard multi-column layouts, conventional toolbars. |
| **`Ignore`** | Standard platform UI patterns where novelty introduces unnecessary friction or violates user expectations. | Admin tables, settings forms, high-density data grids, filter sidebars. |

### Concrete Decision Example: The Card-Grid Pattern

> Finding: *"This dashboard follows a familiar card-grid structure."*
>
> - **Enterprise Admin / High-Density DevTool**: **`Ignore`**.
>   *Rationale*: Predictable, symmetrical card grids minimize cognitive load, accelerate rapid visual scanning, and conform to the operator's established mental model. Novel layout variation here increases friction.
> - **Consumer Landing Page / Marketing Showcase**: **`Contextual` ➔ `Recommended` (Fix)**.
>   *Rationale*: A consumer landing page requires visual distinction, brand memorability, and editorial pacing. Breaking out of generic 3-card uniformity into an asymmetric showcase creates genuine product personality.

---

## 4. Inputs to Provide to the Subagent

Provide Hallmark with product positioning and structural context:
1. **Component Source Code & Rendered Tree**: The generated layout, DOM hierarchy, and styling classes.
2. **Product Domain & Target Audience**: Market category (e.g. enterprise B2B admin, high-density developer tool, consumer SaaS, editorial publication).
3. **UX Contract & Mental Model**: The user's primary mental model and expected interaction patterns to ensure originality does not introduce cognitive friction.
4. **Design Tokens & Palette Constraints**: Established `DESIGN.md` brand colors and typography scale to prevent rogue style divergence.

---

## 5. Outputs to Expect

Expect critique and alternatives targeting generic AI stereotypes:
- **AI Trope Detection**: Identifies clichés such as uniform 3-card grids, centered purple gradient hero sections, ubiquitous glowing border buttons, and floating glassmorphism cards without purpose.
- **Structural Layout Variety**: Asymmetric grid suggestions, editorial typographic pacing, varied card proportions, and distinctive section dividers.
- **Palette & Surface Guidance**: Grounded color combinations, high-craft neutral ramps, and intentional contrast rather than "safe" generic purple/indigo AI defaults.
- **Component Personality**: Tailored UI signifiers that match the specific domain rather than looking like an off-the-shelf component library demo.

---

## 6. Actionable Findings

Findings are actionable when they eliminate clichés without harming usability:
- **Template Sameness**: Every container having the exact same aspect ratio, background surface, and drop shadow regardless of content hierarchy.
- **Predictable AI Defaults**: Purple/violet gradients on primary buttons, centered marketing copy with generic badge headers ("✨ The Future of...").
- **Hollow Visual Novelty**: Gimmicky animations or decorative shapes that add no semantic value.
- **Unearned Symmetry**: Forcing content into rigid symmetric columns where an asymmetric hierarchy (e.g. 60/40 split with clear primary focus) would better guide the eye.

---

## 7. Severity Mapping & Critique Normalization

All Hallmark findings must be normalized into the unified UX Critique Contract:

```yaml
finding:
  source: hallmark
  rule_id: HLM-xxx
  severity: P2 | P3
  actionability: Required | Recommended | Contextual | Ignore
  category: slop | visual
  evidence: "<exact code snippet or pattern identified>"
  recommendation: "<concrete alternative layout or styling pattern>"
  confidence: 0.80
```

### Severity Tiers:
- **`P2` (Medium / Anti-Slop Violation)**: Egregious AI cliché on a flagship or consumer-facing view (e.g. purple gradient card soup, generic template look).
- **`P3` (Low / Distinctiveness Suggestion)**: Opportunity for stronger typographic character, asymmetric layout pacing, or unique border treatment.

> [!IMPORTANT]
> **Precedence Law**: Hallmark findings NEVER override P0 accessibility, UX cognitive clarity, or established `DESIGN.md` tokens:
> ```text
> P0 Accessibility ➔ UX Correctness ➔ Design Tokens ➔ Responsive Quality ➔ Visual Polish (Impeccable) ➔ Anti-Slop (Hallmark)
> ```
> Hallmark saying *"make this more distinctive"* DOES NOT override UX saying *"the existing familiar pattern reduces cognitive load."*

---

## 8. When to Skip

Skip Hallmark to conserve token budgets and avoid pointless friction:
- **Accessibility-Only Workflows (`/ux a11y`, `audit_ux.py`)**: Dedicated a11y repairs.
- **Internal CRUD / Admin Dashboards**: Administrative tables, settings pages, and developer dashboards where familiar platform patterns reduce cognitive load and increase task speed.
- **Atomic Controls & System Utilities**: Checkboxes, buttons, dropdowns, modal shells, and form fields where standard platform conventions must be preserved.
- **Existing Design System Compliance**: When the codebase strictly mandates exact design system component reuse (e.g. corporate enterprise library).

---

## 9. Preflight Installation & Graceful Fallback

1. **Preflight Check**:
   The agent checks whether Hallmark tooling is installed or accessible via upstream [nutlope/hallmark](https://github.com/nutlope/hallmark).
2. **Autonomous Graceful Fallback**:
   If Hallmark is not installed or unavailable:
   - The absence of Hallmark MUST NEVER fail the UX pipeline or stop `--autopilot` execution.
   - The UX workflow continues autonomously: `UX + Impeccable continue`.
   - Log: `hallmark: skipped (nutlope/hallmark unavailable; continuing autonomously with UX + Impeccable)`.
