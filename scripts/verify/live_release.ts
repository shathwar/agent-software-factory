#!/usr/bin/env bun
/** Fail closed unless the candidate has a complete live tool-loop report. */

export const REQUIRED_CASES = new Set([
  'tdd-average', 'debug-average', 'review-average', 'review-average-clean', 'ship-average',
]);
const COMMON_CHECKS = new Set(['completed', 'no_symlinks', 'trace_integrity', 'tools_observed', 'notes_preserved']);
const IMPLEMENTATION_CHECKS = new Set(['red_before_edit_before_green', 'test_edited', 'existing_tests_preserved', 'scope_preserved', 'independent_acceptance']);
const REVIEW_CHECKS = new Set([...COMMON_CHECKS, 'source_read', 'contract_read', 'no_edits', 'review_schema_valid', 'review_oracle_executed', 'review_verdict_correct', 'review_findings_grounded']);
export const CASE_CHECKS: Record<string, Set<string>> = {
  'tdd-average': new Set([...COMMON_CHECKS, ...IMPLEMENTATION_CHECKS]),
  'debug-average': new Set([...COMMON_CHECKS, ...IMPLEMENTATION_CHECKS]),
  'review-average': REVIEW_CHECKS,
  'review-average-clean': REVIEW_CHECKS,
  'ship-average': new Set([...COMMON_CHECKS, ...IMPLEMENTATION_CHECKS, 'design_approved_before_code', 'resumed_after_approval', 'stale_delivery_rejected', 'fresh_delivery_after_drift', 'archived_through_runtime', 'archive_exists', 'config_preserved', 'host_edit_preserved']),
};

export function validate(report: any, commit: string, model: string): string[] {
  const errors: string[] = [];
  if (report?.mode !== 'live-tool-loop' || report?.host !== 'anthropic-tool-loop') errors.push('A real supported tool-loop report is required');
  if (report?.suite_commit !== commit || report?.dirty_checkout !== false) errors.push('Evidence must match the clean candidate commit');
  if (!model || report?.model_requested !== model) errors.push('Evidence must use the explicitly approved model');
  if (report?.passed !== true || report?.status !== 'pass') errors.push('Live evaluation did not pass');
  const results = report?.results;
  if (!Array.isArray(results) || !results.every((r) => r && typeof r === 'object')) return [...errors, 'Malformed case results'];
  const ids = results.map((r) => r.case);
  if (ids.length !== REQUIRED_CASES.size || ids.some((id) => typeof id !== 'string') || new Set(ids).size !== REQUIRED_CASES.size || ![...REQUIRED_CASES].every((id) => new Set(ids).has(id))) errors.push('Missing, duplicate, or unexpected live cases');
  for (const result of results) {
    const checks = result.checks;
    if (result.passed !== true || result.complete !== true || result.error) errors.push(`Incomplete or failed case: ${result.case}`);
    if (!checks || typeof checks !== 'object' || !Object.keys(checks).length || Object.values(checks).some((v) => v !== true)) errors.push(`Missing or failed observations: ${result.case}`);
    const required = typeof result.case === 'string' ? CASE_CHECKS[result.case] ?? new Set<string>() : new Set<string>();
    if (!checks || typeof checks !== 'object' || [...required].some((key) => checks[key] !== true)) errors.push(`Required observations are incomplete: ${result.case}`);
  }
  return errors;
}

if (import.meta.main) {
  const [reportPath, ...args] = Bun.argv.slice(2);
  const commit = args[args.indexOf('--commit') + 1];
  const model = args[args.indexOf('--model') + 1];
  let errors: string[];
  try {
    const report = await Bun.file(reportPath).json();
    errors = report && typeof report === 'object' ? validate(report, commit, model) : ['Report must be an object'];
  } catch (error) { errors = [String(error instanceof Error ? error.message : error)]; }
  console.log(JSON.stringify({ passed: errors.length === 0, errors }, null, 2));
  process.exit(errors.length ? 1 : 0);
}
