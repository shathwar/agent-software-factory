# The Laziness Ladder & Stdlib Playbook

A practical handbook on avoiding dependencies, eliminating speculative abstractions, and leveraging modern language standard libraries.

---

## 1. The 7 Rungs in Practice

```text
1. YAGNI (Skip it)
2. Existing Codebase Helper (Reuse it)
3. Standard Library (Native runtime)
4. Platform Feature (Browser/OS/Database)
5. Already-Installed Dependency (No new package)
6. One-Liner (Keep it tiny)
7. Minimum Code That Works (Surgical diff)
```

### Contrast Pairs (Bad vs Good)

```typescript
// ❌ BAD: Speculative abstraction with single implementation (Rung 1 violation)
interface IUserRepository { findById(id: string): Promise<User>; }
class UserRepositoryFactory { static create(): IUserRepository { return new SqlUserRepository(); } }
const repo = UserRepositoryFactory.create();

// ✅ GOOD: Direct concrete class; introduce interface ONLY when 2nd impl arrives
class UserRepository { async findById(id: string): Promise<User> { ... } }
```

```typescript
// ❌ BAD: Installing external dependency for built-in feature (Rung 3 violation)
import cloneDeep from 'lodash.clonedeep';
import { v4 as uuidv4 } from 'uuid';
const copy = cloneDeep(data);
const id = uuidv4();

// ✅ GOOD: Native platform stdlib primitives
const copy = structuredClone(data);
const id = crypto.randomUUID();
```

```python
# ❌ BAD: Patching multiple callsites defensively with null checks (Rung 7 violation)
# caller1.py: if user and user.email: send(user.email)
# caller2.py: if user and user.email: notify(user.email)

# ✅ GOOD: Fix once at the root function entrypoint
def send(email: str | None) -> None:
    if not email: return
    ...
```

---

## 2. Stdlib & Platform Replacements by Ecosystem

### Modern JavaScript / Node.js (Node 20+)

| Over-Engineered Third-Party Package | Modern Built-in / Native Stdlib Replacement |
|---|---|
| `uuid` | `crypto.randomUUID()` |
| `axios`, `node-fetch`, `request` | Global `fetch()` |
| `lodash.clonedeep` | Global `structuredClone()` |
| `mkdirp`, `rimraf` | `fs.promises.mkdir(dir, { recursive: true })`<br>`fs.promises.rm(dir, { recursive: true, force: true })` |
| `dotenv` | Native Node 20+ flag: `node --env-file=.env` |
| `date-fns` (for basic formatting) | `Intl.DateTimeFormat` |
| Custom event emitter | `EventTarget` (global in Node 16+) |
| `chalk` (for basic terminal colors) | Node 21+ `util.styleText('green', text)` |

### Python 3.10+

| Over-Engineered Dependency / Custom Class | Modern Built-in Replacement |
|---|---|
| `pytz` | `zoneinfo.ZoneInfo` (standard in Python 3.9+) |
| `requests` (for a single GET/POST in a script) | `urllib.request.urlopen()` |
| Custom getter/setter boilerplate | `@dataclass(slots=True)` |
| Custom caching logic | `@functools.lru_cache(maxsize=128)` |
| Complex string concatenation | f-strings |
| Manual file path string manipulation | `pathlib.Path` |
| Manual enum or constant tables | `enum.StrEnum` (Python 3.11+) |

### Go (Go 1.21+)

| Third-Party Library | Modern Built-in Replacement |
|---|---|
| `gorilla/mux` (for basic URL routing) | Modern `net/http.ServeMux` (Go 1.22+ supports `GET /path/{id}`) |
| `golang.org/x/exp/slices` | Built-in `slices` package |
| `golang.org/x/exp/maps` | Built-in `maps` package |
| Custom min/max helpers | Built-in `min()` and `max()` functions |

---

## 3. Native Platform Replacements

### HTML & Web Platform
- **Date Pickers**: Use `<input type="date">` instead of heavy 80KB React datepicker libraries.
- **Dialogs & Modals**: Use the native `<dialog>` element with `.showModal()` instead of portal abstractions and custom backdrop click listeners.
- **Accordion / Expandable Sections**: Use `<details>` and `<summary>` elements instead of JS state machines.
- **Form Validation**: Use HTML5 `required`, `pattern`, `minlength`, `type="email"` before writing custom regex validators in JavaScript.

### Databases & Storage
- **Uniqueness checks**: Use a `UNIQUE` index constraint instead of running a `SELECT count(*)` query before every `INSERT` (which has race conditions anyway).
- **Cascade deletions**: Use `ON DELETE CASCADE` foreign keys instead of multi-step application cleanup logic.
- **Timestamps**: Use `DEFAULT CURRENT_TIMESTAMP` instead of injecting application clock timestamps.

---

## 4. Root-Cause Bug Fixing Protocol

When a bug report arrives with a stack trace:
1. **Locate the failing call site**: Identify the exact function and parameter.
2. **Do NOT patch just the caller**: Adding an `if (param == null) return;` at the caller leaves every other caller vulnerable.
3. **Grep for all callers**:
   ```bash
   git grep -n "functionName("
   ```
4. **Fix at the shared root**:
   - Normalize the input at the entrance of the shared function.
   - One guard in one shared function protects all current and future callers with the minimal possible git diff.

---

## 5. Ousterhout's Complexity Reducers (A Philosophy of Software Design)

### 1. Deep Modules vs. Shallow Wrappers
- **Deep Module**: A simple, narrow interface that hides substantial implementation complexity (e.g. Unix file I/O: `open`, `read`, `write`, `close` hiding block allocators, caching, drivers).
- **Shallow Module**: An interface that is relatively large compared to the functionality it provides. A 5-line wrapper class that merely maps DTO fields or passes calls to a service without transformation adds indirection without reducing cognitive load. **Never introduce a shallow wrapper.**

### 2. Define Errors Out of Existence
The best way to reduce code and complexity is to eliminate error cases entirely:
- **Make Boundary Conditions Valid**: Instead of throwing exceptions for edge cases, define the method semantics so that boundaries are normal outcomes:
  - Deleting an unreferenced ID $\rightarrow$ idempotent success (not `404 Not Found` or `ItemNotFoundException`).
  - Slicing past the end of a string or array $\rightarrow$ return empty result (like Python `s[100:]`), not `IndexOutOfBoundsException`.
  - Unsubscribing a non-listener $\rightarrow$ silent no-op, not an error.
- **Benefit**: Callers do not need `try/catch` or defensive guards, reducing boilerplate across the entire codebase.
