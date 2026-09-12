# Testing Anti-Patterns Catalog

A catalog of testing anti-patterns—especially common in AI-assisted development—and how to detect and correct them during the TDD cycle.

---

## 1. The Retrospective Test (Backfill Fallacy)

### Symptom
The agent writes 150 lines of production code, announces *"Now I will write the tests"*, and creates a test file whose tests pass on the very first execution.

### The Problem
You have no evidence that the test was ever capable of failing. Often, these tests assert trivial things, assert tautologies (`expect(true).toBe(true)`), or miss critical boundary conditions that the production code silently mishandles.

### The Fix
Enforce **Law 1 & Law 2 of TDD**:
1. Stash or revert the production code.
2. Write the single test case.
3. Run the test runner and verify it **fails with an assertion error**.
4. Restore only the minimal lines of production code needed to satisfy the assertion.

---

## 2. The Mirrored Implementation

### Symptom
The test recalculates the expected value by re-implementing the production algorithm:

```typescript
// Anti-Pattern: Test duplicates the production calculation
const expectedFee = items.reduce((sum, item) => sum + item.price * 0.0825, 0);
expect(calculator.calculateTax(items)).toBe(expectedFee);
```

### The Problem
If the business logic contains a conceptual bug (e.g. tax should not apply to shipping fees or digital goods), the test duplicates the exact same bug and happily passes.

### The Fix
Use **concrete, independently calculated fixtures**:
```typescript
// Correct: Pre-calculated invariant with known inputs
const items = [{ price: 100, taxExempt: false }, { price: 50, taxExempt: true }];
// 100 * 0.0825 = 8.25; exempt item taxed at 0
expect(calculator.calculateTax(items)).toBe(8.25);
```

---

## 3. The Overmocked Mirage

### Symptom
Every single function, repository, utility, and sub-service is mocked using `jest.fn()` or `unittest.mock`.

```python
# Anti-Pattern: Mocking everything
mock_repo = Mock()
mock_validator = Mock()
mock_hasher = Mock()
mock_validator.is_valid.return_value = True
mock_hasher.hash.return_value = "hashed_pw"

service = UserService(repo=mock_repo, validator=mock_validator, hasher=mock_hasher)
service.register("user@test.com", "password")

mock_repo.save.assert_called_once()
```

### The Problem
This test does not test that a user is registered. It only tests that `UserService` called three mocks in sequence. If `hasher` changes its return type, or `validator` changes its method name, this test remains 100% green while production crashes.

### The Fix
- **Use real domain objects and state**: Let the real validator and real hasher run.
- **Use in-memory fakes for persistence**: Use an `InMemoryUserRepository` that stores entities in a Python dict or JS Map.
- **Only mock true network/hardware boundaries**: Mock Stripe HTTP calls, S3 upload sockets, or OS system clocks.

---

## 4. The Shotgun Test (God Test)

### Symptom
A single test function named `test_user_flow()` that runs 80 lines: creates a user, checks email, updates profile, resets password, makes a purchase, checks inventory, and soft-deletes the user.

### The Problem
When the test fails at line 62, the entire test run stops. You cannot tell if password reset broke or if inventory decrement broke. It is impossible to isolate bugs.

### The Fix
Apply the **Single Responsibility Principle** to tests:
- `test_should_send_verification_email_on_signup()`
- `test_should_invalidate_sessions_on_password_reset()`
- `test_should_decrement_inventory_on_successful_checkout()`

Each test runs independently and can fail without masking the others.

---

## 5. The Sleep/Flake Anti-Pattern

### Symptom
Using arbitrary time delays to wait for asynchronous operations:
```javascript
// Anti-Pattern: Flaky timer
await service.dispatchJob(jobId);
await new Promise((resolve) => setTimeout(resolve, 500)); // Hope it finished
expect(await service.getJobStatus(jobId)).toBe('COMPLETED');
```

### The Problem
On a slow CI runner or under CPU throttling, 500ms is not enough, causing random test failures. On a fast runner, it needlessly wastes 490ms of idle time per test.

### The Fix
Use **deterministic polling or event-driven promises**:
```javascript
// Correct: Explicit polling with timeout
await service.dispatchJob(jobId);
await waitFor(async () => {
  const status = await service.getJobStatus(jobId);
  expect(status).toBe('COMPLETED');
}, { timeoutMs: 2000, intervalMs: 20 });
```

---

## 6. Testing Logic in Tests (Loops and Conditionals)

### Symptom
Writing `if/else` statements or complex `for` loops inside a test function:

```python
# Anti-Pattern: Logic in test
for user in users:
    if user.is_active:
        assert service.can_login(user) is True
    else:
        assert service.can_login(user) is False
```

### The Problem
Tests with branching logic can have their own bugs. If `user.is_active` is never `False` in the test data, the `else` branch is never evaluated, silently leaving inactive user logins untested.

### The Fix
Use **parameterized tests (table-driven tests)**:
```python
# Correct: Explicit table-driven cases
@pytest.mark.parametrize("is_active,expected", [
    (True, True),
    (False, False),
])
def test_user_login_eligibility(is_active, expected):
    user = create_user(is_active=is_active)
    assert service.can_login(user) is expected
```

---

## 7. The Whitebox Spy (Testing Private Methods)

### Symptom
Writing tests for private helpers or inspecting private class state:
```javascript
// Anti-Pattern: Accessing private internals
expect(orderService._calculateInternalTax(100)).toBe(8.25);
```

### The Problem
Private methods are implementation details. If you refactor the internal tax logic to a separate strategy class, all your tests break, even though the public behavior of `checkout()` never changed.

### The Fix
Test **through the public interface**:
- If an internal algorithm is so complex that it demands its own unit tests, extract it into a dedicated, testable domain class or pure helper function and test its public contract.
