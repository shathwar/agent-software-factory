import fs from "node:fs";
import path from "node:path";
import { FileLedgerStore, type LedgerState } from "./ledger.ts";
import { ConvergenceGuard, type ConvergenceStatus } from "./convergence.ts";
import { PolicyEngine } from "./policy.ts";

export type LifecycleGate = "design" | "spike" | "implementation" | "review" | "delivery" | "convergence";

export interface LifecycleEvaluation {
  gate: LifecycleGate;
  stateKey: string;
  nextAction: string;
  activeChangeId?: string | null;
  convergence?: ConvergenceStatus;
}

export class LifecycleEngine {
  readonly convergence: ConvergenceGuard;
  readonly policy: PolicyEngine;

  constructor(policyEngine?: PolicyEngine, convergenceGuard?: ConvergenceGuard) {
    this.policy = policyEngine ?? new PolicyEngine();
    this.convergence = convergenceGuard ?? new ConvergenceGuard();
  }

  evaluateRepository(repoRoot: string, targetChange?: string): LifecycleEvaluation {
    const ledger = FileLedgerStore.load(repoRoot);
    const activeId = targetChange || ledger.active_change_id || Object.keys(ledger.changes || {})[0] || null;

    if (!activeId) {
      return {
        gate: "design",
        stateKey: "NO_ACTIVE_CHANGE",
        nextAction: "Initialize an active change or proposal in openspec/changes/ or via 'ship init <id>'",
        activeChangeId: null,
      };
    }

    const change = ledger.changes[activeId] ?? {};
    const turns = change.turns || [];
    const convStatus = this.convergence.evaluateTurns(turns);
    if (convStatus.isHalted) {
      return {
        gate: "convergence",
        stateKey: "AUTONOMY_HALTED",
        nextAction: `Convergence halt: ${convStatus.reason}. Address failure or reset turn limit.`,
        activeChangeId: activeId,
        convergence: convStatus,
      };
    }

    const tasks = change.task_status || {};
    const pendingTasks = Object.entries(tasks).filter(([_, status]) => status !== "COMPLETED");
    if (pendingTasks.length > 0) {
      return {
        gate: "implementation",
        stateKey: "TDD_ACTIVE",
        nextAction: `Execute pending implementation tasks (${pendingTasks.length} remaining). Next: Task ${pendingTasks[0][0]}.`,
        activeChangeId: activeId,
        convergence: convStatus,
      };
    }

    const reviewEv = change.evidence?.review || {};
    if (!reviewEv.verdict || reviewEv.verdict === "PENDING") {
      return {
        gate: "review",
        stateKey: "REVIEW_ACTIVE",
        nextAction: "Execute adversarial code review and record verdict.",
        activeChangeId: activeId,
        convergence: convStatus,
      };
    }

    return {
      gate: "delivery",
      stateKey: "DELIVERY_READY",
      nextAction: "All lifecycle gates passed. Ready for deployment / merge.",
      activeChangeId: activeId,
      convergence: convStatus,
    };
  }
}
