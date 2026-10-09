#!/usr/bin/env node
/**
 * Scan codebases for simplify: technical debt markers and validate syntax.
 *
 * Zero external dependencies (Node.js 22+ / 25+ standard library).
 *
 * Valid Syntax:
 *     // simplify: <Shortcut>. Ceiling: <Threshold/Limit>. Upgrade: <Next Architecture>.
 */

import fs from "node:fs";
import { pythonSource, pythonBlocks } from "./python_source.ts";
import path from "node:path";
import process from "node:process";

export interface DebtMarker {
  file: string;
  line: number;
  shortcut: string;
  ceiling: string;
  upgrade: string;
  isValid: boolean;
  errors: string[];
  raw: string;
}

export interface SimplicityFinding {
  ruleId: string;
  file: string;
  line: number;
  severity: "ERROR" | "WARNING";
  message: string;
}

export const REDUNDANT_DEPENDENCIES: Record<string, string> = {
  uuid: "Use native crypto.randomUUID()",
  "lodash.clonedeep": "Use native structuredClone()",
  rimraf: "Use fs.promises.rm(dir, { recursive: true, force: true })",
  mkdirp: "Use fs.promises.mkdir(dir, { recursive: true })",
  "node-fetch": "Use native global fetch()",
  pytz: "Use standard library zoneinfo.ZoneInfo (Python 3.9+)",
  mock: "Use standard library unittest.mock (Python 3.3+)",
  six: "Remove dead Python 2 compatibility layer",
  simplejson: "Use standard library json",
  pathlib2: "Use standard library pathlib (Python 3.4+)",
  axios: "Use native global fetch() in Node 18+ or standard library",
  dotenv: "Use Node 20+ native flag (--env-file=.env) or standard library os.environ",
  chalk: "Use native ANSI escape codes or Node util.styleText()",
};

export const DEFAULT_EXCLUDES = new Set([
  ".git",
  ".venv",
  "venv",
  "node_modules",
  "__pycache__",
  ".agentflow",
  ".scratch",
  "scratch",
  ".idea",
  ".vscode",
  "build",
  "dist",
]);

export const IGNORE_EXTENSIONS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf",
  ".zip", ".tar", ".gz", ".lock", ".lockb", ".woff", ".woff2", ".ttf", ".eot",
]);

