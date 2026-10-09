# Claude Model, Effort & Tool Selection Guide

## Overview

Anthropic's Claude models provide distinct trade-offs across capability, latency, context processing, and cost. This guide outlines how to systematically select the model, reasoning effort, and tool capabilities for any engineering task.

---

## 1. Model Profiles

### Claude 3.5 Haiku
- **Context Window**: 200k tokens
- **Pricing**: \$0.80 / MTok Input, \$4.00 / MTok Output, \$0.08 / MTok Cache Read
- **Latency**: Ultra-low (<1s typical TTFT)
- **Strengths**: Lightweight logic, regex matching, log parsing, token classification, fast text generation
- **Recommended Tasks**:
  - Mechanical refactoring (renames, formatting, import sorting)
  - Broad repository grep/search filtering
  - Commit message generation and PR template scaffolding
  - Quick documentation lookups

### Claude 3.7 Sonnet / Claude 3.5 Sonnet
- **Context Window**: 200k tokens
- **Pricing**: \$3.00 / MTok Input, \$15.00 / MTok Output, \$0.30 / MTok Cache Read
- **Latency**: Interactive (~1.5s - 3s)
- **Strengths**: Code generation, architectural analysis, refactoring, systems debugging, test-driven development
- **Recommended Tasks**:
  - Full-stack feature development
  - Test-Driven Development (TDD Red-Green-Refactor)
  - Complex bug root-cause analysis and surgical repairs
  - Adversarial code review (10-stage review hierarchy)
  - Architecture Decision Records (ADRs) and OpenSpec packages

### Claude 3 Opus
- **Context Window**: 200k tokens
- **Pricing**: \$15.00 / MTok Input, \$75.00 / MTok Output, \$1.50 / MTok Cache Read
- **Latency**: Deliberate (~4s - 8s)
- **Strengths**: Deep reasoning, abstract conceptual synthesis, complex mathematical proofs, high ambiguity
- **Recommended Tasks**:
  - Novel protocol and consensus architecture
  - Multi-stakeholder conflict resolution in system specs
  - Highly non-linear algorithmic proofs

---

## 2. Reasoning Effort Calibration

Claude 3.7+ supports adjustable reasoning depth. Use these guidelines:

| Effort | Reasoning Steps | When to Apply | Expected Latency Overhead |
|---|---|---|---|
| **`low`** | 1–3 internal thoughts | Deterministic scripts, templated code, formatting, simple lookups | Negligible |
| **`medium`** | 4–8 internal thoughts | Single-system features, standard unit tests, straightforward bugfixes | +1–2s |
| **`high`** | 9–20 internal thoughts | Concurrency, distributed invariants, multi-file TDD, deep code review | +3–6s |
| **`max`** | 20+ internal thoughts | Cryptographic invariants, kernel/compiler fixes, zero-defect systems | +7–15s |

---

## 3. Tool Sandboxing Matrix

Limit Claude's tool exposure to enforce security and prevent unwanted side-effects:

| Profile | Tools | Use Case |
|---|---|---|
| **Read-Only** | `Read`, `Glob`, `Grep` | Code review, security auditing, initial architecture exploration |
| **Non-Shell Dev** | `Read`, `Edit`, `Write`, `Glob`, `Grep` | Surgical code repairs where terminal execution is untrusted or unneeded |
| **Full SDLC** | `Read`, `Edit`, `Write`, `Bash`, `Glob`, `Grep` | Standard development lifecycle requiring test execution and build verification |
| **Diagnostic** | `Read`, `Bash`, `Glob`, `Grep` | Running test suites and benchmarks without mutating files |
