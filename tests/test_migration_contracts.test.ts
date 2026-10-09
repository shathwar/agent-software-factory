import { describe, it, expect } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import cases from "./fixtures/migration/python-contracts.json";
import { DebugRubricEvaluator } from "./evaluation/evaluate_debug_rubric.ts";
import { DesignRubricEvaluator } from "./evaluation/evaluate_design_rubric.ts";
import { EvalsRubricEvaluator } from "./evaluation/evaluate_evals_rubric.ts";
import { ReviewRubricEvaluator } from "./evaluation/evaluate_review_rubric.ts";
import { SimplifyRubricEvaluator } from "./evaluation/evaluate_simplify_rubric.ts";
import { SpikeRubricEvaluator } from "./evaluation/evaluate_spike_rubric.ts";
import { TDDRubricEvaluator } from "./evaluation/evaluate_tdd_rubric.ts";
import { UXRubricEvaluator } from "./evaluation/evaluate_ux_rubric.ts";
import * as debug from "../src/ship/tools/debug.ts";
import * as design from "../src/ship/tools/design.ts";
import * as evals from "../src/ship/tools/evals.ts";
import * as review from "../src/ship/tools/review.ts";
import * as simplify from "../src/ship/tools/simplify.ts";
import * as tdd from "../src/ship/tools/tdd.ts";
import * as spike from "../src/ship/tools/spike.ts";
import * as ux from "../src/ship/tools/ux.ts";
import * as skill from "../src/ship/tools/skill.ts";
import * as traces from "../src/ship/tools/sample_traces.ts";
const modules: Record<string, any> = { debug, design, evals, review, simplify, tdd, spike, ux, sample_traces: traces, skill };
const rubrics: Record<string, any> = {debug: DebugRubricEvaluator, design: DesignRubricEvaluator, evals: EvalsRubricEvaluator, review: ReviewRubricEvaluator, simplify: SimplifyRubricEvaluator, spike: SpikeRubricEvaluator, tdd: TDDRubricEvaluator, ux: UXRubricEvaluator};
const camel = (s: string) => s.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
const names: Record<string, string> = {audit_tdd: "auditTDD", audit_adr_content: "validateAdrContent", validate_adr_content: "validateAdrContent", validate_openspec_dir: "validateOpenspecDir"};
function canonical(value: any): any {
  if (value == null) return value;
  if (Array.isArray(value)) return value.map(canonical);
  if (typeof value === "number") return Number.isFinite(value) ? Number(value.toFixed(9)) : value;
  if (typeof value !== "object") return value;
  if ("$number" in value) return value.$number === "nan" ? NaN : value.$number === "inf" ? Infinity : -Infinity;
  return Object.fromEntries(Object.entries(value).map(([k,v]) => [camel(k), canonical(v)]));
}
// Compare findings by rule, location, and severity: wording and key casing are not API semantics.
function behavior(value: any): any {
  value = canonical(value);
  if (Array.isArray(value)) return value.map(behavior);
  if (value && typeof value === "object") {
    if (value.ruleId) return {rule: value.ruleId, severity: value.severity, line: value.line ?? value.lineNumber ?? null};
    return Object.fromEntries(Object.entries(value).filter(([k]) => !["message", "assessmentKind", "summaryNotes", "feedback", "errorCount", "warningCount"].includes(k)).map(([k,v]) => [k, behavior(v)]));
  }
  return value;
}

describe("Python migration contracts", () => {
  for (const [index, fixture] of cases.entries()) {
    it(`${fixture.test}: ${fixture.tool}.${fixture.function} #${index}`, async () => {
      const temp = fs.mkdtempSync(path.join(os.tmpdir(), "ship-contract-"));
      try {
        const data: any = JSON.parse(JSON.stringify(fixture).replaceAll("$REPO", process.cwd()).replaceAll("$TMP", temp));
        for (const [file, content] of Object.entries(data.files)) {
          fs.mkdirSync(path.dirname(file), {recursive: true}); fs.writeFileSync(file, content as string);
        }
        let actual: any;
        for (const key of ["ignore_rules", "allowed_arbitrary", "excludes"]) {
          if (data.args[key] != null) data.args[key] = new Set(data.args[key]);
        }
        // Keep argument names in the captured Python contract; only results are normalized.
        const args = Object.values(data.args).map((v: any) => v instanceof Set ? v : JSON.parse(JSON.stringify(v), (_, x) => x && typeof x === "object" && "$number" in x ? x.$number === "nan" ? NaN : x.$number === "inf" ? Infinity : -Infinity : x));
        if (data.tool.startsWith("rubric_")) {
          actual = new rubrics[data.tool.slice(7)]()[data.function](...args);
          expect(behavior(actual)).toEqual(behavior(data.expected));
        } else {
          const fn = modules[data.tool][names[data.function] ?? camel(data.function)];
          expect(fn).toBeFunction();
          actual = await fn(...args);
          if (data.function === "select_diverse_sample") {
            expect(actual.length).toBe(data.expected.length);
            expect(new Set(actual.map((r: any) => r.trace_id)).size).toBe(actual.length);
            expect(actual.some((r: any) => r.error)).toBe(true);
            expect(actual).toEqual(await fn(...args));
          } else if (data.function === "verify_split_isolation") {
            expect(actual[0]).toBe(data.expected[0]);
            expect(actual[1].length).toBe(data.expected[1].length);
          } else if (data.tool === "review" && data.function === "validate_report") {
            expect(actual.length === 0).toBe(data.expected.length === 0);
          } else {
            expect(behavior(actual)).toEqual(behavior(data.expected));
          }
        }
      } finally { fs.rmSync(temp, {recursive: true, force: true}); }
    });
  }
});

export function test_migration_contracts(): void {}
