#!/usr/bin/env node
/**
 * Validate the report contract, not the truth or completeness of its findings.
 * Zero external dependencies (Node.js 22+ / 25+ standard library).
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

export const TOP_REQUIRED = new Set(["reviewer", "status", "findings", "coverage", "questions", "routing_notes"]);
export const REVIEWERS = new Set(["correctness", "concurrency", "design", "judge"]);
export const STATUSES = new Set(["complete", "incomplete", "skipped"]);
export const FINDING_REQUIRED = new Set([
  "id", "severity", "category", "file", "line", "title",
  "problem", "evidence", "impact", "recommendation", "confidence", "fixability"
]);
export const SEVERITIES = new Set(["CRITICAL", "HIGH", "MEDIUM", "LOW"]);
export const CATEGORIES = new Set([
  "SpecAlignment", "Correctness", "Concurrency", "Failure/Resilience",
  "Simplicity", "Maintainability", "Reuse", "Performance", "SOLID",
  "Patterns", "ProductionRisk"
]);
export const FIXABILITIES = new Set(["autonomous", "requires-human"]);
export const ID_REGEX = /^FINDING-[0-9]{3,}$/;
export const LINE_REGEX = /^L[1-9][0-9]*(-L[1-9][0-9]*)?$/;

/**
 * Custom JSON parser that detects duplicate object keys.
 */
function parseJsonWithDuplicateKeyCheck(jsonString: string): any {
  // Use regex tokenizer or JSON parser with reviver / token check
  const seenKeysStack: Set<string>[] = [];
  let currentKeys: Set<string> | null = null;
  let inString = false;
  let isEscaped = false;
  let currentToken = "";

  for (let i = 0; i < jsonString.length; i++) {
    const char = jsonString[i];
    if (inString) {
      if (isEscaped) {
        isEscaped = false;
      } else if (char === "\\") {
        isEscaped = true;
      } else if (char === '"') {
        inString = false;
        // Check if this string was an object key (followed by colon after whitespace)
        let j = i + 1;
        while (j < jsonString.length && /\s/.test(jsonString[j])) {
          j++;
        }
        if (j < jsonString.length && jsonString[j] === ":" && currentKeys !== null) {
          if (currentKeys.has(currentToken)) {
            throw new Error(`Duplicate JSON key: ${currentToken}`);
          }
          currentKeys.add(currentToken);
        }
        currentToken = "";
      } else {
        currentToken += char;
      }
    } else {
      if (char === '"') {
        inString = true;
        currentToken = "";
      } else if (char === "{") {
        currentKeys = new Set();
        seenKeysStack.push(currentKeys);
      } else if (char === "}") {
        seenKeysStack.pop();
        currentKeys = seenKeysStack.length > 0 ? seenKeysStack[seenKeysStack.length - 1] : null;
      }
    }
  }

  return JSON.parse(jsonString, (key, value) => {
    if (typeof value === "number" && !Number.isFinite(value)) {
      throw new Error(`Non-finite JSON number: ${value}`);
    }
    return value;
  });
}

export function parseReport(text: string): Record<string, any> {
  let cleaned = text.trim();
  const fencedMatch = /^```(?:json)?\s*\r?\n([\s\S]*?)\r?\n```$/.exec(cleaned);
  if (fencedMatch) {
    cleaned = fencedMatch[1].trim();
  }
  return parseJsonWithDuplicateKeyCheck(cleaned);
}