// Regex to find simplify: or ponytail: marker comment line
export const MARKER_PATTERN = /(?:^\s*(?:\/\/|#|\/\*|\*|--|<!--|;|%)?|(?<=[\s;])(?:\/\/|#|\/\*|\*|--|<!--|;|%))\s*(?:simplify|ponytail):\s*(.+)$/i;

// Field extractors: stop at next delimiter token or end of line
export const CEILING_PATTERN = /Ceiling:\s*(.+?)(?=(?:\s*[|;.]\s*Upgrade:|\s+Upgrade:|\s*$))/i;
export const UPGRADE_PATTERN = /Upgrade:\s*(.+?)(?=(?:\s*[|;.]\s*Ceiling:|\s+Ceiling:|\s*$))/i;

export function parseDebtMarker(rawText: string, filePath: string, lineNumber: number): DebtMarker | Record<string, never> {
  const match = MARKER_PATTERN.exec(rawText);
  if (!match) {
    return {};
  }

  let body = match[1].trim();

  // Strip any trailing comment closing tokens (*/, -->, etc.)
  body = body.replace(/(\*\/|-->|\?>)$/, "").trim();

  const ceilingMatch = CEILING_PATTERN.exec(body);
  const upgradeMatch = UPGRADE_PATTERN.exec(body);

  let ceiling: string | null = null;
  let upgrade: string | null = null;
  let shortcut = "";
  const errors: string[] = [];

  if (ceilingMatch || upgradeMatch) {
    if (ceilingMatch) {
      const extractedCeiling = ceilingMatch[1].trim().replace(/^[.|;\s]+|[.|;\s]+$/g, "");
      if (extractedCeiling) {
        ceiling = extractedCeiling;
      } else {
        errors.push("Empty 'Ceiling:' threshold");
      }
    } else {
      errors.push("Missing 'Ceiling:' threshold");
    }

    if (upgradeMatch) {
      const extractedUpgrade = upgradeMatch[1].trim().replace(/^[.|;\s]+|[.|;\s]+$/g, "");
      if (extractedUpgrade) {
        upgrade = extractedUpgrade;
      } else {
        errors.push("Empty 'Upgrade:' path");
      }
    } else {
      errors.push("Missing 'Upgrade:' path");
    }

    let firstStart = body.length;
    if (ceilingMatch) {
      firstStart = Math.min(firstStart, ceilingMatch.index);
    }
    if (upgradeMatch) {
      firstStart = Math.min(firstStart, upgradeMatch.index);
    }
    shortcut = body.slice(0, firstStart).trim().replace(/^[.|;\s]+|[.|;\s]+$/g, "");
  } else if (body.includes(",")) {
    const commaIdx = body.indexOf(",");
    const p1 = body.slice(0, commaIdx).trim();
    const p2 = body.slice(commaIdx + 1).trim();
    shortcut = p1;
    ceiling = p1;
    upgrade = p2;
  } else {
    shortcut = body.trim().replace(/^[.|;\s]+|[.|;\s]+$/g, "");
    errors.push("Missing 'Ceiling:' threshold");
    errors.push("Missing 'Upgrade:' path");
  }

  const shortcutLower = shortcut.toLowerCase();
  if (!shortcut || ["todo", "fixme", "clean this up", "optimize", "temp"].includes(shortcutLower)) {
    errors.push(`Vague or missing shortcut description: '${shortcut}'`);
  } else if (
    (shortcut.startsWith("<") && shortcut.endsWith(">")) ||
    ["shortcut", "desc", "description"].includes(shortcut.replace(/^[<]+|[>]+$/g, "").toLowerCase())
  ) {
    errors.push(`Unreplaced template placeholder in shortcut description: '${shortcut}'`);
  }

  if (ceiling) {
    const ceilingLower = ceiling.toLowerCase();
    if (["none", "n/a", "tbd", "todo", "fixme"].includes(ceilingLower)) {
      errors.push(`Vague or placeholder 'Ceiling:' threshold: '${ceiling}'`);
    } else if (
      (ceiling.startsWith("<") && ceiling.endsWith(">")) ||
      ["threshold/limit", "threshold", "limit", "ceiling"].includes(ceiling.replace(/^[<]+|[>]+$/g, "").toLowerCase())
    ) {
      errors.push(`Unreplaced template placeholder in 'Ceiling:' threshold: '${ceiling}'`);
    }
  }

  if (upgrade) {
    const upgradeLower = upgrade.toLowerCase();
    if (["none", "n/a", "tbd", "todo", "fixme"].includes(upgradeLower)) {
      errors.push(`Vague or placeholder 'Upgrade:' path: '${upgrade}'`);
    } else if (
      (upgrade.startsWith("<") && upgrade.endsWith(">")) ||
      ["next architecture", "architecture", "upgrade", "action"].includes(upgrade.replace(/^[<]+|[>]+$/g, "").toLowerCase())
    ) {
      errors.push(`Unreplaced template placeholder in 'Upgrade:' path: '${upgrade}'`);
    }
  }

  const isValid = errors.length === 0;

  return {
    file: filePath,
    line: lineNumber,
    shortcut,
    ceiling: ceiling ?? "N/A",
    upgrade: upgrade ?? "N/A",
    isValid,
    errors,
    raw: rawText.trim(),
  };
}

export function scanFile(filePath: string, baseDir: string): DebtMarker[] {
  const ext = path.extname(filePath).toLowerCase();
  if (IGNORE_EXTENSIONS.has(ext)) {
    return [];
  }

  let buffer: Buffer;
  try {
    const fd = fs.openSync(filePath, "r");
    const tempBuf = Buffer.alloc(1024);
    const bytesRead = fs.readSync(fd, tempBuf, 0, 1024, 0);
    fs.closeSync(fd);
    if (tempBuf.subarray(0, bytesRead).includes(0)) {
      return []; // Binary file
    }
    buffer = fs.readFileSync(filePath);
  } catch {
    return [];
  }

  const content = buffer.toString("utf-8");
  const contentLower = content.toLowerCase();
  if (!contentLower.includes("simplify:") && !contentLower.includes("ponytail:")) {
    return [];
  }

  const relative = path.relative(process.cwd(), filePath);
  const relPath = relative.startsWith("..") ? path.relative(baseDir, filePath) : relative;
  if (ext === ".py") {
    return pythonSource(content).comments.map(({text, line}) => parseDebtMarker(text, relPath, line)).filter((m): m is DebtMarker => "isValid" in m);
  }

  const markers: DebtMarker[] = [];
  const isMarkdown = ext === ".md" || ext === ".markdown";
  let inTextFence = false;

  const lines = content.split(/\r?\n/);
  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    const lineNum = idx + 1;

    if (isMarkdown) {
      const stripped = line.trim();
      if (stripped.startsWith("```")) {
        const tag = stripped.slice(3).trim().toLowerCase();
        if (!inTextFence) {
          if (["text", "txt", "plain"].includes(tag)) {
            inTextFence = true;
          }
        } else {
          inTextFence = false;
        }
        continue;
      }
      if (inTextFence) {
        continue;
      }
      if (/^\s*#{1,6}\s+/.test(line)) {
        continue;
      }
    }

    const lower = line.toLowerCase();
    if (lower.includes("simplify:") || lower.includes("ponytail:")) {
      const parsed = parseDebtMarker(line, relPath, lineNum);
      if ("isValid" in parsed) {
        markers.push(parsed);
      }
    }
  }

  return markers;
}

export function scanPaths(targets: string[], excludes: Set<string> = DEFAULT_EXCLUDES): DebtMarker[] {
  const allMarkers: DebtMarker[] = [];

  for (const target of targets) {
    const resolved = path.resolve(target);
    let stat: fs.Stats;
    try {
      stat = fs.statSync(resolved);
    } catch {
      continue;
    }

    if (stat.isFile()) {
      allMarkers.push(...scanFile(resolved, path.dirname(resolved)));
    } else if (stat.isDirectory()) {
      const traverse = (dir: string) => {
        let entries: fs.Dirent[];
        try {
          entries = fs.readdirSync(dir, { withFileTypes: true });
        } catch {
          return;
        }

        for (const entry of entries) {
          if (entry.name.startsWith(".")) {
            continue;
          }
          if (entry.isDirectory()) {
            if (!excludes.has(entry.name)) {
              traverse(path.join(dir, entry.name));
            }
          } else if (entry.isFile()) {
            allMarkers.push(...scanFile(path.join(dir, entry.name), resolved));
          }
        }
      };
      traverse(resolved);
    }
  }

  return allMarkers;
}

export function formatTable(markers: DebtMarker[], markdown: boolean = true): string {
  if (markers.length === 0) {
    return "No technical debt markers found. Codebase is clean.";
  }

  const lines: string[] = [];
  lines.push("| Location | Shortcut Taken | Operational Ceiling | Designated Upgrade Path | Status |");
  lines.push("|---|---|---|---|---|");
  for (const m of markers) {
    const loc = `\`${m.file}:${m.line}\``;
    const shortcut = m.shortcut.replace(/\|/g, "\\|");
    const ceiling = m.ceiling.replace(/\|/g, "\\|");
    const upgrade = m.upgrade.replace(/\|/g, "\\|");
    const status = m.isValid ? "✅ Valid" : `❌ Invalid: ${m.errors.join(", ")}`;
    lines.push(`| ${loc} | ${shortcut} | ${ceiling} | ${upgrade} | ${status} |`);
  }

  return lines.join("\n");
}

export function auditCodeSimplicity(filePath: string, content?: string): SimplicityFinding[] {
  if (content == null) {
    try {
      content = fs.readFileSync(filePath, "utf-8");
    } catch {
      return [];
    }
  }

  const findings: SimplicityFinding[] = [];
  const lines = content.split(/\r?\n/);

  // 1. Redundant dependencies (Laziness Ladder Rungs 3 & 5)
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const stripped = line.trim();
    if (stripped.startsWith("#") || stripped.startsWith("//") || stripped.startsWith("/*") || stripped.startsWith("*")) {
      continue;
    }

    for (const [dep, replacement] of Object.entries(REDUNDANT_DEPENDENCIES)) {
      const escapedDep = dep.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const pattern = new RegExp(
        `(?:import\\s+.*\\s+from\\s+['"]${escapedDep}['"]|require\\s*\\(\\s*['"]${escapedDep}['"]\\s*\\)|import\\s+['"]${escapedDep}['"]|import\\s+${escapedDep}\\b)`
      );
      if (pattern.test(stripped)) {
        findings.push({
          ruleId: "SMP-DEP-001",
          file: filePath,
          line: i + 1,
          severity: "ERROR",
          message: `Redundant external dependency '${dep}' detected. Laziness Ladder violation: ${replacement}.`,
        });
      }
    }
  }

  if (path.extname(filePath) === ".py") {
    for (const block of pythonBlocks(pythonSource(content).code, "class")) {
      const methods = pythonBlocks(block.body, "def");
      const statements = block.body.split(/\r?\n/).filter(l => l.trim() && !l.trim().startsWith("@") && (l.match(/^\s*/)?.[0].length ?? 0) === block.indent + 4);
      if (block.name.endsWith("Factory") && statements.length <= 3) findings.push({ruleId: "SMP-ABS-001", file: filePath, line: block.line, severity: "WARNING", message: `Speculative factory class '${block.name}' detected with minimal implementation. Favor direct concrete instantiation.`});
      const nonDunder = methods.filter(m => !m.name.startsWith("__"));
      if (nonDunder.length && nonDunder.every(m => /^return\s+\w+\.(?:_\w*|repo\w*|inner\w*|service\w*)\.\w+\([\s\S]*\)\s*$/.test(m.body.trim()))) findings.push({ruleId: "SMP-WRAP-001", file: filePath, line: block.line, severity: "WARNING", message: `Shallow wrapper class '${block.name}' forwards all calls without domain logic. Deepen the module or eliminate the wrapper layer.`});
    }
    return findings;
  }

  // 2. Speculative factories and shallow wrappers in TS / JS / Python
  const classRegex = /class\s+([A-Za-z0-9_]+)\b[^{]*\{([\s\S]*?)\n\}/g;
  let classMatch: RegExpExecArray | null;
  while ((classMatch = classRegex.exec(content)) !== null) {
    const className = classMatch[1];
    const classBody = classMatch[2];
    const classStartIdx = classMatch.index;
    const lineNo = content.slice(0, classStartIdx).split(/\r?\n/).length;

    // Speculative factory check
    if (className.endsWith("Factory")) {
      const nonCommentLines = classBody.split(/\r?\n/).filter((l) => {
        const s = l.trim();
        return s.length > 0 && !s.startsWith("//") && !s.startsWith("/*") && !s.startsWith("*");
      });
      if (nonCommentLines.length <= 4) {
        findings.push({
          ruleId: "SMP-ABS-001",
          file: filePath,
          line: lineNo,
          severity: "WARNING",
          message: `Speculative factory class '${className}' detected with minimal implementation. Favor direct concrete instantiation.`,
        });
      }
    }

    // Shallow wrapper check (all methods simply delegate to inner._inner or similar)
    const methodMatches = Array.from(classBody.matchAll(/(?:async\s+)?([A-Za-z0-9_]+)\s*\([^)]*\)\s*\{([\s\S]*?)\}/g));
    const nonConstructorMethods = methodMatches.filter((m) => m[1] !== "constructor");
    if (nonConstructorMethods.length >= 1) {
      let forwardingCount = 0;
      for (const m of nonConstructorMethods) {
        const methodBody = m[2].trim();
        if (/^return\s+this\._?[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+\([^)]*\);?$/.test(methodBody)) {
          forwardingCount++;
        }
      }
      if (forwardingCount === nonConstructorMethods.length) {
        findings.push({
          ruleId: "SMP-WRAP-001",
          file: filePath,
          line: lineNo,
          severity: "WARNING",
          message: `Shallow wrapper class '${className}' forwards all calls without domain logic. Deepen the module or eliminate the wrapper layer.`,
        });
      }
    }
  }

  return findings;
}

