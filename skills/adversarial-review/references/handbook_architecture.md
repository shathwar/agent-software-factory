# Engineering Handbook: Architecture (Stages 8–9)

Consult only when active checks require SOLID or pattern analysis.

Treat smells and suggested fixes as prompts for investigation, not automatic findings or mandatory refactors. Repository conventions and current requirements govern. Require a concrete cost before recommending change; do not add abstractions merely because SOLID or a pattern permits one.

## Stage 8: SOLID Principles in Practice

Use these questions to locate costs in the current change. A label alone is not a finding.

- **Single responsibility:** Do unrelated changes repeatedly affect this module or force callers to coordinate its internals? A cohesive operation may legitimately parse, compute, and persist; several verbs do not prove it needs several layers.
- **Open/closed:** Does a required extension duplicate branching or force scattered edits? Compare a local branch or table with a new strategy hierarchy before recommending either.
- **Substitution:** Does an implementation violate behavior promised by its interface, including accepted inputs, failures, and lifecycle? Verify the contract rather than treating every unsupported operation as invalid.
- **Interface segregation:** Must callers learn or depend on operations they do not need? Split only when doing so reduces a demonstrated dependency or maintenance burden.
- **Dependency inversion:** Does direct construction of an external dependency prevent needed configuration or behavior tests? Reuse the existing boundary or pass a concrete dependency before proposing a new interface.

---

## Stage 9: Design Patterns & Anti-Patterns

- **Appropriate Patterns**:
  - **Strategy**: For swappable algorithms (e.g. trailing stop-loss models, routing engines).
  - **Observer / Pub-Sub**: For decoupled event notifications (e.g. cache invalidation events).
  - **Single-Flight / Keyed Mutex**: For deduplicating concurrent expensive operations across symbols.
  - **Circuit Breaker / Retry**: For resilient broker and external service communication.
- **Pattern Anti-Patterns**:
  - *Patternitis*: Introducing Factory-of-Factories or abstract factories for a single class.
  - *God Object*: Giant monolithic service controlling persistence, execution, and risk.
  - *Leaky Abstraction*: Implementation specifics leaking through API contracts or interfaces.
