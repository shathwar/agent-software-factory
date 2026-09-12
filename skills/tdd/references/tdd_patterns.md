# TDD Patterns & Testability Guide

A practical reference on designing for testability, choosing effective test doubles, and structuring resilient test suites during the TDD cycle.

---

## 1. Test Structure: The Arrange-Act-Assert (AAA) Pattern

Every unit and behavioral test should follow the tripartite structure:

```python
def test_should_apply_loyalty_discount_when_cart_exceeds_threshold():
    # 1. Arrange: Setup inputs, fixtures, and state
    customer = Customer(tier="gold", points=500)
    cart = Cart(customer=customer)
    cart.add_item(Item(name="Mechanical Keyboard", price=120.00))

    # 2. Act: Invoke the single operation under test
    order = cart.checkout(discount_policy=LoyaltyDiscountPolicy())

    # 3. Assert: Verify the outcome and invariant
    assert order.total == 108.00  # 10% discount applied
    assert order.discount_amount == 12.00
```

### Key AAA Rules:
- **One Act per test**: A test that contains multiple acts separated by intermediate assertions is testing a workflow or sequence, not an isolated unit behavior.
- **Clear visual separation**: Keep empty lines between the Arrange, Act, and Assert blocks.
- **Obvious test data**: Hardcode test values that directly illustrate the rule (e.g. `price=120.00` and `discount=12.00` makes 10% self-evident, unlike `price=37.19`).

---

## 2. Test Doubles Taxonomy

Using the wrong kind of test double leads to brittle tests or false confidence. Know the 5 types:

```text
┌────────────────────────────────────────────────────────┐
│                      TEST DOUBLES                      │
├──────────┬──────────┬──────────┬───────────┬───────────┤
│  Dummy   │   Stub   │   Spy    │   Mock    │   Fake    │
│  (Args)  │ (Canned) │(Recorded)│ (Asserts) │(In-Memory)│
└──────────┴──────────┴──────────┴───────────┴───────────┘
```

| Type | Definition | Best Used When |
|---|---|---|
| **Dummy** | Passed around to fill parameter lists, never actually read or executed. | Required non-null arguments unrelated to the test scenario. |
| **Stub** | Returns canned data in response to specific calls. | Providing input from a collaborator (e.g. returning a hardcoded exchange rate). |
| **Spy** | A wrapper that records call counts, arguments, and return values without enforcing expectations upfront. | Verifying that an external notification or event was dispatched. |
| **Mock** | Pre-programmed with expectations about calls it *must* receive. Fails if unexpected calls occur. | Strict interaction testing at system boundaries (e.g. network driver). |
| **Fake** | A lightweight, working in-memory implementation of an interface. | Replacing databases or stores (e.g. `InMemoryUserRepository` backed by a map). |

> **Best Practice**: **Prefer Fakes over Mocks**. Fakes allow your tests to execute real state transitions without coupling your assertions to internal method names.

---

## 3. Designing for Testability

If a piece of code is hard to test with TDD, **the design is giving you architectural feedback**. Listen to it.

### 1. Invert Dependencies (Constructor Injection)
*Untestable* (Hardcoded dependency):
```typescript
class OrderService {
  async processOrder(order: Order) {
    const gateway = new StripePaymentGateway(); // Tightly coupled
    return gateway.charge(order.total);
  }
}
```

*Testable* (Injected interface):
```typescript
class OrderService {
  constructor(private readonly paymentGateway: PaymentGateway) {}

  async processOrder(order: Order) {
    return this.paymentGateway.charge(order.total);
  }
}
```

### 2. Isolate Time, Randomness, and Clocks
Never call `new Date()`, `time.time()`, or `uuidv4()` directly inside core business logic. Inject a clock or ID generator provider:

```python
class TokenIssuer:
    def __init__(self, clock: Callable[[], datetime]):
        self._clock = clock

    def issue_token(self, user_id: str) -> Token:
        now = self._clock()
        return Token(user_id=user_id, created_at=now, expires_at=now + timedelta(hours=1))
```
*In tests*: Pass `lambda: datetime(2026, 1, 1, 12, 0, 0)` for deterministic expiry assertions.

### 3. Functional Core, Imperative Shell
- **Functional Core**: Keep business decisions, tax calculations, validation rules, and state machines as pure, side-effect-free functions. These are trivial to test with high-density, millisecond-fast unit tests.
- **Imperative Shell**: Keep the I/O, database writes, and network orchestration thin and isolated at the edge. Test these with subcutaneous or integration tests.

---

## 4. Test Granularity & The Testing Trophy

Avoid the inverted pyramid (too many brittle unit tests of private functions, zero integration tests). Balance tests across layers:

1. **Unit / Domain Tests (Fastest, High Volume)**:
   - Exercise pure domain logic, entities, value objects, and algorithms.
   - Zero I/O, zero network, zero database. Execute in < 1ms per test.
2. **Subcutaneous / Component Tests (Medium Volume)**:
   - Exercise the public API of a component or module just below the UI/HTTP layer.
   - Use in-memory fakes for databases and external APIs.
3. **End-to-End / Integration Tests (Lowest Volume, Smoke)**:
   - Verify that all real components (DB driver, wire protocol, configuration) integrate properly on a single critical happy path.

---

## 5. Fast Test Execution Protocol for AI Agents

To keep the Red-Green-Refactor cycle rapid and responsive:
- **Run Targeted Tests**: Do not run the entire 10,000-test suite on every single cycle. Run the specific test file or test pattern:
  - *Jest/Vitest*: `npx vitest run path/to/feature.spec.ts`
  - *Pytest*: `pytest tests/test_feature.py -k test_specific_name`
  - *Go*: `go test -run TestSpecificName ./pkg/feature`
  - *Cargo*: `cargo test test_specific_name`
- **Run Full Suite Before Completion**: Once all incremental TDD cycles for a task are green, run the full test suite once to verify no regressions were introduced.
