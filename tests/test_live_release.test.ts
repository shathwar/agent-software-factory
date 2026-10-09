import { describe, expect, test } from 'bun:test';
import { CASE_CHECKS, REQUIRED_CASES, validate } from '../scripts/verify/live_release';

const report = () => ({ mode: 'live-tool-loop', host: 'anthropic-tool-loop', suite_commit: 'candidate', dirty_checkout: false, model_requested: 'approved', passed: true, status: 'pass', results: [...REQUIRED_CASES].map((caseName) => ({ case: caseName, passed: true, complete: true, error: null, checks: Object.fromEntries([...CASE_CHECKS[caseName]].map((key) => [key, true])) })) });

describe('live release evidence', () => {
  test('accepts complete evidence', () => expect(validate(report(), 'candidate', 'approved')).toEqual([]));
  test('rejects stale, dirty, wrong-model, and incomplete evidence', () => {
    for (const [field, value] of [['suite_commit', 'old'], ['dirty_checkout', true], ['model_requested', 'other'], ['passed', false]] as const) {
      const altered: any = structuredClone(report()); altered[field] = value; expect(validate(altered, 'candidate', 'approved').length).toBeGreaterThan(0);
    }
    const altered: any = structuredClone(report()); altered.results.pop(); expect(validate(altered, 'candidate', 'approved').length).toBeGreaterThan(0);
    const failed: any = structuredClone(report()); failed.results[0].checks.completed = false; expect(validate(failed, 'candidate', 'approved').length).toBeGreaterThan(0);
  });
});