export function auditPathsSimplicity(targets: string[], excludes: Set<string> = DEFAULT_EXCLUDES): SimplicityFinding[] {
  const findings: SimplicityFinding[] = [];
  const targetExts = new Set([".py", ".ts", ".js", ".tsx", ".jsx", ".go"]);

  for (const target of targets) {
    const resolved = path.resolve(target);
    let stat: fs.Stats;
    try {
      stat = fs.statSync(resolved);
    } catch {
      continue;
    }

    if (stat.isFile()) {
      findings.push(...auditCodeSimplicity(resolved));
    } else if (stat.isDirectory()) {
      const traverse = (dir: string) => {
        let entries: fs.Dirent[];
        try {
          entries = fs.readdirSync(dir, { withFileTypes: true });
        } catch {
          return;
        }

        for (const entry of entries) {
          if (entry.name.startsWith(".")) {
            continue;
          }
          if (entry.isDirectory()) {
            if (!excludes.has(entry.name)) {
              traverse(path.join(dir, entry.name));
            }
          } else if (entry.isFile()) {
            const fileExt = path.extname(entry.name).toLowerCase();
            if (targetExts.has(fileExt)) {
              findings.push(...auditCodeSimplicity(path.join(dir, entry.name)));
            }
          }
        }
      };
      traverse(resolved);
    }
  }

  return findings;
}

