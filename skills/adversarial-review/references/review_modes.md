# Review Modes & Tailored Invocations

Guidance on adapting the review depending on the specific phrasing of the user's prompt, organized across the 9-stage review hierarchy.

---

## 1. Mode Matching Table

| User Trigger / Prompt Phrasing | Activated Review Mode | Primary Focus Stages | Output Emphasis |
|---|---|---|---|
| *"do an adversarial review"*, *"adversarial code review"*, *"find all bugs"* | **Full Adversarial Audit** | **All 9 Stages** (Emphasis on Stages 1–3) | Complete scorecard, P0/P1 issues, live production impact scenarios, code fixes |
| *"review like a principal engineer"*, *"review SOLID, YAGNI, reusability"* | **Principal Engineer Architectural Review** | **Stages 4, 5, 6, 8, 9** (Simplicity, Maintainability, Reuse, SOLID, Patterns) | Architectural critique, simplification, decoupling, pattern alignment |
| *"do another pass for reusability / DRY"* | **Reusability & DRY Pass** | **Stage 6** (Reuse) | Candidates for shared utils, diff reduction, constant centralization |
| *"adversarial review for cognitive load and complexity"* | **Cognitive Load & Simplicity Pass** | **Stages 4, 5** (Simplicity, Maintainability) | Flatter code, domain-specific naming, early returns, lower indirection |
| *"review for concurrency / thread safety"* | **Concurrency & Safety Pass** | **Stage 2** (Concurrency / Safety) | Lock analysis, race windows, atomic collections, async task lifecycles |
| *"review performance / allocations"* | **Performance Pass** | **Stage 7** (Performance) | Hot-path allocations, GC pressure, DB queries, complexity |
| *"review risks to deploy in production"*, *"pre-deploy review"* | **Pre-Deploy Production Risk Audit** | **Production Risk Matrix** + **Stages 1, 2, 3** | Deployment safety, contract integrity, database migrations, operational blast radius |
| *"review PR <url>"*, *"review changes in last N days"* | **Scoped Pull Request Audit** | **All 9 Stages** across changed PR files | Full diff vs base branch, end-to-end caller tracing, regression checks |

---

## 2. Handling Iterative / Multi-Pass Reviews

When the user asks for multiple passes (e.g. *"do another round of adversarial review"* or *"do another pass for reusability"*):

1. **Acknowledge Previous Fixes**: Verify that issues found in earlier passes were correctly addressed and did not introduce secondary bugs.
2. **Step Through the 9-Stage Cascade**: Re-evaluate the updated diff through the next stage of the hierarchy.
3. **Avoid Repetition**: Do not regurgitate resolved findings. Focus entirely on new, subtle opportunities or remaining gaps.
4. **Be Honest When Clean**: If no further flaws exist after deep inspection, state clearly: *"Zero critical issues identified in this pass. The changes are sound, clean, and ready for deployment."* Never manufacture fake nitpicks to fill space.
