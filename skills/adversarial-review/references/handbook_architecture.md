# Engineering Handbook: Architecture (Stages 8–9)

Investigation prompts for SOLID Principles and Design Patterns. Consult only when active checks require architectural evaluation.

Require demonstrated maintenance/testability costs before recommending structural changes.

---

## Stage 8: SOLID Principles in Practice

- **Single Responsibility (SRP)**:
  - Do unrelated business changes touch this module? Multiple verbs (`parse`, `compute`, `persist`) within a cohesive unit do not justify extra layers unless axes of change diverge.
- **Open / Closed (OCP)**:
  - Does extending functionality require scattered code edits? Compare simple dispatch tables against full strategy hierarchies before proposing abstractions.
- **Liskov Substitution (LSP)**:
  - Does a subclass/implementation break caller expectations, input domains, error contracts, or lifecycles?
- **Interface Segregation (ISP)**:
  - Are callers forced to depend on methods they never invoke? Split interfaces only when it decouples concrete dependencies.
- **Dependency Inversion (DIP)**:
  - Does direct instantiation block needed test isolation or runtime configuration? Pass concrete instances before inventing new interfaces.

---

## Stage 9: Design Patterns & Anti-Patterns

- **Appropriate Patterns**:
  - **Strategy**: Swappable algorithms (trailing stop-loss, execution routers).
  - **Observer / Pub-Sub**: Decoupled event broadcast (cache invalidation).
  - **Single-Flight / Keyed Mutex**: Deduplicating concurrent identical expensive fetches.
  - **Circuit Breaker / Retry**: Bounded resilience against external dependency failure.
- **Pattern Anti-Patterns**:
  - **Patternitis**: Abstract factories or multiple indirection layers for single implementations.
  - **God Object**: Giant monolithic class bundling persistence, execution, and business rules.
  - **Leaky Abstraction**: Exposing storage/transport details across API contracts.
