# Testing Anti-Patterns Catalog

High-frequency testing defects in AI-assisted development and their strict contrast corrections.

---

## 1. Retrospective Test (Backfill Fallacy)

*Rule: Never write production code before observing a failing behavioral test.*

```text
❌ BAD:
1. Agent writes 150 lines of production code.
2. Agent announces "Now I will write the tests."
3. Test passes on first run without ever proving failure.

✅ GOOD:
1. Write single behavioral test asserting expected outcome.
2. Run test runner; prove assertion failure (terminal receipt).
3. Write minimum production code to satisfy assertion.
```

---

## 2. Mirrored Implementation

*Rule: Assert fixed, pre-calculated invariants. Never re-implement production math in the test.*

```typescript
// ❌ BAD: Test duplicates production calculation (duplicates conceptual bugs)
const expectedFee = items.reduce((sum, item) => sum + item.price * 0.0825, 0);
expect(calculator.calculateTax(items)).toBe(expectedFee);

// ✅ GOOD: Pre-calculated invariant with concrete inputs
const items = [{ price: 100, taxExempt: false }, { price: 50, taxExempt: true }];
expect(calculator.calculateTax(items)).toBe(8.25);
```

---

## 3. Overmocked Mirage

*Rule: Test real domain state and in-memory fakes. Mock only real external I/O boundaries (Stripe, S3, Clock).*

```python
# ❌ BAD: Mocking all collaborators (tests call sequence, not behavior)
mock_repo, mock_val, mock_hash = Mock(), Mock(), Mock()
service = UserService(repo=mock_repo, validator=mock_val, hasher=mock_hash)
service.register("user@test.com", "pass")
mock_repo.save.assert_called_once()  # Green even if types crash in production

# ✅ GOOD: Real domain objects with in-memory persistence fake
fake_repo = InMemoryUserRepository()
service = UserService(repo=fake_repo, validator=RealValidator(), hasher=RealHasher())
service.register("user@test.com", "pass")
assert fake_repo.find_by_email("user@test.com").is_active is True
```

---

## 4. Shotgun God Test

*Rule: Single Responsibility per test. One assertion target per test.*

```python
# ❌ BAD: 80-line mega-test masking cascade failures
def test_user_lifecycle():
    user = signup()
    verify_email(user)
    reset_password(user)      # If this fails...
    checkout_cart(user)       # ...we never know if checkout works
    delete_user(user)

# ✅ GOOD: Isolated atomic tests
def test_should_send_verification_email_on_signup(): ...
def test_should_invalidate_sessions_on_password_reset(): ...
def test_should_decrement_inventory_on_checkout(): ...
```

---

## 5. Sleep / Flake Anti-Pattern

*Rule: Deterministic polling or event-driven promises. Zero arbitrary `sleep()` or `setTimeout()`.*

```javascript
// ❌ BAD: Arbitrary sleep (flaky on slow CI, wasteful on fast CI)
await service.dispatchJob(jobId);
await new Promise((resolve) => setTimeout(resolve, 500));
expect(await service.getJobStatus(jobId)).toBe('COMPLETED');

// ✅ GOOD: Explicit condition polling with timeout
await service.dispatchJob(jobId);
await waitFor(async () => {
  expect(await service.getJobStatus(jobId)).toBe('COMPLETED');
}, { timeoutMs: 2000, intervalMs: 20 });
```

---

## 6. Logic & Branching Inside Tests

*Rule: Keep tests linear and branchless. Use table-driven parameterized tests.*

```python
# ❌ BAD: Conditionals in test (untested branches hide bugs)
for user in users:
    if user.is_active:
        assert service.can_login(user) is True
    else:
        assert service.can_login(user) is False

# ✅ GOOD: Table-driven parameterized cases
@pytest.mark.parametrize("is_active,expected", [
    (True, True),
    (False, False),
])
def test_user_login_eligibility(is_active, expected):
    user = create_user(is_active=is_active)
    assert service.can_login(user) is expected
```

---

## 7. Whitebox Spy (Testing Private Internals)

*Rule: Assert observable public behavior. Never couple tests to private methods or internal state.*

```javascript
// ❌ BAD: Tests break on internal refactors even when behavior is intact
expect(orderService._calculateInternalTax(100)).toBe(8.25);

// ✅ GOOD: Assert public behavior or extract pure standalone helper
expect(orderService.checkout({ amount: 100 })).toEqual(
  expect.objectContaining({ tax: 8.25 })
);
```
