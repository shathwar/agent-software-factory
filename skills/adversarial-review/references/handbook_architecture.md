# Engineering Handbook: Architecture (Stages 8–9)

Consult this reference when evaluating SOLID principles, design patterns, and architectural decoupling.

---

## Stage 8: SOLID Principles in Practice

- **Single Responsibility Principle (SRP)**:
  - *Symptom of Violation*: A service parses inbound messages, makes HTTP broker calls, computes risk formulas, and persists audit logs.
  - *Fix*: Decompose into cohesive layers: Stream Consumer -> Service Orchestrator -> Domain Formula / Broker Client.
- **Open/Closed Principle (OCP)**:
  - *Symptom of Violation*: Adding a new strategy, broker, or indicator requires modifying a 300-line `switch/case` or `if/elif` block.
  - *Fix*: Use a strategy registry, factory pattern, or polymorphic dispatch via interfaces.
- **Liskov Substitution Principle (LSP)**:
  - *Symptom of Violation*: Subclass throws `UnsupportedOperationException` for methods declared on the interface, or requires callers to perform `instanceof` / `isinstance` checks.
  - *Fix*: Refactor the hierarchy or split the interface.
- **Interface Segregation Principle (ISP)**:
  - *Symptom of Violation*: Fat interfaces with 20 methods where consumers only ever use 2.
  - *Fix*: Break into fine-grained role interfaces (e.g. `OrderReader`, `OrderWriter`).
- **Dependency Inversion Principle (DIP)**:
  - *Symptom of Violation*: Business logic instantiates concrete network clients or persistence drivers directly (`new FyersHttpClient()`).
  - *Fix*: Depend on abstractions (`BrokerClient`) injected via dependency injection or constructors.

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
