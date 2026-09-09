# Engineering Handbook: Craftsmanship (Stages 4–7)

Consult the relevant sections for simplicity, maintainability, reuse, and performance. Design owns complexity checks; the orchestrator retains general performance.

Treat smells and suggested fixes as prompts for investigation, not automatic findings or mandatory refactors. Repository conventions and current requirements govern. Require a concrete cost before recommending change; do not add abstractions merely because SOLID or a pattern permits one.

## Stage 4: Simplicity (YAGNI & Minimalism)

- **The Simplest Solution That Works**:
  - Challenge every new abstraction: *"Do we actually need this interface/factory right now, or is it for speculative future requirements?"*
  - One implementation is not by itself a defect or a reason for an interface. Ask whether the boundary hides meaningful complexity or isolates a present external dependency.
- **Deletion Over Addition**:
  - Actively hunt for dead code, unused parameters, obsolete imports, and deprecated methods.
  - Deletion is useful only when it removes an actual cost without losing required behavior.
- **Standard Library First**:
  - Prefer native platform and standard library capabilities (`java.time`, `java.util.concurrent`, Python `math`, `asyncio`, `pathlib`) over introducing third-party dependencies or custom utility wheels.
  - Shortest sound working diff wins.
- **Fowler Code Smells Baseline (Simplification Focus)**:
  - *Repo standards precedence*: Documented repo standards (`CODING_STANDARDS.md`, `CONTRIBUTING.md`) always override baseline heuristics.
  - *Tooling exemption*: Skip formatting or stylistic issues already enforced by repo linters (Ruff, ESLint, Checkstyle).
  - **Speculative Generality**: Abstraction, parameters, or hooks added for hypothetical needs not in the spec. $\rightarrow$ delete it; inline back until real need shows.
  - **Middle Man**: A class or method that mostly just forwards calls directly onward without adding value. $\rightarrow$ cut it, call the real target direct.
  - **Duplicated Code**: Similar blocks that encode the same domain rule and must evolve together. $\rightarrow$ consider sharing that rule; independently evolving code may stay separate.
  - **Refused Bequest**: Subclass or implementer that ignores or throws `UnsupportedOperationException` on inherited methods. $\rightarrow$ drop inheritance, use composition.

---

## Stage 5: Maintainability & Cognitive Load

- **Low Indirection**:
  - Code should read like well-written prose. Avoid "bounce-around" code where reading a 10-line method requires jumping through 5 one-line wrapper methods.
- **Flat Control Flow**:
  - Guard clauses and early returns (`if (!condition) return;`) preferred over 4 levels of nested `if/else` blocks.
- **Domain-Specific Naming**:
  - Variables and methods must use terms from the business domain (e.g. `isSquareOffTime()`, `activeTrailOrders`, `ltpThreshold`) instead of implementation mechanics (`flag1`, `processData()`, `tempObj`).
- **Testability & Determinism**:
  - Isolate non-deterministic elements (system clock, random numbers, external networks) so logic can be tested deterministically.
- **Fowler Code Smells Baseline (Maintainability Focus)**:
  - **Mysterious Name**: A function, variable, or type whose name doesn't reveal what it does or holds. $\rightarrow$ rename it; if no honest name comes, the design is murky.
  - **Feature Envy**: A method that reaches into another object's fields or getters more than its own. $\rightarrow$ move the method onto the data it envies.
  - **Data Clumps**: The same 3+ fields or parameters travelling together across multiple signatures. $\rightarrow$ bundle into a cohesive domain type or value object.
  - **Primitive Obsession**: Raw primitives (`String`, `int`) standing in for domain concepts (e.g. `orderId`, `currency`, `percentage`). $\rightarrow$ introduce small type-safe domain wrappers.
  - **Repeated Switches**: The same `switch` or `if/else` cascade on the same type recurring across files. $\rightarrow$ replace with polymorphism or a centralized strategy map.
  - **Shotgun Surgery**: One logical change forces scattered modifications across dozens of files. $\rightarrow$ gather what changes together into one cohesive module.
  - **Divergent Change**: One file or class is repeatedly edited for completely unrelated business reasons. $\rightarrow$ split so each module has a single axis of change (SRP).
  - **Message Chains**: Deep traversal like `a.getB().getC().getD().execute()`. $\rightarrow$ hide the navigation behind a method on the immediate object (Law of Demeter).

---

## Stage 6: Reuse (DRY & Drift Prevention)

- **Identify Duplicate Implementations**:
  - Look for duplicated symbol parsing, date arithmetic, rate limiting, or hash calculations across multiple files or repositories.
  - Check whether a helper or utility class already exists in the codebase before approving new code.
- **Constant & Prefix Drift Prevention**:
  - Never hardcode magic strings (e.g. Redis stream prefixes `"market:streams:instrument:"`, topic names, header names) in multiple locations. Centralize them in shared constants.
- **Reusable Domain Formulas**:
  - Stop-loss calculation, ATM strike determination, and risk percentage math should be centralized and thoroughly unit-tested.

---

## Stage 7: Performance & Resources

- **Hot-Path Allocations & GC Pressure**:
  - Avoid unnecessary object allocations and string concatenations inside high-frequency processing loops (e.g. tick stream consumers).
  - Use `StringBuilder` instead of `+` in tight loops.
- **Algorithmic Complexity**:
  - Watch for nested loops causing $O(n^2)$ complexity on large datasets. Use hash lookups ($O(1)$) or pre-indexed collections.
- **Database & Query Performance**:
  - Eliminate N+1 query patterns; use batch fetches or joins.
  - Verify that database queries filter on indexed columns (`WHERE symbol = ... AND created_at >= ...`).
- **Resource Boundedness**:
  - Establish whether cache growth is bounded by its input domain or an eviction policy. Require TTLs only when freshness or lifecycle calls for them.
