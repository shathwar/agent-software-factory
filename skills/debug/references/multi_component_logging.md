# Multi-Component Boundary Instrumentation

How to debug complex, multi-tiered systems (CLI $\rightarrow$ API $\rightarrow$ Worker $\rightarrow$ Database) without guessing.

---

## 1. The Boundary Logging Mandate

When an error spans multiple layers, processes, or asynchronous queues, guessing which component failed leads to shotgun changes across the entire codebase.

**Before modifying code or proposing fixes:**
Add temporary diagnostic instrumentation at **each component boundary**:

```text
[Boundary 1: Input / CLI] ──▶ Log payload entering layer
         │
         ▼
[Boundary 2: Service / API] ──▶ Log deserialized parameters & auth context
         │
         ▼
[Boundary 3: Queue / Worker] ──▶ Log message popped & environment vars
         │
         ▼
[Boundary 4: Persistence / DB] ──▶ Log exact query & execution return
```

---

## 2. Evidence Collection Protocol

1. **Add Boundary Probes**: Log entry data, exit data, and environment state at each layer interface.
2. **Execute Single Run**: Run the reproduction scenario exactly once to capture the full trace.
3. **Pinpoint the Failing Boundary**:
   - Boundary 1: payload valid ✓
   - Boundary 2: parameters valid ✓
   - Boundary 3: worker environment variable missing or empty ✗
4. **Isolate Investigation**: Focus investigation exclusively on the single component that failed to propagate state across its boundary.
5. **Clean Up Probes**: Remove temporary diagnostic logging once the root cause is confirmed and fixed.
