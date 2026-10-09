/** Explicit JSON boundary for the Python lifecycle host. Never accepts module paths or code. */
import fs from "node:fs";
import path from "node:path";
import { verifyTDD, trimTestReceipt, isTestFile, isProductionCode } from "./tdd.ts";
import { scanDebt, formatTable } from "./simplify.ts";
import { runBenchmark, formatMarkdownTable } from "./spike.ts";
import { parseReport, validateReport } from "./review.ts";
import { auditPath } from "./ux.ts";

function snakeKeys(value: any): any {
  if (Array.isArray(value)) return value.map(snakeKeys);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k,v]) => [k.replace(/[A-Z]/g, c => `_${c.toLowerCase()}`), snakeKeys(v)]));
  return value;
}
export async function dispatch(action: string, args: any): Promise<any> {
  switch (action) {
    case "classify": return {is_test: isTestFile(args.path), is_production: isProductionCode(args.path)};
    case "tdd": return args.trim_receipt ? {trimmed_receipt: trimTestReceipt(args.trim_receipt)} : snakeKeys(verifyTDD(args.ref_range, args.files, args.path, !!args.strict));
    case "simplify": {
      const paths = args.paths?.map((p: string) => path.resolve(args.path ?? ".", p)) ?? [path.resolve(args.path ?? ".")];
      const [markers, errors] = scanDebt(paths, !!args.strict);
      return {passed: !errors, total_markers: markers.length, markers: snakeKeys(markers), table: formatTable(markers, true)};
    }
    case "spike": {
      const summary = await runBenchmark({cmd: args.command, iterations: args.iterations ?? 10, concurrency: args.concurrency ?? 1, warmup: args.warmup ?? 0, timeoutSec: args.timeout_sec ?? 60, cwd: args.path});
      const [table, passed] = formatMarkdownTable(summary);
      return {summary, table, passed};
    }
    case "review": {
      const report = args.report_text !== undefined ? parseReport(args.report_text) : args.report_data;
      const errors = validateReport(report, !!args.verify_source, args.repo_root);
      return {valid: errors.length === 0, errors};
    }
    case "ux": return auditPath(args.path, new Set(args.ignore_rules ?? []), new Set(args.allowed_arbitrary ?? []));
    default: throw new Error(`Unknown specialist action: ${action}`);
  }
}
if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    const request = JSON.parse(fs.readFileSync(0, "utf8"));
    console.log(JSON.stringify({result: await dispatch(request.action, request.args ?? {})}));
  } catch (error: any) {
    console.log(JSON.stringify({error: error.message})); process.exitCode = 1;
  }
}
