import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { FileLedgerStore } from "../src/ship/lifecycle/ledger.ts";
import { LifecycleEngine } from "../src/ship/lifecycle/engine.ts";
import { ConvergenceGuard } from "../src/ship/lifecycle/convergence.ts";
import { runPythonSpecialist } from "../src/ship/lifecycle/specialist_dispatcher.ts";

test("LifecycleEngine transitions across states based on ledger and tasks", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "engine-test-"));
  try {
    const engine = new LifecycleEngine();

    // 1. No active change
    let evalRes = engine.evaluateRepository(tmpDir);
    assert.equal(evalRes.gate, "design");
    assert.equal(evalRes.stateKey, "NO_ACTIVE_CHANGE");

    // 2. Pending task -> implementation
    FileLedgerStore.save(tmpDir, {
      version: 1,
      active_change_id: "chg-1",
      changes: {
        "chg-1": {
          task_status: { "1": "PENDING" },
          turns: [],
        },
      },
    });
    evalRes = engine.evaluateRepository(tmpDir);
    assert.equal(evalRes.gate, "implementation");
    assert.equal(evalRes.stateKey, "TDD_ACTIVE");

    // 3. Task completed, pending review -> review
    FileLedgerStore.save(tmpDir, {
      version: 1,
      active_change_id: "chg-1",
      changes: {
        "chg-1": {
          task_status: { "1": "COMPLETED" },
          evidence: { review: { verdict: "PENDING" } },
          turns: [],
        },
      },
    });
    evalRes = engine.evaluateRepository(tmpDir);
    assert.equal(evalRes.gate, "review");
    assert.equal(evalRes.stateKey, "REVIEW_ACTIVE");

    // 4. Review passed -> delivery
    FileLedgerStore.save(tmpDir, {
      version: 1,
      active_change_id: "chg-1",
      changes: {
        "chg-1": {
          task_status: { "1": "COMPLETED" },
          evidence: { review: { verdict: "PASSED" } },
          turns: [],
        },
      },
    });
    evalRes = engine.evaluateRepository(tmpDir);
    assert.equal(evalRes.gate, "delivery");
    assert.equal(evalRes.stateKey, "DELIVERY_READY");
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("ConvergenceGuard halts on repeat failures", () => {
  const guard = new ConvergenceGuard({ maxSameFailureCount: 2 });
  const status = guard.evaluateTurns([
    { error: "SyntaxError in foo.ts" },
    { error: "SyntaxError in foo.ts" },
  ]);
  assert.equal(status.isHalted, true);
  assert.equal(status.stagnationType, "SAME_FINDING");
});

test("runPythonSpecialist executes standard python inline", () => {
  const res = runPythonSpecialist("-c", ["import sys, json; json.dump({'ok': True}, sys.stdout)"]);
  assert.equal(res.code, 0);
  assert.deepEqual(res.data, { ok: true });
});
