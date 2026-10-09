#!/usr/bin/env node
/**
 * audit_ux.ts / ux.ts — Deterministic UX, Accessibility, and Design Token Scanner.
 * Zero external dependencies (Node.js 22+ / 25+ standard library).
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

export const TARGET_EXTENSIONS = new Set([
  ".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".astro"
]);

export const DEFAULT_EXCLUDES = new Set([
  ".git", ".venv", "venv", "node_modules", "__pycache__",
  ".agentflow", ".scratch", "scratch", ".idea", ".vscode",
  "build", "dist", ".next", ".nuxt", "coverage",
]);

export const SEVERITY_LEVELS: Record<string, number> = {
  CRITICAL: 4,
  ERROR: 3,
  WARNING: 2,
  INFO: 1,
};

export const DEFAULT_ALLOWED_ARBITRARY = new Set([
  "0", "1px", "2px", "100%", "auto", "inherit", "100vh", "100vw",
  "full", "fit-content", "min-content", "max-content", "screen",
]);

export const ACCESSIBLE_PRIMITIVES_TEMPLATE = `<!-- Universal Accessible Component Blueprints -->

<!-- 1. Accessible Button with Focus Ring, Busy State, and Keyboard Handling -->
<button
  type="button"
  disabled={isLoading || isDisabled}
  aria-busy={isLoading}
  className="inline-flex items-center justify-center px-4 py-2 font-medium rounded-md
             focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-600
             disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
  onClick={handleClick}
>
  {isLoading ? (
    <>
      <svg className="animate-spin -ml-1 mr-2 h-4 w-4" aria-hidden="true" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
      </svg>
      <span>Loading...</span>
    </>
  ) : (
    children
  )}
</button>

<!-- 2. Accessible Icon-Only Button -->
<button
  type="button"
  aria-label="Close dialog"
  className="p-2 rounded-full hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
  onClick={onClose}
>
  <svg aria-hidden="true" className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
    <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
  </svg>
  <span className="sr-only">Close</span>
</button>

<!-- 3. Accessible Form Field with Associated Label and Error Recovery -->
<div className="flex flex-col gap-1.5">
  <label htmlFor="user-email" className="text-sm font-medium text-gray-900">
    Email address <span aria-hidden="true" className="text-red-600">*</span>
  </label>
  <input
    id="user-email"
    name="email"
    type="email"
    required
    aria-invalid={Boolean(errorMessage)}
    aria-describedby={errorMessage ? "email-error" : undefined}
    className="px-3 py-2 border rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
  />
  {errorMessage && (
    <p id="email-error" role="alert" className="text-sm text-red-600 flex items-center gap-1">
      <span>{errorMessage}</span>
      <button type="button" onClick={onRetry} className="underline font-medium ml-1">Retry</button>
    </p>
  )}
</div>

<!-- 4. Accessible Modal Dialog with Trapped Focus & ESC Dismissal -->
<dialog
  ref={dialogRef}
  aria-labelledby="dialog-title"
  aria-describedby="dialog-desc"
  className="p-6 rounded-lg shadow-xl backdrop:bg-black/50"
  onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
>
  <h2 id="dialog-title" className="text-lg font-bold">Dialog Title</h2>
  <p id="dialog-desc" className="mt-2 text-sm text-gray-600">Dialog description body text.</p>
  <div className="mt-4 flex justify-end gap-2">
    <button type="button" onClick={onClose} className="px-4 py-2">Cancel</button>
    <button type="button" onClick={onConfirm} className="px-4 py-2 bg-blue-600 text-white rounded">Confirm</button>
  </div>
</dialog>
`;

export interface UXViolation {
  rule_id: string;
  severity: "CRITICAL" | "ERROR" | "WARNING" | "INFO";
  message: string;
  file_path: string;
  line_number: number;
  snippet?: string;
}

export const CLICK_HANDLER_PATTERN = /<(div|span|p|section|article)\b([^>]*?)(?:onClick|@click|v-on:click|onclick)=([^>]*?)>/gi;
export const KEYBOARD_HANDLER_PATTERN = /\b(?:onKeyDown|onKeyUp|onKeyPress|@keydown|@keyup|v-on:keydown|v-on:keyup)\b/i;
export const OUTLINE_NONE_PATTERN = /(?:\boutline-none\b|\bfocus:outline-none\b|outline\s*:\s*(?:none|0))/i;
export const FOCUS_REPLACEMENT_PATTERN = /(?:\bfocus(?:-visible)?:(?:ring|border|shadow|outline-[a-z0-9_-]+)\b|\bring-|\bbox-shadow\b|\bvar\(--(?:focus-ring|ring)\)|\bshadow-)/i;
export const BUTTON_ELEMENT_PATTERN = /<(?:button\b|a\b[^>]*\brole\s*=\s*["']button["'])([^>]*)>([\s\S]*?)<\/(?:button|a)>/gi;
export const INPUT_PATTERN = /<(input|textarea|select)\b([^>]*?)>/gi;
export const LABEL_FOR_PATTERN = /<label\b[^>]*?(?:for|htmlFor)\s*=\s*["']([^"']+)["']/gi;
export const GENERIC_ERROR_PATTERN = /(?:["'`]\s*(?:An error occurred|Something went wrong|Error loading data|Unknown error)\s*["'`]|>\s*(?:An error occurred|Something went wrong|Error loading data|Unknown error)\s*<)/i;
export const RECOVERY_CTA_PATTERN = /\b(?:retry|reload|refresh|try again|contact|support|go back|return)\b/i;
export const ARBITRARY_TAILWIND_PATTERN = /(?:\b|(?<=[\s"'`]))([a-zA-Z0-9_-]*(?:p|m|px|py|pl|pr|pt|pb|mx|my|ml|mr|mt|mb|top|bottom|left|right|w|h|gap|inset)-\[([^\]]+)\])/g;
export const DIALOG_PATTERN = /<(?:dialog\b|div\b[^>]*\brole\s*=\s*["']dialog["'])([^>]*)>/gi;
export const MAP_COLLECTION_PATTERN = /\b(\w+)\.map\s*\(/gi;

export function checkClickableElements(content: string, filePath: string): UXViolation[] {
  const violations: UXViolation[] = [];
  const lines = content.split(/\r?\n/);

  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    const regex = new RegExp(CLICK_HANDLER_PATTERN.source, "gi");
    let match: RegExpExecArray | null;
    while ((match = regex.exec(line)) !== null) {
      const tag = match[1].toLowerCase();
      const attrs = match[2] + " " + match[3];
      const hasKeyboard = KEYBOARD_HANDLER_PATTERN.test(attrs) || KEYBOARD_HANDLER_PATTERN.test(line);

      if (!hasKeyboard) {
        violations.push({
          rule_id: "UX-001",
          severity: "ERROR",
          message: `Interactive-looking non-native <${tag}> lacks keyboard interaction (Enter/Space). Prefer native <button> over ARIA remediation.`,
          file_path: filePath,
          line_number: idx + 1,
          snippet: line.trim().slice(0, 100),
        });
      }
    }
  }
  return violations;
}

export function checkFocusIndicators(content: string, filePath: string): UXViolation[] {
  const violations: UXViolation[] = [];
  const lines = content.split(/\r?\n/);

  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    if (OUTLINE_NONE_PATTERN.test(line)) {
      if (!FOCUS_REPLACEMENT_PATTERN.test(line)) {
        violations.push({
          rule_id: "UX-002",
          severity: "ERROR",
          message: "Suppressed focus outline (outline-none) without replacement indicator (ring, box-shadow, or border).",
          file_path: filePath,
          line_number: idx + 1,
          snippet: line.trim().slice(0, 100),
        });
      }
    }
  }
  return violations;
}

export function checkIconButtons(content: string, filePath: string): UXViolation[] {
  const violations: UXViolation[] = [];
  const regex = new RegExp(BUTTON_ELEMENT_PATTERN.source, "gi");
  let match: RegExpExecArray | null;

  while ((match = regex.exec(content)) !== null) {
    const attrs = match[1];
    const body = match[2].trim();

    const strippedBody = body.replace(/<[^>]+>/g, "").trim();
    const hasIconTag = /<(?:svg|i|Icon|Lucide|Feather)\b/i.test(body);

    if (hasIconTag && !strippedBody) {
      const hasAriaLabel = /\b(?:aria-label|aria-labelledby)\s*=/i.test(attrs);
      const hasSrText = /(?:sr-only|visually-hidden)/i.test(body);
      const hasTitle = /\btitle\s*=/i.test(attrs);

      const lineNo = content.slice(0, match.index).split(/\r?\n/).length;

      if (!hasAriaLabel && !hasSrText && !hasTitle) {
        violations.push({
          rule_id: "UX-003",
          severity: "ERROR",
          message: "Icon-only button has no accessible name (missing aria-label, aria-labelledby, or .sr-only text).",
          file_path: filePath,
          line_number: lineNo,
          snippet: match[0].split(/\r?\n/)[0].trim().slice(0, 100),
        });
      } else if (hasTitle && !hasAriaLabel && !hasSrText) {
        violations.push({
          rule_id: "UX-031",
          severity: "INFO",
          message: "Icon button uses title attribute rather than aria-label or visually-hidden text.",
          file_path: filePath,
          line_number: lineNo,
          snippet: match[0].split(/\r?\n/)[0].trim().slice(0, 100),
        });
      }
    }
  }
  return violations;
}

export function checkFormLabels(content: string, filePath: string): UXViolation[] {
  const violations: UXViolation[] = [];
  const lines = content.split(/\r?\n/);

  const associatedLabelIds = new Set<string>();
  let lMatch: RegExpExecArray | null;
  const lRegex = new RegExp(LABEL_FOR_PATTERN.source, "gi");
  while ((lMatch = lRegex.exec(content)) !== null) {
    associatedLabelIds.add(lMatch[1]);
  }

  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    const regex = new RegExp(INPUT_PATTERN.source, "gi");
    let match: RegExpExecArray | null;
    while ((match = regex.exec(line)) !== null) {
      const tag = match[1].toLowerCase();
      const attrs = match[2];

      const typeMatch = /type\s*=\s*["']([^"']+)["']/i.exec(attrs);
      if (typeMatch && ["hidden", "submit", "button", "reset"].includes(typeMatch[1].toLowerCase())) {
        continue;
      }

      const hasAriaLabel = /\b(?:aria-label|aria-labelledby)\s*=/i.test(attrs);
      const idMatch = /\bid\s*=\s*["']([^"']+)["']/i.exec(attrs);
      const hasMatchingLabel = Boolean(idMatch && associatedLabelIds.has(idMatch[1]));

      const startPos = match.index;
      const precedingChunk = line.slice(Math.max(0, startPos - 300), startPos);
      const isWrappedInLabel = precedingChunk.includes("<label") && !precedingChunk.includes("</label>");

      if (!hasAriaLabel && !hasMatchingLabel && !isWrappedInLabel) {
        violations.push({
          rule_id: "UX-014",
          severity: "ERROR",
          message: `Form <${tag}> element has no accessible name (missing associated <label for>, aria-label, or aria-labelledby).`,
          file_path: filePath,
          line_number: idx + 1,
          snippet: line.trim().slice(0, 100),
        });
      }
    }
  }
  return violations;
}

export function checkArbitraryTokens(
  content: string,
  filePath: string,
  allowedTokens: Set<string>
): UXViolation[] {
  const violations: UXViolation[] = [];
  const lines = content.split(/\r?\n/);

  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    const regex = new RegExp(ARBITRARY_TAILWIND_PATTERN.source, "g");
    let match: RegExpExecArray | null;
    while ((match = regex.exec(line)) !== null) {
      const fullClass = match[1];
      const rawVal = match[2].trim().toLowerCase();

      if (!allowedTokens.has(rawVal)) {
        violations.push({
          rule_id: "UX-021",
          severity: "WARNING",
          message: `Arbitrary value: '${fullClass}'. Avoid arbitrary values when existing tokens satisfy; permit when justified.`,
          file_path: filePath,
          line_number: idx + 1,
          snippet: line.trim().slice(0, 100),
        });
      }
    }
  }
  return violations;
}

export function checkDeadEndErrors(content: string, filePath: string): UXViolation[] {
  const violations: UXViolation[] = [];
  const lines = content.split(/\r?\n/);

  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    if (GENERIC_ERROR_PATTERN.test(line)) {
      const startWindow = Math.max(0, idx - 5);
      const endWindow = Math.min(lines.length, idx + 6);
      const windowText = lines.slice(startWindow, endWindow).join(" ");

      if (!RECOVERY_CTA_PATTERN.test(windowText)) {
        violations.push({
          rule_id: "UX-005",
          severity: "WARNING",
          message: "Generic error message without actionable recovery action (e.g. Retry, Reload, Contact).",
          file_path: filePath,
          line_number: idx + 1,
          snippet: line.trim().slice(0, 100),
        });
      }
    }
  }
  return violations;
}

export function checkModalDialogs(content: string, filePath: string): UXViolation[] {
  const violations: UXViolation[] = [];
  const regex = new RegExp(DIALOG_PATTERN.source, "gi");
  let match: RegExpExecArray | null;

  while ((match = regex.exec(content)) !== null) {
    const attrs = match[1];
    const hasAriaLabel = /\b(?:aria-label|aria-labelledby)\s*=/i.test(attrs);
    const hasTitle = /\btitle\s*=/i.test(attrs);
    if (!hasAriaLabel && !hasTitle) {
      const lineNo = content.slice(0, match.index).split(/\r?\n/).length;
      violations.push({
        rule_id: "UX-041",
        severity: "ERROR",
        message: "Modal dialog lacks accessible name (missing aria-label, aria-labelledby, or title).",
        file_path: filePath,
        line_number: lineNo,
        snippet: match[0].split(/\r?\n/)[0].trim().slice(0, 100),
      });
    }
  }
  return violations;
}

export function checkStateCompleteness(content: string, filePath: string): UXViolation[] {
  const violations: UXViolation[] = [];
  const matches: RegExpExecArray[] = [];
  const regex = new RegExp(MAP_COLLECTION_PATTERN.source, "gi");
  let m: RegExpExecArray | null;
  while ((m = regex.exec(content)) !== null) {
    matches.push(m);
  }
  if (matches.length === 0) {
    return violations;
  }

  const hasEmpty = /(?:\.length\s*===?\s*0|!\w+\.length|\bEmpty\b|No\s+(?:items|results|data)|not\s+found)/i.test(content);
  const hasLoading = /(?:\bisLoading\b|\bloading\b|\bSkeleton\b|\bSpinner\b|\bpending\b)/i.test(content);

  if (!hasEmpty || !hasLoading) {
    const firstMatch = matches[0];
    const lineNo = content.slice(0, firstMatch.index).split(/\r?\n/).length;
    const missing: string[] = [];
    if (!hasEmpty) {
      missing.push("empty state (.length === 0 / 'No items')");
    }
    if (!hasLoading) {
      missing.push("loading skeleton/spinner");
    }

    violations.push({
      rule_id: "UX-051",
      severity: "WARNING",
      message: `Dynamic collection mapping missing: ${missing.join(", ")}. Brad Frost 6-state completeness requires explicit Empty and Loading branches.`,
      file_path: filePath,
      line_number: lineNo,
      snippet: content.slice(firstMatch.index, firstMatch.index + 80).trim(),
    });
  }
  return violations;
}

export function auditContent(
  content: string,
  filePath: string,
  ignoreRules?: Set<string>,
  allowedArbitrary?: Set<string>
): UXViolation[] {
  const ignored = ignoreRules || new Set<string>();
  const allowedTokens = allowedArbitrary || DEFAULT_ALLOWED_ARBITRARY;
  const violations: UXViolation[] = [];

  if (!ignored.has("UX-001") && !ignored.has("DIV_BUTTON")) {
    violations.push(...checkClickableElements(content, filePath));
  }
  if (!ignored.has("UX-002") && !ignored.has("SUPPRESSED_FOCUS")) {
    violations.push(...checkFocusIndicators(content, filePath));
  }
  if (!ignored.has("UX-003") && !ignored.has("UX-031") && !ignored.has("ICON_BUTTON_LABEL")) {
    violations.push(...checkIconButtons(content, filePath));
  }
  if (!ignored.has("UX-014") && !ignored.has("MISSING_INPUT_LABEL")) {
    violations.push(...checkFormLabels(content, filePath));
  }
  if (!ignored.has("UX-021")) {
    violations.push(...checkArbitraryTokens(content, filePath, allowedTokens));
  }
  if (!ignored.has("UX-005") && !ignored.has("DEAD_END_ERROR")) {
    violations.push(...checkDeadEndErrors(content, filePath));
  }
  if (!ignored.has("UX-041") && !ignored.has("MODAL_DIALOG_LABEL")) {
    violations.push(...checkModalDialogs(content, filePath));
  }
  if (!ignored.has("UX-051") && !ignored.has("STATE_COMPLETENESS")) {
    violations.push(...checkStateCompleteness(content, filePath));
  }

  return violations;
}

export function auditFile(
  filePath: string,
  ignoreRules?: Set<string>,
  allowedArbitrary?: Set<string>
): UXViolation[] {
  const ext = path.extname(filePath).toLowerCase();
  if (!TARGET_EXTENSIONS.has(ext)) {
    return [];
  }
  try {
    const content = fs.readFileSync(filePath, "utf-8");
    return auditContent(content, filePath, ignoreRules, allowedArbitrary);
  } catch (err: any) {
    return [
      {
        rule_id: "UX-999",
        severity: "ERROR",
        message: `Failed to read file: ${err.message}`,
        file_path: filePath,
        line_number: 1,
      },
    ];
  }
}

export function auditPath(
  targetPath: string,
  ignoreRules?: Set<string>,
  allowedArbitrary?: Set<string>
): UXViolation[] {
  const resolved = path.resolve(targetPath);
  if (!fs.existsSync(resolved)) {
    return [];
  }
  const stat = fs.statSync(resolved);
  if (stat.isFile()) {
    return auditFile(resolved, ignoreRules, allowedArbitrary);
  }
  if (!stat.isDirectory()) {
    return [];
  }

  const violations: UXViolation[] = [];
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
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!DEFAULT_EXCLUDES.has(entry.name)) {
          traverse(full);
        }
      } else if (entry.isFile()) {
        const ext = path.extname(entry.name).toLowerCase();
        if (TARGET_EXTENSIONS.has(ext)) {
          violations.push(...auditFile(full, ignoreRules, allowedArbitrary));
        }
      }
    }
  };

  traverse(resolved);
  return violations;
}

export function main(argv: string[] = process.argv.slice(2)): number {
  const paths: string[] = [];
  let failOn = "error";
  let strict = false;
  let allowArbitrary = "";
  let ignoreRulesStr = "";
  let jsonOutput = false;
  let quiet = false;
  let template = false;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--template") {
      template = true;
    } else if (arg === "--strict") {
      strict = true;
    } else if (arg === "--json") {
      jsonOutput = true;
    } else if (arg === "--quiet") {
      quiet = true;
    } else if (arg === "--fail-on") {
      failOn = argv[++i];
    } else if (arg.startsWith("--fail-on=")) {
      failOn = arg.split("=")[1];
    } else if (arg === "--allow-arbitrary") {
      allowArbitrary = argv[++i];
    } else if (arg.startsWith("--allow-arbitrary=")) {
      allowArbitrary = arg.split("=")[1];
    } else if (arg === "--ignore-rules") {
      ignoreRulesStr = argv[++i];
    } else if (arg.startsWith("--ignore-rules=")) {
      ignoreRulesStr = arg.split("=")[1];
    } else if (!arg.startsWith("-")) {
      paths.push(arg);
    }
  }

  if (template) {
    console.log(ACCESSIBLE_PRIMITIVES_TEMPLATE);
    return 0;
  }

  if (paths.length === 0) {
    paths.push(".");
  }

  const failLevel = strict ? "warning" : failOn;
  const failThreshold = SEVERITY_LEVELS[failLevel.toUpperCase()] ?? 3;

  const ignoreRules = new Set(
    ignoreRulesStr.split(",").map((r) => r.trim().toUpperCase()).filter(Boolean)
  );

  const allowedArbitrarySet = new Set(DEFAULT_ALLOWED_ARBITRARY);
  if (allowArbitrary) {
    for (const t of allowArbitrary.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean)) {
      allowedArbitrarySet.add(t);
    }
  }

  const allViolations: UXViolation[] = [];
  for (const p of paths) {
    allViolations.push(...auditPath(p, ignoreRules, allowedArbitrarySet));
  }

  const counts = {
    CRITICAL: allViolations.filter((v) => v.severity === "CRITICAL").length,
    ERROR: allViolations.filter((v) => v.severity === "ERROR").length,
    WARNING: allViolations.filter((v) => v.severity === "WARNING").length,
    INFO: allViolations.filter((v) => v.severity === "INFO").length,
  };

  if (jsonOutput) {
    console.log(
      JSON.stringify(
        {
          total_violations: allViolations.length,
          counts,
          violations: allViolations,
        },
        null,
        2
      )
    );
  } else {
    if (!quiet) {
      console.log("🎨 UX & Accessibility Audit Scanner");
      console.log("=======================================================");
    }

    if (allViolations.length === 0) {
      if (!quiet) {
        console.log("✅ 0 UX / Accessibility violations found.");
      }
      return 0;
    }

    const icons: Record<string, string> = {
      CRITICAL: "🛑",
      ERROR: "❌",
      WARNING: "⚠️",
      INFO: "ℹ️",
    };

    for (const v of allViolations) {
      const icon = icons[v.severity] || "•";
      console.log(`${icon} ${v.rule_id} ${v.severity}: ${v.file_path}:${v.line_number} — ${v.message}`);
      if (v.snippet) {
        console.log(`   Snippet: ${v.snippet}`);
      }
    }

    console.log("-------------------------------------------------------");
    console.log(
      `Summary: ${counts.CRITICAL} critical, ${counts.ERROR} error(s), ${counts.WARNING} warning(s), ${counts.INFO} info.`
    );
  }

  const maxSeverity = Math.max(
    0,
    ...allViolations.map((v) => SEVERITY_LEVELS[v.severity] ?? 0)
  );

  return maxSeverity >= failThreshold ? 1 : 0;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const exitCode = main();
  process.exit(exitCode);
}
