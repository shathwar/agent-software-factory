# Simplify Technical Debt Tracking & Ledger Protocol

A guide to tracking deliberate shortcuts, defining operational ceilings, and preventing pragmatism from decaying into unmanaged technical debt.

---

## 1. The Purpose of the Debt Marker

In high-velocity engineering, building the ultimate distributed, infinitely-scalable solution on day one is premature optimization. However, taking a quick shortcut without documentation is reckless.

The `simplify:` comment strikes the balance:
- **It documents the shortcut explicitly**.
- **It specifies the operational ceiling** (when this shortcut will break or saturate).
- **It specifies the concrete upgrade path** (what to do when the ceiling is reached).

---

## 2. Syntax & Required Fields

Every `simplify:` comment must include three components:
1. **The Shortcut**: What pragmatic simplification was chosen over a heavier architecture.
2. **The Ceiling**: The numeric or architectural boundary where this solution becomes inadequate.
3. **The Upgrade**: The specific pattern or technology to replace it with.

### Standard Format

```text
// simplify: <Shortcut>. Ceiling: <Threshold/Limit>. Upgrade: <Next Architecture>.
```

### Examples by Domain

#### Concurrency & Locking
```go
// simplify: Coarse sync.Mutex around entire cache. Ceiling: 5,000 ops/sec. Upgrade: Sharded RWMutex or sync.Map if lock contention shows in p99.
type Cache struct {
    mu    sync.Mutex
    items map[string]Item
}
```

#### Persistence & Storage
```python
# simplify: SQLite in-process store. Ceiling: 1 node / 2,000 writes/sec. Upgrade: Postgres RDS with connection pooling if horizontally scaled.
DATABASE_URL = "sqlite:///./app.db"
```

#### Algorithms & Filtering
```typescript
// simplify: O(N) array search on active users. Ceiling: 1,000 active users in memory. Upgrade: Binary search or secondary Map index on userId.
const active = users.filter(u => u.isActive);
```

---

## 3. The Automated Debt Ledger

To automatically scan, validate syntax, and compile a Markdown debt ledger across the repository, run the **Debt Scanner**:

```bash
python3 skills/simplify/scripts/scan_debt.py
```

Use `--strict` in CI pipelines or pre-commit hooks to fail if any marker is missing a ceiling or upgrade path:

```bash
python3 skills/simplify/scripts/scan_debt.py --strict
```

Or perform a manual text search:

```bash
git grep -n "simplify:"
```

### Organizing the Ledger Report

When auditing codebase debt (e.g. prior to a major release or scaling phase), summarize findings into a structured table:

| Location | Shortcut Taken | Operational Ceiling | Designated Upgrade Path | Status |
|---|---|---|---|---|
| `src/auth.ts:42` | In-memory token blacklist | Single-instance server | Redis cluster blacklist | Safe (Single instance) |
| `src/reports.py:108` | Synchronous CSV generation | 5,000 rows / 10s request | Celery background job + S3 link | ⚠️ Near ceiling (rows > 4k) |

---

## 4. Ground Rules for Shortcuts

1. **Shortcuts must be correct within their ceiling**: A shortcut is never an excuse for broken invariants, data corruption, or security flaws. It is an algorithmic or architectural trade-off that is 100% correct within its defined envelope.
2. **No open-ended deferrals**: Comments like `// simplify: clean this up later` or `// simplify: optimize` are strictly forbidden. Always name the ceiling and upgrade path.
3. **Upgrade when telemetry alerts**: When metrics show traffic approaching 70% of the documented ceiling, trigger a planned refactoring task following the designated upgrade path.
