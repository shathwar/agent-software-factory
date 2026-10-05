# State Completeness & Interaction Models

**Core Law**: **Every component must define all applicable states for its interaction model.**

Writing only the "happy path" or forcing an inflexible taxonomy onto complex UI controls is strictly forbidden. State models must reflect whether a component is a data container, an interactive control, or a compound widget.

---

## 1. Views & Organisms (Data Containers & Screens)

For pages, tables, feeds, dashboards, cards, and modal dialogs:

| State | Purpose & Requirements | Manifestation / Pattern |
|---|---|---|
| **Empty** | First-run onboarding or zero search/filter results. | Friendly illustration/icon + clear explanation + Primary CTA to create first item. |
| **Loading** | Mitigates perceived latency and eliminates Cumulative Layout Shift (CLS). | Content-shaped pulsing skeleton loader matching incoming row/card geometry. |
| **Populated** | The ideal happy path with realistic data densities. | Clean hierarchy, text wrapping, truncation rules, hover states on list items. |
| **Partial / Stale** | Pagination boundaries, overflow limits, or background revalidating stale data. | Item counter ("Showing 25 of 1,420") + stale data banner or revalidation indicator. |
| **Error / Recovery** | Graceful failure without technical blame; preserves user inputs. | Contextual alert badge + explanation + actionable CTA (e.g., "Retry", "Reload"). |
| **Unavailable / Forbidden** | Control or view blocked by RBAC permissions, tier gates, or maintenance. | Reduced opacity + tooltip or banner explaining *why* locked and *how to unlock*. |

---

## 2. Controls & Atoms (Interactive Elements)

For buttons, inputs, toggles, badges, and icon triggers:

| State | Trigger / Condition | Visual & Accessibility Requirement |
|---|---|---|
| **Default** | Resting state. | Base colors, borders, and clear interactive signifiers. |
| **Hover** | Cursor over element. | Subtle contrast shift (brightness, shadow) signaling affordance. |
| **Focus-visible** | Keyboard navigation (`Tab`). | High-contrast `:focus-visible` ring; never suppress outline. |
| **Pressed / Active** | Pointer down (`:active`). | Immediate tactile feedback (inset shadow, slight scale or depression). |
| **Disabled** | Non-interactive / locked. | Reduced opacity (0.5), cursor `not-allowed`, `aria-disabled="true"`. |
| **Busy / Loading** | In-flight async execution. | `aria-busy="true"`; replace icon with inline spinner, preserve button width. |

---

## 3. Compound & Contextual States (When Applicable)

Specialized controls require domain-specific state definitions to prevent broken UX:

- **Selected**: Tabs, segment controls, selectable list rows (`aria-selected="true"`).
- **Checked / Indeterminate**: Checkboxes, toggle switches (`aria-checked="true"` or `"mixed"`).
- **Expanded / Collapsed**: Accordions, dropdown menus, comboboxes, tree views (`aria-expanded="true/false"`).
- **Invalid**: Form inputs failing client/server validation (`aria-invalid="true"`, error message linked via `aria-describedby`).
- **Read-only**: Form fields displaying fixed data (`readOnly`, distinct from disabled styling so text remains selectable and screen-reader accessible).
