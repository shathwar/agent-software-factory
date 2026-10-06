# Usability Heuristics & Cognitive Friction Rubric

Grounded in **Jakob Nielsen's 10 Usability Heuristics** and **Steve Krug's Laws of Usability** (*Don't Make Me Think*).

---

## 1. Nielsen's 10 Heuristics Inspection Checklist

| Heuristic | Code & UI Manifestation | Anti-Pattern Failure Mode |
|---|---|---|
| **1. Visibility of System Status** | Spinners, skeletons, progress bars, active tab indicator. | Button clicked with zero visual feedback; long operations with blank screen. |
| **2. Match Between System & Real World** | Plain English domain vocabulary; ISO standard conventions. | Displaying raw database error codes (`ERR_PG_UNIQUE_VIOLATION`), unformatted ISO timestamps. |
| **3. User Control & Freedom** | Clear "Cancel", "Back", "Escape" hotkey, non-destructive undo. | Modal dialogs that cannot be closed by `Escape` or backdrop click; irreversible deletions without confirmation. |
| **4. Consistency & Standards** | Platform-standard UI controls; design tokens for color/spacing. | Custom reinvented dropdowns that break arrow keys; primary action on left on one page, right on another. |
| **5. Error Prevention** | Disabling invalid submit options, input masks, destructive confirmations. | Allowing user to type letters into phone inputs; accidental clicks immediately wiping user data. |
| **6. Recognition Over Recall** | Visible options, autocomplete, field placeholders, tooltips. | Forcing user to remember codes or IDs from previous screens; icon-only buttons with zero tooltips. |
| **7. Flexibility & Efficiency of Use** | Keyboard shortcuts (`Enter` to submit, `Esc` to close), bulk actions. | Mouse-only requirement; forms requiring 10 clicks when tab navigation could suffice. |
| **8. Aesthetic & Minimalist Design** | Uncluttered visual hierarchy; essential content prioritised over visual noise. (Visual refinement delegated to Impeccable; anti-slop delegated to Hallmark). | Crammed layouts, competing calls-to-action, and gratuitous decorative clutter obscuring primary user tasks. |
| **9. Help Users Recognize, Diagnose, & Recover from Errors** | Contextual inline errors explaining *what*, *why*, and *how to fix*. | "Invalid input" or "Error 500" with no guidance on which field failed or what to do next. |
| **10. Help & Documentation** | Inline helper text, contextual tooltips, FAQs near friction points. | Unexplained technical parameters with no tooltip or docs link. |

---

## 2. Krug's Cognitive Friction Audit ("Don't Make Me Think")

1. **The Trunk Test (Orientation)**:
   - If dropped blindfolded onto any subpage, can the user answer immediately:
     - What site / app is this?
     - What page / screen am I on?
     - What are the major sections?
     - Where can I go from here?
     - How do I search or go home?

2. **Visual Hierarchy & Scannability**:
   - The eye must naturally follow a clear path: Heading ➔ Primary Visual ➔ Body ➔ Primary CTA.
   - Everything that is clickable must look clearly clickable (affordance / signifier).
   - Everything that is not clickable must never look clickable (no underlined non-link text).

3. **Omission of Unnecessary Words**:
   - Cut happy talk, conversational preamble, and corporate fluff from UI copy.
   - Labels must be concise verbs: `Save Changes`, `Delete Project`, `Invite Member`.
