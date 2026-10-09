# Dimension-Based Synthetic Data Generation

How to bootstrap high-coverage eval datasets before having production traffic, without producing uniform or repetitive samples.

---

## 1. The Dimension Tuple Framework

Do not ask an LLM to "Generate 50 realistic user queries." LLMs default to modal, homogeneous outputs.

Instead, define the **variation dimensions** of your problem space and compute a sparse Cartesian product:

### Example: Customer Support Email Agent
- **Dimension A: User Persona**
  - Impatient Executive, Tech-Savvy Developer, Frustrated Elderly User, Procurement Officer
- **Dimension B: Product Category**
  - Billing & Invoices, SSO / SAML Integration, Data Export, Rate Limits
- **Dimension C: Query Complexity**
  - Simple 1-liner, Multi-part ambiguous query, Query with conflicting constraints
- **Dimension D: Adversarial Tone / Edge Case**
  - Heavy typos/caps, SQL injection attempt, Out-of-scope refund demand

---

## 2. Generation Workflow

1. **Cartesian Sampling**: Pick diverse tuples (e.g., `(Frustrated Elderly User, Billing, Multi-part, Heavy typos)`).
2. **Conditional Prompting**: Feed the exact tuple to the generator model with instructions to embody that specific profile.
3. **Deduplication & Diversity Verification**:
   - Filter identical intents.
   - Run character length and token distribution checks.
4. **Execution**: Pass synthetic queries through your AI pipeline to generate candidate traces.
5. **Bootstrap Review**: Feed the resulting traces into the Error Discovery workflow (`scripts/serve_review_app.ts`) to discover initial failure modes before real users ever hit the product.
