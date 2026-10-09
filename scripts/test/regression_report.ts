export type RegressionResult = { skill: string; scenario_id: string; scenario_description: string; passed: boolean; checks_total: number; checks_passed: number; failures: string[]; elapsed_ms: number };
export type RegressionReport = { passed: boolean; total: number; n_passed: number; n_failed: number; pass_rate: number | null; assessment_kind: string; behavior_verified: boolean; status: string; results: RegressionResult[]; summary?: string };

export function formatMarkdownReport(report: RegressionReport, mode: string): string {
  const assessment = report.behavior_verified ? `\`${report.assessment_kind}\` (causal invariants independently proven via execution trace)` : `\`${report.assessment_kind}\`; behavior is not independently verified`;
  const lines = ['# Response Contract Report', '', `- **Execution Mode**: \`${mode}\``, `- **Assessment**: ${assessment}`, `- **Status**: ${report.status.toUpperCase()}`, `- **Total Scenarios**: ${report.total}`, `- **Passed**: ${report.n_passed}`, `- **Failed**: ${report.n_failed}`, '', '## Scenario Breakdown', '', '| Skill | Scenario ID | Description | Checks | Status |', '|---|---|---|---|---|'];
  for (const result of report.results) lines.push(`| \`${result.skill}\` | \`${result.scenario_id}\` | ${result.scenario_description} | ${result.checks_passed}/${result.checks_total} | ${result.passed ? '✅ PASS' : '❌ FAIL'} |`);
  if (report.n_failed > 0) { lines.push('', '## Failure Details', ''); for (const result of report.results.filter((r) => !r.passed)) lines.push(`### ❌ \`${result.scenario_id}\``, `**Description**: ${result.scenario_description}\n`, '**Failed Checks:**', ...result.failures.map((failure) => `- ✗ ${failure}`), ''); }
  return lines.join('\n');
}

export function reportJson(report: RegressionReport, mode: string) { return { passed: report.passed, total: report.total, n_passed: report.n_passed, n_failed: report.n_failed, pass_rate: report.pass_rate, mode, assessment_kind: report.assessment_kind, behavior_verified: report.behavior_verified, status: report.status, results: report.results.map(({ scenario_id, scenario_description, skill, passed, checks_total, checks_passed, failures, elapsed_ms }) => ({ scenario_id, description: scenario_description, skill, passed, checks_total, checks_passed, failures, elapsed_ms })) }; }
