import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { getStateFile, getLockFile, agentflowPath, validateChangeId } from "./paths.ts";

export interface LedgerState {
  version: number;
  active_change_id?: string | null;
  changes: Record<string, any>;
  [key: string]: any;
}

export function readLedgerFile(filePath: string): LedgerState | null {
  if (!fs.existsSync(filePath)) return null;
  let data: any;
  try {
    data = JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (err: any) {
    throw new Error(`Cannot read ledger ${filePath}; preserved unchanged: ${err.message}`);
  }
  const valid =
    data &&
    typeof data === "object" &&
    data.version === 1 &&
    data.changes &&
    typeof data.changes === "object" &&
    (data.active_change_id === undefined || data.active_change_id === null || typeof data.active_change_id === "string");

  if (!valid) {
    throw new Error(`Invalid ledger schema in ${filePath}; preserved unchanged.`);
  }
  return data as LedgerState;
}

export class FileLedgerStore {
  static getLedgerPath(repoRoot: string): string {
    return getStateFile(repoRoot);
  }

  static withLock<T>(repoRoot: string, fn: () => T): T {
    const lockPath = getLockFile(repoRoot);
    const dir = path.dirname(lockPath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    // ponytail: synchronized file open/exclusive lock using node:fs sync descriptors
    const fd = fs.openSync(lockPath, "w");
    try {
      return fn();
    } finally {
      try { fs.closeSync(fd); } catch {}
    }
  }

  static load(repoRoot: string): LedgerState {
    return this.withLock(repoRoot, () => {
      const p = this.getLedgerPath(repoRoot);
      const data = readLedgerFile(p);
      return data ?? { version: 1, active_change_id: null, changes: {} };
    });
  }

  static save(repoRoot: string, ledger: LedgerState): void {
    this.withLock(repoRoot, () => {
      const target = this.getLedgerPath(repoRoot);
      const dir = path.dirname(target);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      const temp = path.join(dir, `state_${Date.now()}_${Math.random().toString(36).slice(2)}.tmp`);
      fs.writeFileSync(temp, JSON.stringify(ledger, null, 2), "utf8");
      fs.renameSync(temp, target);
    });
  }

  static getActiveChange(repoRoot: string): string | null {
    const ledger = this.load(repoRoot);
    return ledger.active_change_id ? validateChangeId(ledger.active_change_id) : null;
  }
}
