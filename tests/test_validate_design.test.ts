import test, { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import {
  validateAdrContent,
  validateOpenspecDir,
  validateInterviewRound,
  validateConfirmationGate,
  FrontierDAG,
  validateRepository,
  main,
} from "../src/ship/tools/design.ts";

const SCRIPT_PATH = path.resolve("src/ship/tools/design.ts");

const VALID_CANONICAL_ADR = `# ADR-0001: Distributed Order Execution Engine

- **Status**: ACCEPTED
- **Date**: 2026-10-06
- **Architects**: User & Principal Systems Architect
- **Target Components**: OrderExecutionService, Postgres, RedisStreams
- **Related Issues / PRDs**: #101

---

## 1. Context & Problem Statement
Order processing currently experiences database lock contention under burst flash-sales.
We need an event-driven decoupled architecture with strict order execution invariants.

---

## 2. Decision Drivers
- Driver 1: Sub-15ms p99 execution latency
- Driver 2: 5,000 TPS concurrent write capability
- Driver 3: Zero double-spend or duplicate order execution

---

## 3. Considered Options

### Option A: Synchronous Two-Phase Commit across Postgres shards
- **Pros**: Strong immediate consistency
- **Cons**: High latency, brittle availability

### Option B: Transactional Outbox with Redis Streams Partitioning *(Chosen)*
- **Pros**: High throughput, isolated failure domains
- **Cons**: Requires consumer deduplication and eventual consistency

---

## 4. Decision Outcome & Architecture Specification

### 4.1. Chosen Architecture
We will use Postgres transactional outbox combined with Redis Streams consumer groups partitioned by customer_id.

### 4.2. Invariants & Guarantees
- **State & Consistency**: Outbox events committed atomically with aggregate mutation in single database transaction.
- **Concurrency**: Consumer groups enforce serial per-partition ordering.
- **Resilience**: Dead-letter queues for unparseable poison messages.
- **Data & Migration**: Dual-write period with shadow reads during rollout.
- **Blast Radius**: Isolation per partition key.

---

## 5. Consequences & Trade-offs
- **Positive Consequences**: Orders unblock with async throughput.
- **Negative Consequences**: Consumers must deduplicate messages.

---

## 6. Downstream Verification Criteria (For review)
- [ ] Verify outbox event record inserted in same transaction.
- [ ] Stress test partition rebalancing under consumer crash.
`;

describe("TypeScript Systems Design Validator (validate_design.ts)", () => {
  it("validates a canonical ADR", () => {
    const res = validateAdrContent(VALID_CANONICAL_ADR, "ADR-0001.md");
    assert.equal(res.passed, true);
    assert.equal(res.errors.length, 0);
  });

  it("detects missing ADR required sections", () => {
    const invalidAdr = `# Bad ADR
- **Status**: UNKNOWN
- **Date**: invalid-date
## 1. Context
Some context.
`;
    const res = validateAdrContent(invalidAdr, "BAD-ADR.md");
    assert.equal(res.passed, false);
    const ruleIds = res.errors.map((e) => e.rule_id);
    assert.ok(ruleIds.includes("DES-ADR-001"));
    assert.ok(ruleIds.includes("DES-ADR-002"));
    assert.ok(ruleIds.includes("DES-ADR-003"));
    assert.ok(ruleIds.includes("DES-ADR-006"));
    assert.ok(ruleIds.includes("DES-ADR-008"));
    assert.ok(ruleIds.includes("DES-ADR-011"));
  });

  it("validates an OpenSpec change package", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "design-openspec-"));
    try {
      // 1. proposal.md
      fs.writeFileSync(
        path.join(tmpDir, "proposal.md"),
        "# Proposal\n## Problem Statement\nLocks.\n## Proposed Changes\nOutbox.\n## Capabilities\nAdded.\n## Non-Goals\nNone.\n"
      );

      // 2. specs/
      const specsDir = path.join(tmpDir, "specs");
      fs.mkdirSync(specsDir);
      fs.writeFileSync(
        path.join(specsDir, "orders.md"),
        "# Spec\nThe service SHALL process orders. GIVEN order WHEN placed THEN committed.\nRole Access Matrix: Admin.\n"
      );

      // 3. design.md
      fs.writeFileSync(
        path.join(tmpDir, "design.md"),
        "# Design\nSystem Invariants & Guarantees documented here.\n"
      );

      // 4. tasks.md
      fs.writeFileSync(
        path.join(tmpDir, "tasks.md"),
        "# Tasks\n- [ ] Task 1: Create outbox table\n- [x] Task 2: Implement publisher\n"
      );

      const res = validateOpenspecDir(tmpDir);
      assert.equal(res.passed, true);
      assert.equal(res.errors.length, 0);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("validates interview rounds and rejects vacuous stances", () => {
    const goodRound = `### 🏛️ Round 1 — Design Frontier
❓ **Q1** - **Event Broker Selection**:
Should we use Kafka or Redis Streams?
➡️ **Recommended Stance**: We recommend Redis Streams because existing operations already maintain Redis clusters and throughput requirements are below 50k RPS.
`;
    const resGood = validateInterviewRound(goodRound);
    assert.equal(resGood.passed, true);

    const vacuousRound = `### 🏛️ Round 1 — Design Frontier
❓ **Q1** - **Event Broker Selection**:
Should we use Kafka or Redis Streams?
➡️ **Recommended Stance**: Up to the team whatever you prefer.
`;
    const resVacuous = validateInterviewRound(vacuousRound);
    assert.equal(resVacuous.passed, false);
    assert.ok(resVacuous.errors.some((e) => e.rule_id === "DES-FNT-005"));
  });

  it("enforces confirmation gate against premature spec mutations", () => {
    const prompt = "Please confirm this design frontier before we proceed.";
    const badFiles = ["docs/adr/ADR-0001.md", "src/calc.ts"];
    const resBad = validateConfirmationGate(prompt, badFiles);
    assert.equal(resBad.passed, false);
    assert.ok(resBad.errors.some((e) => e.rule_id === "DES-GATE-001"));

    const goodFiles = ["src/calc.ts"];
    const resGood = validateConfirmationGate(prompt, goodFiles);
    assert.equal(resGood.passed, true);
  });

  it("manages FrontierDAG dependencies and frontier sets", () => {
    const dag = new FrontierDAG();
    dag.addDecision("D1", "Storage Engine");
    dag.addDecision("D2", "Partition Scheme", ["D1"]);
    dag.addDecision("D3", "Cache Layer", ["D1"]);

    let frontier = dag.getFrontier();
    assert.equal(frontier.length, 1);
    assert.equal(frontier[0].id, "D1");

    dag.resolve("D1", "Postgres");
    frontier = dag.getFrontier();
    assert.equal(frontier.length, 2);
    const ids = frontier.map((d: any) => d.id).sort();
    assert.deepEqual(ids, ["D2", "D3"]);

    dag.resolve("D2", "Hash");
    dag.resolve("D3", "Redis");
    assert.equal(dag.isComplete(), true);
    assert.equal(dag.getFrontier().length, 0);
  });

  it("runs CLI on valid ADR and JSON output mode", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "design-cli-"));
    try {
      const adrFile = path.join(tmpDir, "ADR-0001.md");
      fs.writeFileSync(adrFile, VALID_CANONICAL_ADR);

      const stdout = execFileSync(
        process.execPath,
        [SCRIPT_PATH, "--adr", adrFile, "--json"],
        { encoding: "utf-8" }
      );
      const parsed = JSON.parse(stdout);
      assert.equal(parsed.passed, true);
      assert.equal(parsed.error_count, 0);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
