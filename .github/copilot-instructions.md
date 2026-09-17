# GitHub Copilot Instructions

## Engineering Lifecycle Standards

When assisting in this repository:

1. **Test-Driven Development (TDD)**:
   - Always write failing behavioral unit/integration tests before writing implementation code.
   - Run tests to confirm assertion failure before implementing.
   - For database persistence, use ephemeral databases (SQLite, Testcontainers); do not mock database engines.

2. **In-Flight Adversarial Doubt**:
   - For non-trivial logic (branching, concurrency, boundary crossing, data mutation), challenge assumptions and look for race conditions, unhandled edge cases, and hidden coupling before finalizing changes.

3. **Code Craftsmanship & Laziness Ladder**:
   - Rely on standard library utilities and existing helpers before introducing new third-party dependencies.
   - Keep control flow flat; use early returns and guard clauses.
   - Tag necessary pragmatic technical shortcuts with `// simplify: <Shortcut>. Ceiling: <Limit>. Upgrade: <Next>.` debt markers.

4. **Adversarial Review Standards**:
   - Audit code for OWASP Top 10 vulnerabilities, input injection, secret leakage, and Core Web Vitals (LCP, CLS, INP) where applicable.
   - Adhere strictly to the 12-field finding schema in `skills/review/references/finding_schema.md`.