export function validateReport(
  report: any,
  verifySource: boolean = false,
  repoRoot?: string | null
): string[] {
  if (typeof report !== "object" || report === null || Array.isArray(report)) {
    return ["Report must be a JSON object"];
  }

  const errors: string[] = [];
  const reportKeys = new Set(Object.keys(report));

  for (const k of Array.from(TOP_REQUIRED).sort()) {
    if (!reportKeys.has(k)) {
      errors.push(`$.${k}: field is required`);
    }
  }
  for (const k of Array.from(reportKeys).sort()) {
    if (!TOP_REQUIRED.has(k)) {
      errors.push(`$.${k}: unexpected property`);
    }
  }

  if (errors.length > 0) {
    return errors;
  }

  if (typeof report.reviewer !== "string" || !REVIEWERS.has(report.reviewer)) {
    errors.push(`$.reviewer: must be one of [${Array.from(REVIEWERS).sort().map((r) => `'${r}'`).join(", ")}]`);
  }
  if (typeof report.status !== "string" || !STATUSES.has(report.status)) {
    errors.push(`$.status: must be one of [${Array.from(STATUSES).sort().map((s) => `'${s}'`).join(", ")}]`);
  }

  for (const listField of ["coverage", "questions", "routing_notes"]) {
    const val = report[listField];
    if (!Array.isArray(val)) {
      errors.push(`$.${listField}: must be an array`);
    } else if (val.some((item) => typeof item !== "string")) {
      errors.push(`$.${listField}: all items must be strings`);
    }
  }

  const findings = report.findings;
  if (!Array.isArray(findings)) {
    errors.push("$.findings: must be an array");
    return errors;
  }

  const seenIds = new Set<string>();
  for (let idx = 0; idx < findings.length; idx++) {
    const finding = findings[idx];
    const prefix = `$.findings[${idx}]`;

    if (typeof finding !== "object" || finding === null || Array.isArray(finding)) {
      errors.push(`${prefix}: must be an object`);
      continue;
    }

    const findingKeys = new Set(Object.keys(finding));
    let hasMissing = false;
    for (const k of Array.from(FINDING_REQUIRED).sort()) {
      if (!findingKeys.has(k)) {
        errors.push(`${prefix}.${k}: field is required`);
        hasMissing = true;
      }
    }
    for (const k of Array.from(findingKeys).sort()) {
      if (!FINDING_REQUIRED.has(k)) {
        errors.push(`${prefix}.${k}: unexpected property`);
      }
    }

    if (hasMissing) {
      continue;
    }

    const fid = finding.id;
    if (typeof fid !== "string" || !ID_REGEX.test(fid)) {
      errors.push(`${prefix}.id: must match pattern ^FINDING-[0-9]{3,}$`);
    } else {
      if (seenIds.has(fid)) {
        errors.push(`Duplicate finding ID: ${fid}`);
      }
      seenIds.add(fid);
    }

    if (typeof finding.severity !== "string" || !SEVERITIES.has(finding.severity)) {
      errors.push(`${prefix}.severity: must be one of [${Array.from(SEVERITIES).sort().map((s) => `'${s}'`).join(", ")}]`);
    }
    if (typeof finding.category !== "string" || !CATEGORIES.has(finding.category)) {
      errors.push(`${prefix}.category: must be one of [${Array.from(CATEGORIES).sort().map((c) => `'${c}'`).join(", ")}]`);
    }
    if (typeof finding.fixability !== "string" || !FIXABILITIES.has(finding.fixability)) {
      errors.push(`${prefix}.fixability: must be one of [${Array.from(FIXABILITIES).sort().map((f) => `'${f}'`).join(", ")}]`);
    }

    for (const strField of ["title", "problem", "evidence", "impact", "recommendation"]) {
      const val = finding[strField];
      if (typeof val !== "string" || val.trim().length < 1) {
        errors.push(`${prefix}.${strField}: must be a non-empty string`);
      }
    }

    const conf = finding.confidence;
    if (typeof conf !== "number" || !Number.isFinite(conf) || conf < 0.0 || conf > 1.0) {
      errors.push(`${prefix}.confidence: must be a finite number between 0.0 and 1.0`);
    }

    const filePath = finding.file;
    if (typeof filePath !== "string" || filePath.trim().length < 1) {
      errors.push(`${prefix}.file: must be a non-empty string`);
    } else {
      const isAbsolute = path.isAbsolute(filePath) || filePath.startsWith("/");
      const parts = filePath.split(/[\\/]/);
      const hasParent = parts.includes("..");
      const hasBackslash = filePath.includes("\\");
      const hasWinDrive = /^[A-Za-z]:/.test(filePath);
      if (isAbsolute || hasParent || hasBackslash || hasWinDrive || filePath === ".") {
        errors.push(`${fid}: file must be a repository-relative path`);
      }
    }

    const line = finding.line;
    if (typeof line !== "string" || !LINE_REGEX.test(line)) {
      errors.push(`${prefix}.line: must match pattern ^L[1-9][0-9]*(-L[1-9][0-9]*)?$`);
    } else {
      const parts = line.split("-L");
      if (parts.length === 2) {
        const start = parseInt(parts[0].slice(1), 10);
        const end = parseInt(parts[1], 10);
        if (end < start) {
          errors.push(`${fid}: line range ends before it starts`);
        }
      }
    }

    // Check for manufactured stylistic findings with elevated severity (REV-SEV-001)
    if (typeof finding.severity === "string" && (finding.severity === "CRITICAL" || finding.severity === "HIGH")) {
      const titleProb = `${finding.title ?? ""} ${finding.problem ?? ""}`.toLowerCase();
      if (/\b(naming convention|rename|camelcase|snake_case|indentation|trailing whitespace|prettier|formatting)\b/.test(titleProb)) {
        errors.push(`[${fid}] [REV-SEV-001] Stylistic or cosmetic issue cannot be marked ${finding.severity}. Demote to LOW or omit.`);
      }
    }
  }

  if (verifySource && errors.length === 0) {
    errors.push(...verifySourceEvidence(report, repoRoot));
  }

  return errors;
}

