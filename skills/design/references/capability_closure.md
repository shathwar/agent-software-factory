# Capability Closure Checklists

Specifications written by AI agents frequently suffer from "happy path myopia"—they detail how to create and read an entity, but forget state transitions, deletion semantics, role-based authorization, subsystem integrations, or implicit user expectations.

Before confirming an architectural specification or OpenSpec change package, the Principal Architect must execute the **Four Capability Closure Checklists**.

---

## 1. Entity Closure (Lifecycle & Surface Completeness)

For **every entity** introduced or modified by the feature, verify its full operational lifecycle across all three architectural surfaces:

| Entity Lifecycle Operation | UI Entry Point | API Surface | Automated Behavioral Test | Explicit Exemption (`n/a`) |
|---|---|---|---|---|
| **Create** | Form / modal / button | `POST /api/...` | Behavioral creation test | `n/a: <reason>` |
| **Read (Detail)** | View page / drawer | `GET /api/.../:id` | Detail query test | `n/a: <reason>` |
| **Read (List / Filter)** | Table / search bar | `GET /api/...` (paged) | Pagination & filter test | `n/a: <reason>` |
| **Update** | Edit form / inline edit | `PUT / PATCH /api/...` | Mutation & validation test | `n/a: <reason>` |
| **Delete / Archive** | Delete button + confirm | `DELETE /api/...` | Soft/hard delete test | `n/a: <reason>` |
| **State Transitions** | Action buttons | `POST /api/.../transition` | State machine invariant test | `n/a: <reason>` |

> [!IMPORTANT]
> Every cell in this matrix must either be explicitly designed or marked with an intentional `n/a: <justification>`. No operation may be omitted by accident.

---

## 2. Integration Closure (Subsystem Reconciliation)

Reconcile the feature against every foundational subsystem present in the repository (e.g. from `docs/CAPABILITIES.md` or existing architecture):

| Subsystem | Integration Requirement | Status / Resolution |
|---|---|---|
| **Authentication** | Session validation, token expiration, anonymous fallback | Explicitly defined |
| **Authorization / RBAC** | Tenant boundaries, resource ownership, permission checks | Explicitly defined |
| **Navigation & Routing** | Breadcrumbs, sidebar links, deep linking, 404 handling | Explicitly defined |
| **Notifications** | In-app toasts, emails, webhooks, or push notifications | In-scope or `n/a` |
| **Audit Logging** | Security-sensitive mutations recorded with actor ID and timestamp | In-scope or `n/a` |
| **Observability** | Metrics counters, error traces, structured log context | In-scope or `n/a` |

---

## 3. Role Matrix (Explicit Access Control)

Enumerate every user persona or system role and explicitly state authorization for each capability:

```markdown
### Role Access Matrix
| Capability / Action | Admin | Manager | Standard User | Anonymous / Guest |
|---|:---:|:---:|:---:|:---:|
| View Resource List | ALLOW | ALLOW | ALLOW | DENY |
| Create Resource | ALLOW | ALLOW | ALLOW (Rate-limited) | DENY |
| Modify Resource | ALLOW | ALLOW (Tenant) | ALLOW (Owner only) | DENY |
| Delete Resource | ALLOW | DENY | DENY | DENY |
```

---

## 4. Expectation Sweep (Implicit Domain Assumptions)

Force at least **10 implicit domain expectations** into explicit categories: `IN-SCOPE`, `OUT-OF-SCOPE`, or `DEFERRED`. Never leave domain assumptions unspoken:

- *Example*:
  1. *"Draft saving before publish"* ➔ `OUT-OF-SCOPE (v1)`
  2. *"Idempotent retry on duplicate submission"* ➔ `IN-SCOPE`
  3. *"Soft deletion with 30-day recovery"* ➔ `DEFERRED (v2)`
  4. *"Bulk export to CSV"* ➔ `OUT-OF-SCOPE`
  5. *"Concurrent edit conflict detection (optimistic locking)"* ➔ `IN-SCOPE`
