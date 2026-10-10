import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { FileLedgerStore, readLedgerFile } from "../src/ship/lifecycle/ledger.ts";
import { PolicyEngine } from "../src/ship/lifecycle/policy.ts";

test("FileLedgerStore persists and reloads state atomically", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ledger-test-"));
  try {
    const initial = FileLedgerStore.load(tmpDir);
    assert.equal(initial.version, 1);
    assert.equal(initial.active_change_id, null);

    FileLedgerStore.save(tmpDir, {
      version: 1,
      active_change_id: "test-feature",
      changes: {
        "test-feature": {
          task_status: { "1": "COMPLETED" },
          blockers: [],
          turns: [],
        },
      },
    });

    const active = FileLedgerStore.getActiveChange(tmpDir);
    assert.equal(active, "test-feature");

    const reloaded = FileLedgerStore.load(tmpDir);
    assert.equal(reloaded.changes["test-feature"].task_status["1"], "COMPLETED");
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("PolicyEngine enforces allowed tools and approvals", () => {
  const engine = new PolicyEngine({
    allowed: { tools: ["tdd", "simplify"] },
    requires_approval: { commit: true },
    forbidden: { force_push: true },
  });

  assert.equal(engine.evaluateTool("tdd").status, "ALLOWED");
  assert.equal(engine.evaluateTool("debug").status, "DENIED");
  assert.equal(engine.evaluateAction("commit").status, "REQUIRES_APPROVAL");
  assert.equal(engine.evaluateAction("force_push").status, "DENIED");
});
