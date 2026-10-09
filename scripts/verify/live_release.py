#!/usr/bin/env python3
"""Fail closed unless the candidate has a complete live tool-loop report.

Run only on artifacts from a trusted evaluation job. JSON is not an attestation.
"""
import argparse
import json
from pathlib import Path

REQUIRED_CASES = {'tdd-average', 'debug-average', 'review-average', 'ship-average'}
SHIP_CHECKS = {'design_approved_before_code', 'resumed_after_approval', 'stale_delivery_rejected',
               'fresh_delivery_after_drift', 'archived_through_runtime', 'archive_exists',
               'red_before_edit_before_green', 'independent_acceptance', 'config_preserved', 'host_edit_preserved'}
COMMON_CHECKS = {'completed', 'no_symlinks', 'trace_integrity', 'tools_observed', 'notes_preserved'}
IMPLEMENTATION_CHECKS = {'red_before_edit_before_green', 'test_edited', 'existing_tests_preserved',
                         'scope_preserved', 'independent_acceptance'}
CASE_CHECKS = {
    'tdd-average': COMMON_CHECKS | IMPLEMENTATION_CHECKS,
    'debug-average': COMMON_CHECKS | IMPLEMENTATION_CHECKS,
    'review-average': COMMON_CHECKS | {'source_read', 'contract_read', 'no_edits', 'defect_reported'},
    'ship-average': COMMON_CHECKS | IMPLEMENTATION_CHECKS | SHIP_CHECKS,
}


def validate(report, commit, model):
    errors = []
    if report.get('mode') != 'live-tool-loop' or report.get('host') != 'anthropic-tool-loop':
        errors.append('A real supported tool-loop report is required')
    if report.get('suite_commit') != commit or report.get('dirty_checkout') is not False:
        errors.append('Evidence must match the clean candidate commit')
    if not model or report.get('model_requested') != model:
        errors.append('Evidence must use the explicitly approved model')
    if report.get('passed') is not True or report.get('status') != 'pass':
        errors.append('Live evaluation did not pass')
    results = report.get('results')
    if not isinstance(results, list) or not all(isinstance(r, dict) for r in results):
        return errors + ['Malformed case results']
    ids = [r.get('case') for r in results]
    if len(ids) != len(REQUIRED_CASES) or any(not isinstance(i, str) for i in ids) or set(ids) != REQUIRED_CASES:
        errors.append('Missing, duplicate, or unexpected live cases')
    for result in results:
        checks = result.get('checks')
        if result.get('passed') is not True or result.get('complete') is not True or result.get('error'):
            errors.append(f"Incomplete or failed case: {result.get('case')}")
        if not isinstance(checks, dict) or not checks or any(v is not True for v in checks.values()):
            errors.append(f"Missing or failed observations: {result.get('case')}")
        case = result.get('case')
        required = CASE_CHECKS.get(case, set()) if isinstance(case, str) else set()
        if not isinstance(checks, dict) or not required.issubset(checks):
            errors.append(f'Required observations are incomplete: {case}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text())
        errors = validate(report, args.commit, args.model) if isinstance(report, dict) else ['Report must be an object']
    except (OSError, ValueError) as exc:
        errors = [str(exc)]
    print(json.dumps({'passed': not errors, 'errors': errors}, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
