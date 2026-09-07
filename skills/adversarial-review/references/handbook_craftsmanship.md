# Engineering Handbook: Craftsmanship (Stages 4–7)

Consult this reference when evaluating Simplicity, Maintainability, Reuse, and Performance.

---

## Stage 4: Simplicity (YAGNI & Minimalism)

- **The Simplest Solution That Works**:
  - Challenge every new abstraction: *"Do we actually need this interface/factory right now, or is it for speculative future requirements?"*
  - If a feature has only ONE implementation and no immediate prospect of a second, keep it concrete.
- **Deletion Over Addition**:
  - Actively hunt for dead code, unused parameters, obsolete imports, and deprecated methods.
  - The cleanest pull request is often the one that deletes more code than it adds.
- **Standard Library First**:
  - Prefer native platform and standard library capabilities (`java.time`, `java.util.concurrent`, Python `math`, `asyncio`, `pathlib`) over introducing third-party dependencies or custom utility wheels.
  - Shortest sound working diff wins.

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
  - Caches must have maximum size bounds (eviction policy like LRU) and TTLs to prevent memory exhaustion (`OutOfMemoryError`).
