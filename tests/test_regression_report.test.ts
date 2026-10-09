import { expect, test } from 'bun:test';
import { formatMarkdownReport, reportJson, type RegressionReport } from '../scripts/test/regression_report';

const sample: RegressionReport = { passed: false, total: 1, n_passed: 0, n_failed: 1, pass_rate: 0, assessment_kind: 'stub_response_contract', behavior_verified: false, status: 'failed', results: [{ skill: 'review', scenario_id: 'review-clean', scenario_description: 'clean report', passed: false, checks_total: 2, checks_passed: 1, failures: ['missing verdict'], elapsed_ms: 4 }] };
test('formats regression reports compatibly', () => { const markdown = formatMarkdownReport(sample, 'stub'); expect(markdown).toContain('`stub`'); expect(markdown).toContain('1/2'); expect(markdown).toContain('missing verdict'); expect(reportJson(sample, 'stub').results[0].description).toBe('clean report'); });
