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
