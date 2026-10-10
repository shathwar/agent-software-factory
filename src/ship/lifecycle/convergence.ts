import crypto from "node:crypto";

export interface ConvergenceConfig {
  maxRemediationAttempts: number;
  maxSameFailureCount: number;
  maxTotalTurns: number;
}

export interface ConvergenceStatus {
  isHalted: boolean;
  reason: string;
  stagnationType?: string | null;
}

export function hashPayload(payload: any): string {
  return crypto.createHash("sha256").update(JSON.stringify(payload ?? {})).digest("hex");
}

export class ConvergenceGuard {
  readonly config: ConvergenceConfig;
  constructor(config: Partial<ConvergenceConfig> = {}) {
    this.config = {
      maxRemediationAttempts: config.maxRemediationAttempts ?? 3,
      maxSameFailureCount: config.maxSameFailureCount ?? 2,
      maxTotalTurns: config.maxTotalTurns ?? 25,
    };
  }

  evaluateTurns(turns: any[] = []): ConvergenceStatus {
    if (turns.length >= this.config.maxTotalTurns) {
      return {
        isHalted: true,
        reason: `Exceeded maximum total turns (${turns.length} >= ${this.config.maxTotalTurns})`,
        stagnationType: "BUDGET_EXCEEDED",
      };
    }
    // Check repeating failures at tail
    if (turns.length >= this.config.maxSameFailureCount) {
      const tail = turns.slice(-this.config.maxSameFailureCount);
      const firstError = tail[0]?.error;
      if (firstError && tail.every(t => t?.error === firstError)) {
        return {
          isHalted: true,
          reason: `Repeated identical failure detected (${this.config.maxSameFailureCount} times): ${firstError}`,
          stagnationType: "SAME_FINDING",
        };
      }
    }
    return { isHalted: false, reason: "OK", stagnationType: null };
  }
}
