# Engineering Handbook: Craftsmanship (Stages 4–7)

Investigation prompts for Simplicity, Maintainability, Reuse, and Performance. Design owns complexity; orchestrator retains general performance.

Rules govern over heuristics; require concrete costs before recommending refactors. Never add abstractions solely because a design pattern permits it.

---

## Stage 4: Simplicity (YAGNI & Minimalism)

- **Simplest Solution**:
  - Challenge abstractions: do not add interfaces/factories for hypothetical futures.
  - Single implementation is not a defect. Abstraction must isolate real external boundaries or complex logic.
- **Deletion Over Addition**:
  - Delete dead code, unused parameters, obsolete imports, and deprecated methods.
- **Standard Library First**:
  - Use native platform APIs (`java.time`, `java.util.concurrent`, Python `math`, `asyncio`, `pathlib`) before introducing dependencies.
  - Shortest sound working diff wins.
- **Fowler Smells (Simplification)**:
  - *Repo standards override baseline heuristics. Skip style enforced by linters.*
  - **Speculative Generality**: hooks/parameters for future needs $\rightarrow$ delete; inline.
  - **Middle Man**: class/method merely forwarding calls $\rightarrow$ cut; call target directly.
  - **Duplicated Code**: identical blocks encoding shared domain rules $\rightarrow$ consolidate; independently evolving logic may stay split.
  - **Refused Bequest**: subclass ignoring/throwing on inherited methods $\rightarrow$ replace inheritance with composition.

---

## Stage 5: Maintainability & Cognitive Load

- **Low Indirection**:
  - Code reads top-to-bottom. Avoid deep hops across one-line wrapper methods.
- **Flat Control Flow**:
  - Guard clauses and early returns (`if (!cond) return;`) over deeply nested branches.
- **Domain Naming**:
  - Use domain business terms (`isSquareOffTime()`, `activeTrailOrders`) instead of mechanical placeholders (`flag1`, `processData()`).
- **Testability & Determinism**:
  - Isolate clock, random sources, and network boundaries for deterministic testing.
- **Fowler Smells (Maintainability)**:
  - **Mysterious Name**: unclear intent $\rightarrow$ rename honestly.
  - **Feature Envy**: method accesses foreign data more than its own $\rightarrow$ move method to data owner.
  - **Data Clumps**: 3+ fields/params passed together $\rightarrow$ bundle into domain value object.
  - **Primitive Obsession**: raw primitives for domain concepts (`orderId`, `currency`) $\rightarrow$ introduce type-safe wrappers.
  - **Repeated Switches**: identical branching across files $\rightarrow$ replace with polymorphism or strategy map.
  - **Shotgun Surgery**: one logical change touches dozens of files $\rightarrow$ co-locate related logic.
  - **Divergent Change**: single class edits for unrelated business axes $\rightarrow$ split along SRP boundaries.
  - **Message Chains**: deep traversal (`a.getB().getC().getD()`) $\rightarrow$ apply Law of Demeter; hide navigation.

---

## Stage 6: Reuse (DRY & Drift Prevention)

- **Duplicate Logic**:
  - Check for duplicated symbol parsing, date arithmetic, rate limiting, or hash helpers before adding new utilities.
- **Constant & Prefix Drift**:
  - Never hardcode magic strings (Redis prefixes, stream topics, header names). Centralize in shared constants.
- **Reusable Domain Math**:
  - Centralize domain formulas (stop-loss calculation, strike selection, risk sizing); verify unit test coverage.

---

## Stage 7: Performance & Resources

- **Hot-Path Allocations & GC**:
  - Avoid allocations and string concatenations in tight tick/event loops (`StringBuilder` over `+`).
- **Algorithmic Complexity**:
  - Replace $O(n^2)$ nested loops with $O(1)$ set/map lookups or pre-indexed collections.
- **Database & Query Performance**:
  - Eliminate N+1 query patterns; use batch fetches or joins.
  - Ensure filters query indexed columns (`WHERE symbol = ... AND created_at >= ...`).
- **Resource Boundedness**:
  - Ensure caches and memory structures have explicit size bounds, eviction policies, or TTLs.
