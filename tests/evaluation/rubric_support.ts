import fs from "node:fs";
import path from "node:path";

export interface RubricScore { name: string; weight: number; score: number; feedback: string[] }
export interface RubricReport {
  target_name: string; overall_score: number; passed: boolean; status: string;
  domain_scores: Record<string, RubricScore>; summary_notes: string[];
}
// Preserve empty-collection and numeric semantics of the original rubric contracts.
export function size(value: any): number {
  return value instanceof Set ? value.size : typeof value === "object" && !Array.isArray(value) ? Object.keys(value).length : value.length;
}
export function truth(value: any): boolean {
  if (value == null || value === false || value === 0 || value === "") return false;
  return typeof value === "object" ? size(value) > 0 : true;
}
export function contains(container: any, value: any): boolean {
  return container instanceof Set ? container.has(value) : typeof container === "string" || Array.isArray(container) ? container.includes(value) : Object.hasOwn(container, value);
}
export const str = "string", int = "number", float = "number", dict = "object", list = "array";
export function valueType(value: any): string { return Array.isArray(value) ? list : typeof value; }
export function isType(value: any, type: string): boolean { return value !== null && valueType(value) === type; }
export function round(value: number, digits = 0): number { return Number(value.toFixed(digits)); }
export const re = { IGNORECASE: 1, MULTILINE: 2, DOTALL: 4 };
function regex(pattern: string, flags = 0, global = false): RegExp {
  return new RegExp(pattern, `${flags & 1 ? "i" : ""}${flags & 2 ? "m" : ""}${flags & 4 ? "s" : ""}${global ? "g" : ""}`);
}
export const rx = {
  search: (pattern: string, text: string, flags = 0) => regex(pattern, flags).exec(text),
  match: (pattern: string, text: string, flags = 0) => regex(`^(?:${pattern})`, flags).exec(text),
  findall: (pattern: string, text: string, flags = 0) => [...text.matchAll(regex(pattern, flags, true))].map(m => m.length === 1 ? m[0] : m.length === 2 ? m[1] : m.slice(1)),
  escape: (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
};
export function checkGrounding(report: any, repoRoot?: string): string[] {
  if (repoRoot == null) return [];
  const root = fs.realpathSync(repoRoot), errors: string[] = [];
  for (const finding of report.findings) {
    const file = path.resolve(root, finding.file);
    let actual: string;
    try { actual = fs.realpathSync(file); } catch { actual = ""; }
    if (!actual || path.relative(root, actual).startsWith("..") || !fs.statSync(actual).isFile()) {
      errors.push("Referenced source is missing or outside the repository."); continue;
    }
    const lines = fs.readFileSync(actual, "utf8").split(/\r?\n/);
    const [start, last] = finding.line.replaceAll("L", "").split("-").map(Number);
    const end = last ?? start;
    const normalized = (text: string) => text.trim().split(/\s+/).join(" ");
    if (end > lines.length || !normalized(lines.slice(start - 1, end).join("\n")).includes(normalized(finding.evidence))) errors.push("Evidence does not occur in the cited line range.");
  }
  return errors;
}
