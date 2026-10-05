# WCAG 2.1 / 2.2 AA Developer Reference

Essential rules and verification checklist for accessible user interfaces.

---

## 1. Contrast Ratios (WCAG AA)

- **Normal Text (< 18pt or < 14pt bold)**: Minimum **4.5:1** contrast against background.
- **Large Text (>= 18pt or >= 14pt bold)**: Minimum **3.0:1** contrast against background.
- **UI Components & Graphical Objects** (Borders, active icons, focus rings): Minimum **3.0:1** contrast against adjacent colors.
- **Decorative Elements / Inactive Controls**: Exempt from contrast minimums, but must remain distinguishable.

---

## 2. Keyboard Navigability & Focus Management

- **Complete Keyboard Reachability**: Every interactive element (buttons, links, inputs, dropdowns) must be reachable via `Tab` / `Shift+Tab`.
- **Visible Focus Indicator**:
  - NEVER use `outline: none` without providing an explicit replacement.
  - Recommended Tailwind: `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-600`.
- **Focus Trapping**: Modal dialogs must trap focus within the dialog while open, and return focus to the triggering element upon closing.
- **Escape Hotkey**: Modals, dropdown menus, and popovers must close on `Escape`.

---

## 3. Semantic HTML & ARIA Rules

- **First Rule of ARIA**: Do NOT use ARIA if a native HTML element exists (`<button>` over `<div role="button">`).
- **Icon Buttons**: Always require accessible labels:
  ```html
  <!-- Good -->
  <button type="button" aria-label="Close dialog">
    <svg aria-hidden="true" class="w-5 h-5" ... />
  </button>
  ```
- **Form Controls**: Every input must have an accessible name:
  ```html
  <!-- Option A: Explicit label association -->
  <label for="email-field">Email Address</label>
  <input id="email-field" type="email" />

  <!-- Option B: aria-label for compact search inputs -->
  <input type="search" aria-label="Search documents" />
  ```
- **Landmarks**: Use `<header>`, `<nav>`, `<main>`, `<aside>`, `<footer>` instead of unsemantic `<div>` containers.