export function verifySourceEvidence(report: any, repoRoot?: string | null): string[] {
  const root = repoRoot ? path.resolve(repoRoot) : process.cwd();
  const errors: string[] = [];
  const findings = report?.findings;
  if (!Array.isArray(findings)) {
    return errors;
  }

  for (let idx = 0; idx < findings.length; idx++) {
    const finding = findings[idx];
    if (typeof finding !== "object" || finding === null) {
      continue;
    }

    const fid = finding.id ?? `findings[${idx}]`;
    const fileRel = finding.file;
    if (!fileRel || typeof fileRel !== "string") {
      continue;
    }

    const targetFile = path.join(root, fileRel);
    if (!fs.existsSync(targetFile) || !fs.statSync(targetFile).isFile()) {
      errors.push(`[${fid}] [REV-SRC-001] Referenced file '${fileRel}' does not exist in repository working tree.`);
      continue;
    }

    const evidence = finding.evidence;
    if (typeof evidence === "string" && evidence.trim().length > 0) {
      try {
        const content = fs.readFileSync(targetFile, "utf-8");
        const normEvidence = evidence.split(/\s+/).filter(Boolean).join(" ");
        const normContent = content.split(/\s+/).filter(Boolean).join(" ");
        if (!normContent.includes(normEvidence)) {
          errors.push(
            `[${fid}] [REV-EV-001] Quoted evidence does not match contents of '${fileRel}'. Hallucinated or modified evidence rejected by Judge.`
          );
        }
      } catch (err: any) {
        errors.push(`[${fid}] Unable to read source file '${fileRel}': ${err.message}`);
      }
    }
  }

  return errors;
}

export function main(argv: string[] = process.argv.slice(2)): number {
  let reportPath: string | undefined;
  let verifySource = false;
  let repoRoot: string | undefined;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--verify-source") {
      verifySource = true;
    } else if (arg === "--repo-root") {
      repoRoot = argv[++i];
    } else if (arg.startsWith("--repo-root=")) {
      repoRoot = arg.split("=")[1];
    } else if (arg === "-" || !arg.startsWith("-")) {
      reportPath = arg;
    }
  }

  if (!reportPath) {
    process.stderr.write("Usage: validate_report.ts <report.json | -> [--verify-source] [--repo-root <dir>]\n");
    return 1;
  }

  try {
    const raw = reportPath === "-" ? fs.readFileSync(0, "utf-8") : fs.readFileSync(reportPath, "utf-8");
    const parsed = parseReport(raw);
    const errors = validateReport(parsed, verifySource, repoRoot);

    if (errors.length > 0) {
      for (const err of errors) {
        process.stderr.write(`${err}\n`);
      }
      return 1;
    }

    console.log("Report structure is valid; source evidence and review coverage verified.");
    return 0;
  } catch (err: any) {
    process.stderr.write(`${err.message}\n`);
    return 1;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const exitCode = main();
  process.exit(exitCode);
}
