# Review Handbook: Security Hardening & Zero-Trust Defense

This handbook provides an adversarial checklist for auditing security vulnerabilities, data privacy risks, and attack surfaces during code reviews. Findings map to category `ProductionRisk` or `Correctness` in the 12-field finding schema.

---

## 1. Attack Surface & Injection Defenses

### SQL & Query Injection
- **Rule**: All database queries MUST use parameterized inputs or ORM binding expressions.
- **smell**: String interpolation (`f"SELECT * FROM users WHERE id = '{user_id}'"` or `"SELECT * FROM tbl WHERE " + cond`).
- **Defect Trigger**: Attacker supplies SQL metacharacters (`' OR '1'='1`) manipulating query structure.

### Command & Shell Injection
- **Rule**: Shell execution MUST pass discrete argument lists (`subprocess.run(["cmd", arg])`), never `shell=True` with concatenated strings.
- **Defect Trigger**: Untrusted user input passed into shell commands or format strings leading to arbitrary code execution.

### Cross-Site Scripting (XSS) & Template Injection
- **Rule**: Never bypass framework escaping (e.g. `dangerouslySetInnerHTML`, `v-html`, `| safe` in Jinja) without cryptographic sanitization (DOMPurify).
- **Defect Trigger**: Stored or reflected payloads executing arbitrary JavaScript in a victim's browser context.

### Server-Side Request Forgery (SSRF)
- **Rule**: Webhooks and outbound HTTP requests fetching user-supplied URLs MUST validate against private IP address ranges (RFC 1918, `127.0.0.1`, `169.254.169.254` AWS metadata).
- **Defect Trigger**: Attacker directs server to query internal microservices, cloud metadata endpoints, or local ports.

---

## 2. Authentication & Authorization Boundaries

### Broken Object-Level Authorization (BOLA / IDOR)
- **Rule**: Every resource access query MUST verify that the authenticated subject owns or is explicitly authorized for the target entity ID.
- **Smell**: `SELECT * FROM orders WHERE id = :order_id` without `AND user_id = :current_user_id` or tenant scope.

### Broken Authentication & Session Hijacking
- **Rule**: Session tokens and auth cookies MUST be marked `Secure`, `HttpOnly`, and `SameSite=Lax/Strict`. Passwords MUST use adaptive hashing algorithms (Argon2id, bcrypt) with work factors.

---

## 3. Secrets & Sensitive Data Leakage

### Hardcoded Credentials
- **Rule**: Zero credentials, API keys, private keys, or passwords committed to source files.
- **Verification**: Check `.env` handling, test fixtures, dockerfiles, and git history for leaked tokens.

### PII & Sensitive Log Masking
- **Rule**: Never log auth tokens, passwords, credit card numbers, or full user PII in application loggers or error traces.
- **Smell**: `logger.info(f"Processing request payload: {request.data}")` or logging exception context containing authorization headers.

---

## 4. Supply Chain & Dependency Auditing

### Known Vulnerability Audit
- **Rule**: Verify third-party package additions against known CVE databases before merging:
  ```bash
  # Python
  pip-audit
  # Node.js
  npm audit --production
  # Rust
  cargo audit
  ```
- **Severity**: Direct dependencies with known HIGH or CRITICAL CVEs block deployment.

---

## 5. Finding Schema Mapping

When filing security findings:
- **Category**: `ProductionRisk` (for auth/permission/data-leak bugs) or `Correctness` (for input validation/injection bugs).
- **Severity**:
  - `CRITICAL`: Remote code execution, unauthenticated data exfiltration, auth bypass, or hardcoded production credentials.
  - `HIGH`: Authenticated privilege escalation, SSRF, SQLi requiring login, or missing authorization check.
  - `MEDIUM`: Missing rate limiting, insecure cookie flags, or missing CSP headers.
