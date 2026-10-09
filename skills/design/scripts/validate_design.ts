#!/usr/bin/env node
/**
 * validate_design.ts / design.ts — Deterministic Systems Design & Architecture Validator.
 *
 * Zero external dependencies (Node.js 22+ / 25+ standard library).
 *
 * Validates:
 * 1. Architecture Decision Records (ADRs) against adr_template.md contract.
 * 2. OpenSpec change packages (proposal.md, specs/*.md, design.md, tasks.md).
 * 3. Design interview rounds and frontier anti-cheat constraints.
 * 4. Capability closure matrices and confirmation gate discipline.
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

export const ADR_TITLE_PATTERN = /^#\s+ADR-(\d{1,5}):\s+(.+)$/m;
export const ADR_STATUS_PATTERN = /-\s+\*\*Status\*\*:\s*\[?(PROPOSED|ACCEPTED|SUPERSEDED|REJECTED)\]?/i;
export const ADR_DATE_PATTERN = /-\s+\*\*Date\*\*:\s*\[?(\d{4}-\d{2}-\d{2})\]?/i;

export const RFC2119_PATTERN = /\b(SHALL|MUST|REQUIRED|SHALL NOT|MUST NOT)\b/;
export const GHERKIN_WHEN_THEN = /\b(GIVEN|WHEN|THEN)\b/i;

export const ROUND_HEADER_PATTERN = /^###\s+🏛️\s*Round\s+(\d+)\s*—\s*Design\s+Frontier/im;
export const QUESTION_PATTERN = /❓\s*\*\*Q(\d+)\*\*\s*-\s*\*\*([^*]+)\*\*:/gi;
export const RECOMMENDED_STANCE_PATTERN = /➡️\s*\*\*Recommended\s+Stance\*\*:\s*(.+)$/gim;

export const VACUOUS_STANCE_KEYWORDS = [
  "whatever you prefer",
  "choose what you want",
  "up to you",
  "up to the team",
  "no recommendation",
  "developer preference",
  "tbd",
  "any option is fine",
];

export interface Finding {
  rule_id: string;
  severity: "ERROR" | "WARNING" | "INFO";
  message: string;
  file_path?: string | null;
  line_number?: number | null;
}

export class ValidationResult {
  passed: boolean;
  findings: Finding[];
  metrics: Record<string, any>;

  constructor(passed: boolean, findings: Finding[] = [], metrics: Record<string, any> = {}) {
    this.passed = passed;
    this.findings = findings;
    this.metrics = metrics;
  }

  get errors(): Finding[] {
    return this.findings.filter((f) => f.severity === "ERROR");
  }

  get warnings(): Finding[] {
    return this.findings.filter((f) => f.severity === "WARNING");
  }

  to_dict(): Record<string, any> {
    return {
      passed: this.passed,
      error_count: this.errors.length,
      warning_count: this.warnings.length,
      findings: this.findings,
      metrics: this.metrics,
    };
  }
}

export function validateAdrContent(content: string, filename: string = "ADR.md"): ValidationResult {
  const findings: Finding[] = [];
  const lines = content.split(/\r?\n/);

  // 1. Title
  if (!ADR_TITLE_PATTERN.test(content)) {
    findings.push({
      rule_id: "DES-ADR-001",
      severity: "ERROR",
      message: "Missing or invalid ADR title. Expected format: '# ADR-[NNNN]: [Short Title]'",
      file_path: filename,
      line_number: 1,
    });
  }

  // 2. Metadata: Status, Date, Target Components
  if (!ADR_STATUS_PATTERN.test(content)) {
    findings.push({
      rule_id: "DES-ADR-002",
      severity: "ERROR",
      message: "Missing or invalid '- **Status**: [PROPOSED / ACCEPTED / SUPERSEDED / REJECTED]'",
      file_path: filename,
    });
  }

  if (!ADR_DATE_PATTERN.test(content)) {
    findings.push({
      rule_id: "DES-ADR-003",
      severity: "ERROR",
      message: "Missing or invalid '- **Date**: [YYYY-MM-DD]'",
      file_path: filename,
    });
  }

  if (!content.includes("- **Target Components**:") && !content.includes("**Target Components**")) {
    findings.push({
      rule_id: "DES-ADR-004",
      severity: "WARNING",
      message: "Missing '- **Target Components**: [e.g. ServiceA, DB, Broker]'",
      file_path: filename,
    });
  }

  // 3. Section 1: Context & Problem Statement
  if (!/^##\s+1\.\s+Context\s+&\s+Problem\s+Statement/m.test(content)) {
    findings.push({
      rule_id: "DES-ADR-005",
      severity: "ERROR",
      message: "Missing required section: '## 1. Context & Problem Statement'",
      file_path: filename,
    });
  }

  // 4. Section 2: Decision Drivers
  const driversMatch = /^##\s+2\.\s+Decision\s+Drivers/m.exec(content);
  if (!driversMatch) {
    findings.push({
      rule_id: "DES-ADR-006",
      severity: "ERROR",
      message: "Missing required section: '## 2. Decision Drivers'",
      file_path: filename,
    });
  } else {
    const afterDrivers = content.slice(driversMatch.index);
    const driverItems = afterDrivers.match(/^-\s+(?:Driver\s+\d+:|.+)/gm) || [];
    if (driverItems.length < 2) {
      findings.push({
        rule_id: "DES-ADR-007",
        severity: "WARNING",
        message: "Decision Drivers section should define at least 2 concrete technical drivers / constraints",
        file_path: filename,
      });
    }
  }

  // 5. Section 3: Considered Options
  const optionsMatch = /^##\s+3\.\s+Considered\s+Options/m.exec(content);
  if (!optionsMatch) {
    findings.push({
      rule_id: "DES-ADR-008",
      severity: "ERROR",
      message: "Missing required section: '## 3. Considered Options'",
      file_path: filename,
    });
  } else {
    const hasOptionA = /###\s+Option\s+A\b/i.test(content);
    const hasOptionB = /###\s+Option\s+B\b/i.test(content);
    const hasUncontested = /\b(uncontested|single option|standard upgrade)\b/i.test(content);
    const hasChosenFlag = /\(Chosen\)|Chosen:|Selected:/i.test(content);

    if (!((hasOptionA && hasOptionB) || (hasOptionA && hasUncontested))) {
      findings.push({
        rule_id: "DES-ADR-009",
        severity: "ERROR",
        message: "Considered Options must explore at least Option A and Option B alternatives, or designate Option A as (Uncontested)",
        file_path: filename,
      });
    }
    if (!hasChosenFlag) {
      findings.push({
        rule_id: "DES-ADR-010",
        severity: "WARNING",
        message: "Considered Options should explicitly designate which option was chosen, e.g. '### Option B: ... *(Chosen)*'",
        file_path: filename,
      });
    }
  }

  // 6. Section 4: Decision Outcome & Invariants
  const outcomeMatch = /^##\s+4\.\s+Decision\s+Outcome/m.exec(content);
  if (!outcomeMatch) {
    findings.push({
      rule_id: "DES-ADR-011",
      severity: "ERROR",
      message: "Missing required section: '## 4. Decision Outcome & Architecture Specification'",
      file_path: filename,
    });
  } else {
    const invariantsMatch = /###\s+4\.2\.?\s+Invariants\s+&\s+Guarantees/i.exec(content);
    if (!invariantsMatch) {
      findings.push({
        rule_id: "DES-ADR-012",
        severity: "ERROR",
        message: "Missing subsection: '### 4.2. Invariants & Guarantees'",
        file_path: filename,
      });
    } else {
      const invariantsText = content.slice(invariantsMatch.index, invariantsMatch.index + 1500).toLowerCase();
      const requiredDomains: [string, string][] = [
        ["State & Consistency", "DES-ADR-013"],
        ["Concurrency", "DES-ADR-014"],
        ["Resilience", "DES-ADR-015"],
        ["Data & Migration", "DES-ADR-016"],
        ["Blast Radius", "DES-ADR-017"],
      ];
      for (const [domainLabel, ruleCode] of requiredDomains) {
        if (!invariantsText.includes(domainLabel.toLowerCase())) {
          findings.push({
            rule_id: ruleCode,
            severity: "WARNING",
            message: `Invariants & Guarantees should address Systems Inquiry domain: '${domainLabel}'`,
            file_path: filename,
          });
        }
      }
    }
  }

  // 7. Section 5: Consequences & Trade-offs
  const consequencesMatch = /^##\s+5\.\s+Consequences\s+&\s+Trade-offs/m.exec(content);
  if (!consequencesMatch) {
    findings.push({
      rule_id: "DES-ADR-018",
      severity: "ERROR",
      message: "Missing required section: '## 5. Consequences & Trade-offs'",
      file_path: filename,
    });
  } else {
    const chunk = content.slice(consequencesMatch.index, consequencesMatch.index + 800);
    if (!chunk.includes("Positive")) {
      findings.push({
        rule_id: "DES-ADR-019",
        severity: "WARNING",
        message: "Consequences section should explicitly document Positive Consequences",
        file_path: filename,
      });
    }
    if (!chunk.includes("Negative") && !content.includes("Technical Debt")) {
      findings.push({
        rule_id: "DES-ADR-020",
        severity: "WARNING",
        message: "Consequences section should explicitly document Negative Consequences / Accepted Technical Debt",
        file_path: filename,
      });
    }
  }

  // 8. Section 6: Downstream Verification Criteria
  const criteriaMatch = /^##\s+6\.\s+Downstream\s+Verification\s+Criteria/m.exec(content);
  if (!criteriaMatch) {
    findings.push({
      rule_id: "DES-ADR-021",
      severity: "ERROR",
      message: "Missing required section: '## 6. Downstream Verification Criteria (For review)'",
      file_path: filename,
    });
  } else {
    const checklistItems = content.slice(criteriaMatch.index).match(/^-\s+\[[ x]\]\s+.+/gm);
    if (!checklistItems || checklistItems.length === 0) {
      findings.push({
        rule_id: "DES-ADR-022",
        severity: "ERROR",
        message: "Downstream Verification Criteria must include actionable checklist items: '- [ ] Criterion'",
        file_path: filename,
      });
    }
  }

  const errors = findings.filter((f) => f.severity === "ERROR");
  return new ValidationResult(errors.length === 0, findings, {
    line_count: lines.length,
    findings_count: findings.length,
    errors: errors.length,
    warnings: findings.filter((f) => f.severity === "WARNING").length,
  });
}

export function validateOpenspecDir(changeDir: string): ValidationResult {
  const findings: Finding[] = [];
  const dirPath = path.resolve(changeDir);

  if (!fs.existsSync(dirPath) || !fs.statSync(dirPath).isDirectory()) {
    return new ValidationResult(false, [
      {
        rule_id: "DES-SPEC-000",
        severity: "ERROR",
        message: `Change directory does not exist: ${dirPath}`,
        file_path: dirPath,
      },
    ]);
  }

  // 1. proposal.md
  const proposalPath = path.join(dirPath, "proposal.md");
  if (!fs.existsSync(proposalPath) || !fs.statSync(proposalPath).isFile()) {
    findings.push({
      rule_id: "DES-SPEC-001",
      severity: "ERROR",
      message: "Missing required OpenSpec file: proposal.md",
      file_path: dirPath,
    });
  } else {
    const content = fs.readFileSync(proposalPath, "utf-8");
    if (!content.includes("Problem Statement")) {
      findings.push({
        rule_id: "DES-SPEC-002",
        severity: "ERROR",
        message: "proposal.md missing 'Problem Statement'",
        file_path: proposalPath,
      });
    }
    if (!content.includes("Proposed Changes")) {
      findings.push({
        rule_id: "DES-SPEC-003",
        severity: "ERROR",
        message: "proposal.md missing 'Proposed Changes'",
        file_path: proposalPath,
      });
    }
    if (!content.includes("Capabilities")) {
      findings.push({
        rule_id: "DES-SPEC-004",
        severity: "WARNING",
        message: "proposal.md missing 'Capabilities' section (Added/Modified/Removed)",
        file_path: proposalPath,
      });
    }
    if (!content.includes("Non-Goals") && !content.includes("Out of Scope")) {
      findings.push({
        rule_id: "DES-SPEC-005",
        severity: "WARNING",
        message: "proposal.md should define 'Non-Goals / Out of Scope' to prevent scope creep",
        file_path: proposalPath,
      });
    }
  }

  // 2. specs/ directory
  const specsDir = path.join(dirPath, "specs");
  if (!fs.existsSync(specsDir) || !fs.statSync(specsDir).isDirectory()) {
    findings.push({
      rule_id: "DES-SPEC-010",
      severity: "ERROR",
      message: "Missing required specs/ directory in OpenSpec change package",
      file_path: dirPath,
    });
  } else {
    const specFiles = fs.readdirSync(specsDir).filter((f) => f.endsWith(".md"));
    if (specFiles.length === 0) {
      findings.push({
        rule_id: "DES-SPEC-011",
        severity: "ERROR",
        message: "specs/ directory must contain at least one specification markdown file",
        file_path: specsDir,
      });
    } else {
      for (const specName of specFiles) {
        const specFile = path.join(specsDir, specName);
        const specContent = fs.readFileSync(specFile, "utf-8");

        // RFC 2119 check
        if (!RFC2119_PATTERN.test(specContent)) {
          findings.push({
            rule_id: "DES-SPEC-012",
            severity: "ERROR",
            message: `${specName}: Requirements must use RFC 2119 keywords (SHALL, MUST)`,
            file_path: specFile,
          });
        }
        // Gherkin scenario check
        if (!GHERKIN_WHEN_THEN.test(specContent)) {
          findings.push({
            rule_id: "DES-SPEC-013",
            severity: "WARNING",
            message: `${specName}: Specifications should include Gherkin scenarios (GIVEN/WHEN/THEN)`,
            file_path: specFile,
          });
        }
        // Capability Closure check
        if (!specContent.includes("Role Access Matrix") && !specContent.includes("Capability Closure")) {
          findings.push({
            rule_id: "DES-SPEC-014",
            severity: "WARNING",
            message: `${specName}: Specification should include Capability Closure (Role Access Matrix or Expectation Sweep)`,
            file_path: specFile,
          });
        }
      }
    }
  }

  // 3. design.md
  const designPath = path.join(dirPath, "design.md");
  if (!fs.existsSync(designPath) || !fs.statSync(designPath).isFile()) {
    findings.push({
      rule_id: "DES-SPEC-020",
      severity: "WARNING",
      message: "Missing design.md in OpenSpec change directory",
      file_path: dirPath,
    });
  } else {
    const content = fs.readFileSync(designPath, "utf-8");
    if (!content.includes("Invariants") && !content.includes("Guarantees")) {
      findings.push({
        rule_id: "DES-SPEC-021",
        severity: "WARNING",
        message: "design.md should document critical system Invariants & Guarantees",
        file_path: designPath,
      });
    }
  }

  // 4. tasks.md
  const tasksPath = path.join(dirPath, "tasks.md");
  if (!fs.existsSync(tasksPath) || !fs.statSync(tasksPath).isFile()) {
    findings.push({
      rule_id: "DES-SPEC-030",
      severity: "ERROR",
      message: "Missing required tasks.md in OpenSpec change directory",
      file_path: dirPath,
    });
  } else {
    const tasksContent = fs.readFileSync(tasksPath, "utf-8");
    const taskItems = tasksContent.match(/^-\s+\[[ x]\]\s+.+/gm);
    if (!taskItems || taskItems.length === 0) {
      findings.push({
        rule_id: "DES-SPEC-031",
        severity: "ERROR",
        message: "tasks.md must contain actionable checklist items matching '- [ ] Task'",
        file_path: tasksPath,
      });
    }
  }

  const errors = findings.filter((f) => f.severity === "ERROR");
  return new ValidationResult(errors.length === 0, findings, {
    change_name: path.basename(dirPath),
    findings_count: findings.length,
    errors: errors.length,
    warnings: findings.filter((f) => f.severity === "WARNING").length,
  });
}

export function validateInterviewRound(roundText: string): ValidationResult {
  const findings: Finding[] = [];

  // 1. Header
  const headerMatch = ROUND_HEADER_PATTERN.exec(roundText);
  if (!headerMatch) {
    findings.push({
      rule_id: "DES-FNT-001",
      severity: "ERROR",
      message: "Missing Frontier Round header. Expected: '### 🏛️ Round [N] — Design Frontier'",
    });
  }

  // 2. Questions
  const questions: string[] = [];
  let qm: RegExpExecArray | null;
  const qRegex = new RegExp(QUESTION_PATTERN.source, "gi");
  while ((qm = qRegex.exec(roundText)) !== null) {
    questions.push(qm[0]);
  }
  if (questions.length === 0) {
    findings.push({
      rule_id: "DES-FNT-002",
      severity: "ERROR",
      message: "Frontier Round must include at least one numbered question: '❓ **Q1** - **<Title>**:'",
    });
  }

  // 3. Recommended Stances
  const stances: string[] = [];
  let sm: RegExpExecArray | null;
  const sRegex = new RegExp(RECOMMENDED_STANCE_PATTERN.source, "gim");
  while ((sm = sRegex.exec(roundText)) !== null) {
    stances.push(sm[1]);
  }

  if (stances.length < questions.length) {
    findings.push({
      rule_id: "DES-FNT-003",
      severity: "ERROR",
      message: `Missing Recommended Stance for questions: found ${questions.length} questions but only ${stances.length} stance(s)`,
    });
  }

  // 4. Anti-Cheat: Reject vacuous stances
  for (let idx = 0; idx < stances.length; idx++) {
    const stance = stances[idx];
    const stanceClean = stance.trim().toLowerCase();
    if (stanceClean.length < 15) {
      findings.push({
        rule_id: "DES-FNT-004",
        severity: "ERROR",
        message: `Q${idx + 1} Recommended Stance is too brief/vacuous ('${stance}'). Must provide concrete architectural rationale.`,
      });
    }
    for (const kw of VACUOUS_STANCE_KEYWORDS) {
      if (stanceClean.includes(kw)) {
        findings.push({
          rule_id: "DES-FNT-005",
          severity: "ERROR",
          message: `Q${idx + 1} Recommended Stance uses evasive language ('${kw}'). Must adopt a definitive Principal Architect stance.`,
        });
        break;
      }
    }
  }

  const errors = findings.filter((f) => f.severity === "ERROR");
  return new ValidationResult(errors.length === 0, findings, {
    round_number: headerMatch ? headerMatch[1] : null,
    question_count: questions.length,
    stance_count: stances.length,
  });
}

export function validateConfirmationGate(
  turnOutput: string,
  filesCreatedOrModified: string[]
): ValidationResult {
  const findings: Finding[] = [];
  const isGatePrompt = /capture our shared architectural understanding|confirm this design frontier|explicitly confirm this architecture/i.test(
    turnOutput
  );

  if (isGatePrompt) {
    const mutatedSpecFiles = filesCreatedOrModified.filter(
      (f) => f.includes("docs/adr") || f.includes("openspec/")
    );
    if (mutatedSpecFiles.length > 0) {
      findings.push({
        rule_id: "DES-GATE-001",
        severity: "ERROR",
        message: `Confirmation Gate violated! Mutated ${mutatedSpecFiles.length} spec file(s) before user confirmation: ${mutatedSpecFiles.join(", ")}`,
      });
    }
  }

  const errors = findings.filter((f) => f.severity === "ERROR");
  return new ValidationResult(errors.length === 0, findings, {
    is_confirmation_gate: isGatePrompt,
    mutated_files_count: filesCreatedOrModified.length,
  });
}

export class FrontierDAG {
  decisions: Record<string, { id: string; title: string; dependencies: string[] }> = {};
  resolved: Record<string, string> = {};

  addDecision(decisionId: string, title: string, dependencies?: string[]): void {
    this.decisions[decisionId] = {
      id: decisionId,
      title,
      dependencies: dependencies || [],
    };
  }

  getFrontier(): { id: string; title: string; dependencies: string[] }[] {
    const frontier: { id: string; title: string; dependencies: string[] }[] = [];
    for (const [decId, data] of Object.entries(this.decisions)) {
      if (this.resolved[decId] !== undefined) {
        continue;
      }
      const depsMet = data.dependencies.every((dep) => this.resolved[dep] !== undefined);
      if (depsMet) {
        frontier.push(data);
      }
    }
    return frontier;
  }

  resolve(decisionId: string, choice: string): void {
    if (!this.decisions[decisionId]) {
      throw new Error(`Unknown decision: ${decisionId}`);
    }
    this.resolved[decisionId] = choice;
  }

  isComplete(): boolean {
    return Object.keys(this.resolved).length === Object.keys(this.decisions).length && Object.keys(this.decisions).length > 0;
  }
}

export function validateRepository(
  repoRoot: string,
  adrPath?: string | null,
  changeName?: string | null
): ValidationResult {
  const root = path.resolve(repoRoot);
  const allFindings: Finding[] = [];
  let adrsChecked = 0;
  let specsChecked = 0;

  // 1. ADR validation
  let adrs: string[] = [];
  if (adrPath) {
    if (fs.existsSync(adrPath) && fs.statSync(adrPath).isFile()) {
      adrs = [adrPath];
    }
  } else {
    const adrsDir = path.join(root, "docs", "adr");
    if (fs.existsSync(adrsDir) && fs.statSync(adrsDir).isDirectory()) {
      adrs = fs
        .readdirSync(adrsDir)
        .filter((f) => f.startsWith("ADR-") && f.endsWith(".md"))
        .map((f) => path.join(adrsDir, f));
    }
  }

  for (const adrFile of adrs.sort()) {
    adrsChecked++;
    const content = fs.readFileSync(adrFile, "utf-8");
    const rel = path.relative(root, adrFile);
    const res = validateAdrContent(content, rel);
    allFindings.push(...res.findings);
  }

  // 2. OpenSpec validation
  const changesDir = path.join(root, "openspec", "changes");
  let targetChanges: string[] = [];
  if (changeName) {
    const cPath = path.join(changesDir, changeName);
    if (fs.existsSync(cPath) && fs.statSync(cPath).isDirectory()) {
      targetChanges = [cPath];
    }
  } else if (fs.existsSync(changesDir) && fs.statSync(changesDir).isDirectory()) {
    targetChanges = fs
      .readdirSync(changesDir)
      .filter((f) => !f.startsWith("."))
      .map((f) => path.join(changesDir, f))
      .filter((p) => fs.statSync(p).isDirectory());
  }

  for (const cDir of targetChanges.sort()) {
    specsChecked++;
    const res = validateOpenspecDir(cDir);
    allFindings.push(...res.findings);
  }

  const errors = allFindings.filter((f) => f.severity === "ERROR");
  return new ValidationResult(errors.length === 0, allFindings, {
    adrs_checked: adrsChecked,
    specs_checked: specsChecked,
    error_count: errors.length,
    warning_count: allFindings.filter((f) => f.severity === "WARNING").length,
  });
}

export function main(argv: string[] = process.argv.slice(2)): number {
  let repoPath = ".";
  let adrPath: string | undefined;
  let changeName: string | undefined;
  let jsonOutput = false;
  let failOn: "error" | "warning" = "error";

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--path") {
      repoPath = argv[++i];
    } else if (arg.startsWith("--path=")) {
      repoPath = arg.split("=")[1];
    } else if (arg === "--adr") {
      adrPath = argv[++i];
    } else if (arg.startsWith("--adr=")) {
      adrPath = arg.split("=")[1];
    } else if (arg === "--change") {
      changeName = argv[++i];
    } else if (arg.startsWith("--change=")) {
      changeName = arg.split("=")[1];
    } else if (arg === "--json") {
      jsonOutput = true;
    } else if (arg === "--fail-on") {
      const next = argv[++i];
      if (next === "error" || next === "warning") {
        failOn = next;
      }
    } else if (arg.startsWith("--fail-on=")) {
      const val = arg.split("=")[1];
      if (val === "error" || val === "warning") {
        failOn = val;
      }
    }
  }

  const root = path.resolve(repoPath);
  const result = validateRepository(root, adrPath, changeName);

  if (jsonOutput) {
    console.log(JSON.stringify(result.to_dict(), null, 2));
  } else {
    console.log(`Systems Design Validation: ${result.passed ? "PASSED" : "FAILED"}`);
    console.log(
      `ADRs Checked: ${result.metrics.adrs_checked ?? 0}, OpenSpec Changes Checked: ${result.metrics.specs_checked ?? 0}`
    );
    console.log(
      `Errors: ${result.metrics.error_count ?? 0}, Warnings: ${result.metrics.warning_count ?? 0}`
    );
    if (result.findings.length > 0) {
      console.log("\nFindings:");
      for (const f of result.findings) {
        const loc = f.file_path ? ` [${f.file_path}:${f.line_number ?? 1}]` : "";
        console.log(`  • [${f.severity}] ${f.rule_id}${loc}: ${f.message}`);
      }
    }
  }

  if (failOn === "warning") {
    return result.passed && result.warnings.length === 0 ? 0 : 1;
  }
  return result.passed ? 0 : 1;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const exitCode = main();
  process.exit(exitCode);
}