export function scanDebt(paths?: string[], strict: boolean = false): [DebtMarker[], boolean] {
  const targetPaths = paths && paths.length > 0 ? paths : [process.cwd()];
  const markers = scanPaths(targetPaths);
  const hasErrors = markers.some((m) => !m.isValid);
  return [markers, hasErrors];
}

export function main(argv: string[] = process.argv.slice(2)): number {
  const paths: string[] = [];
  let format: "markdown" | "table" | "json" = "markdown";
  let strict = false;
  let auditCode = false;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--format") {
      const next = argv[++i];
      if (next === "markdown" || next === "table" || next === "json") {
        format = next;
      }
    } else if (arg.startsWith("--format=")) {
      const val = arg.split("=")[1];
      if (val === "markdown" || val === "table" || val === "json") {
        format = val;
      }
    } else if (arg === "--strict") {
      strict = true;
    } else if (arg === "--audit-code") {
      auditCode = true;
    } else if (!arg.startsWith("-")) {
      paths.push(arg);
    }
  }

  if (paths.length === 0) {
    paths.push(".");
  }

  const markers = scanPaths(paths);
  let codeFindings: SimplicityFinding[] = [];
  if (auditCode) {
    codeFindings = auditPathsSimplicity(paths);
  }

  if (format === "json") {
    const output = auditCode ? { markers, codeFindings } : markers;
    console.log(JSON.stringify(output, null, 2));
  } else {
    console.log(formatTable(markers, format === "markdown"));
    if (codeFindings.length > 0) {
      console.log("\n### 🔍 Code Simplicity Findings:");
      for (const f of codeFindings) {
        const icon = f.severity === "ERROR" ? "❌" : "⚠️";
        console.log(`  ${icon} [${f.ruleId}] \`${f.file}:${f.line}\`: ${f.message}`);
      }
    }
  }

  const hasInvalidMarkers = markers.some((m) => !m.isValid);
  const hasCodeErrors = codeFindings.some((f) => f.severity === "ERROR");

  if (strict && (hasInvalidMarkers || hasCodeErrors)) {
    const invCount = markers.filter((m) => !m.isValid).length;
    const codeErrs = codeFindings.filter((f) => f.severity === "ERROR").length;
    if (codeErrs === 0) {
      process.stderr.write(`\nError: Found ${invCount} invalid debt marker(s).\n`);
    } else {
      process.stderr.write(`\nError: Found ${invCount + codeErrs} simplify violation(s).\n`);
    }
    return 1;
  }

  return 0;
}

// Direct CLI invocation
if (import.meta.url === `file://${process.argv[1]}`) {
  const exitCode = main();
  process.exit(exitCode);
}
