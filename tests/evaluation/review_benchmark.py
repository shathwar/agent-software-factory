"""Seeded review benchmark with withheld answers and explicit external adjudication.

Provision only the source and contract into an agent workspace. Score its report
after a separate evaluator maps finding IDs to known defects (or null for noise).
This runner measures supplied observations; it never substitutes canned reviews.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

STAGES = ['SpecAlignment', 'Correctness', 'Concurrency', 'Failure/Resilience',
          'Simplicity', 'Maintainability', 'Reuse', 'Performance', 'SOLID', 'Patterns']
CASES = {
    'empty-average': {
        'stage': 'Correctness', 'contract': 'average([]) returns 0; other inputs return their arithmetic mean.',
        'buggy': 'def average(values):\n    return sum(values) / len(values)\n',
        'clean': 'def average(values):\n    return sum(values) / len(values) if values else 0\n',
        'line': 2, 'defect': 'empty-input-division',
        'oracle': 'assert average([]) == 0\nassert average([2, 4]) == 3\n',
    },
    'expiry-boundary': {
        'stage': 'SpecAlignment', 'contract': 'A token is valid strictly before its expiry timestamp.',
        'buggy': 'def valid(now, expires):\n    return now <= expires\n',
        'clean': 'def valid(now, expires):\n    return now < expires\n',
        'line': 2, 'defect': 'inclusive-expiry',
        'oracle': 'assert not valid(10, 10)\nassert valid(9, 10)\n',
    },
    'stale-write': {
        'stage': 'Concurrency', 'contract': 'Reject updates whose expected version is stale; preserve the current value.',
        'buggy': 'def update(state, expected_version, value):\n    state.update(version=expected_version + 1, value=value)\n    return True\n',
        'clean': 'def update(state, expected_version, value):\n    if state["version"] != expected_version:\n        return False\n    state.update(version=expected_version + 1, value=value)\n    return True\n',
        'line': 2, 'defect': 'stale-writer-overwrite',
        'oracle': 'state = {"version": 1, "value": "old"}\nassert update(state, 1, "first")\nassert not update(state, 1, "stale")\nassert state["value"] == "first"\n',
    },
    'retry-exhaustion': {
        'stage': 'Failure/Resilience', 'contract': 'Try the operation at most three times. Propagate OSError when all attempts fail.',
        'buggy': 'def fetch(operation):\n    for _ in range(3):\n        try:\n            return operation()\n        except OSError:\n            pass\n    return None\n',
        'clean': 'def fetch(operation):\n    for attempt in range(3):\n        try:\n            return operation()\n        except OSError:\n            if attempt == 2:\n                raise\n',
        'line': 7, 'defect': 'silent-exhaustion',
        'oracle': 'calls = []\ndef fail():\n    calls.append(1)\n    raise OSError("offline")\ntry:\n    fetch(fail)\nexcept OSError:\n    pass\nelse:\n    raise AssertionError("failure swallowed")\nassert len(calls) == 3\n',
    },
    'batch-fetch': {
        'stage': 'Performance', 'contract': 'Fetch all requested IDs in one store call, including an empty list.',
        'buggy': 'def load(store, ids):\n    return [store.fetch_many([key])[0] for key in ids]\n',
        'clean': 'def load(store, ids):\n    return store.fetch_many(ids)\n',
        'line': 2, 'defect': 'per-item-roundtrip',
        'oracle': 'class Store:\n    calls = 0\n    def fetch_many(self, ids):\n        self.calls += 1\n        return list(ids)\ns = Store()\nassert load(s, [1, 2, 3]) == [1, 2, 3]\nassert s.calls == 1\n',
    },
}


def case_data(case_id):
    name, separator, variant = case_id.rpartition(':')
    if not separator or name not in CASES or variant not in ('buggy', 'clean'):
        raise ValueError('Expected a registered case ID ending in :buggy or :clean')
    return CASES[name], variant


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def provision(case_id, destination):
    case, variant = case_data(case_id)
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=False)
    (root / 'subject.py').write_text(case[variant], encoding='utf-8')
    (root / 'CONTRACT.md').write_text(case['contract'] + '\n', encoding='utf-8')
    return {'case_id': case_id, 'workspace': str(root), 'source_sha256': digest(case[variant])}


def validate_submission(report, root):
    # Keep this import local so provisioning does not require an installed package.
    from ship.tools.review import validate_report
    errors = validate_report(report)
    if errors:
        return errors
    if report['status'] != 'complete' or 'subject.py' not in report['coverage']:
        errors.append('A complete review must explicitly cover subject.py')
    for finding in report['findings']:
        if finding['file'] != 'subject.py':
            errors.append('Benchmark findings must cite subject.py')
            continue
        parts = finding['line'].replace('L', '').split('-')
        first, last = int(parts[0]), int(parts[-1])
        lines = (root / 'subject.py').read_text().splitlines()
        if first < 1 or last > len(lines):
            errors.append('Finding line range is outside the source')
        elif ' '.join(finding['evidence'].split()) not in ' '.join('\n'.join(lines[first-1:last]).split()):
            errors.append('Evidence is absent from the cited line range')
    return errors


def score(case_id, root, report, adjudication):
    case, variant = case_data(case_id)
    root = Path(root)
    if (root / 'subject.py').is_symlink() or (root / 'subject.py').read_text() != case[variant]:
        raise ValueError('Benchmark source changed or is not the selected fixture')
    if (root / 'CONTRACT.md').is_symlink() or (root / 'CONTRACT.md').read_text() != case['contract'] + '\n':
        raise ValueError('Benchmark contract changed')
    errors = validate_submission(report, root)
    if errors:
        raise ValueError('; '.join(errors))
    if not isinstance(adjudication, dict):
        raise ValueError('Separate adjudication is required')
    evaluator = adjudication.get('evaluator')
    if not isinstance(evaluator, str) or not evaluator.strip() or evaluator == report['reviewer']:
        raise ValueError('Name a separate evaluator; identity is caller-reported')
    report_hash = digest(json.dumps(report, sort_keys=True, allow_nan=False))
    if adjudication.get('report_sha256') != report_hash:
        raise ValueError('Adjudication is not bound to this exact report')
    matches = adjudication.get('matches')
    ids = {f['id'] for f in report['findings']}
    if not isinstance(matches, dict) or set(matches) != ids:
        raise ValueError('Adjudicate every finding exactly once, including false positives')
    expected = {case['defect']} if variant == 'buggy' else set()
    matched = set()
    for finding in report['findings']:
        defect = matches[finding['id']]
        if defect is None:
            continue
        if not isinstance(defect, str) or defect not in expected:
            raise ValueError('Adjudication references an unknown defect for this case')
        first, _, last = finding['line'].replace('L', '').partition('-')
        if finding['category'] != case['stage'] or not int(first) <= case['line'] <= int(last or first):
            raise ValueError('Adjudicated finding does not cover the defect stage and location')
        matched.add(defect)
    tp = len(matched)
    fp = len(ids) - tp  # Duplicate findings cannot inflate recall or precision.
    fn = len(expected - matched)
    return {'case_id': case_id, 'stage': case['stage'], 'true_positives': tp,
            'false_positives': fp, 'false_negatives': fn,
            'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'status': 'passed' if fp == fn == 0 else 'failed',
            'source_sha256': digest(case[variant]), 'report_sha256': report_hash,
            'evaluator': evaluator, 'measurement_kind': 'adjudicated_report',
            'limitations': ['Semantic matches are supplied by an external evaluator, not authenticated.',
                            'This result does not prove that an agent executed the skill.']}


def summarize(results):
    ids = [r['case_id'] for r in results]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate case results; summarize repeated trials separately')
    expected = {f'{name}:{variant}' for name in CASES for variant in ('buggy', 'clean')}
    if set(ids) - expected:
        raise ValueError('Unknown case result')
    for result in results:
        case, variant = case_data(result['case_id'])
        if result['stage'] != case['stage'] or any(type(result[k]) is not int or result[k] < 0
            for k in ('true_positives', 'false_positives', 'false_negatives')):
            raise ValueError('Invalid stage or counts')
        if result['true_positives'] + result['false_negatives'] != int(variant == 'buggy'):
            raise ValueError('Counts do not match the number of seeded defects')
        expected_status = 'failed' if result['false_positives'] or result['false_negatives'] else 'passed'
        if result['status'] != expected_status:
            raise ValueError('Status contradicts measured counts')
    missing = sorted(expected - set(ids))
    stages = {}
    for stage in STAGES:
        rows = [r for r in results if r['stage'] == stage]
        tp, fp, fn = (sum(r[k] for r in rows) for k in ('true_positives', 'false_positives', 'false_negatives'))
        stages[stage] = {'cases': len(rows), 'status': 'unrun' if not rows else ('failed' if fp or fn else ('passed' if len(rows) == 2 else 'inconclusive')),
                         'precision': tp / (tp + fp) if tp + fp else None,
                         'recall': tp / (tp + fn) if tp + fn else None}
    return {'status': 'failed' if any(r['status'] == 'failed' for r in results) else ('inconclusive' if missing else 'passed'),
            'missing_cases': missing, 'stages': stages,
            'scope': 'Five seeded stages and matched clean controls; other stages remain unrun.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('list')
    make = sub.add_parser('provision')
    make.add_argument('case_id')
    make.add_argument('destination', type=Path)
    grade = sub.add_parser('score')
    grade.add_argument('case_id')
    grade.add_argument('workspace', type=Path)
    grade.add_argument('report', type=Path)
    grade.add_argument('adjudication', type=Path)
    summary = sub.add_parser('summarize')
    summary.add_argument('results', nargs='+', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == 'list':
            result = [f'{name}:{variant}' for name in CASES for variant in ('buggy', 'clean')]
        elif args.action == 'provision':
            result = provision(args.case_id, args.destination)
        elif args.action == 'summarize':
            result = summarize([json.loads(p.read_text()) for p in args.results])
        else:
            result = score(args.case_id, args.workspace, json.loads(args.report.read_text()), json.loads(args.adjudication.read_text()))
        print(json.dumps(result, indent=2, allow_nan=False))
        return int(isinstance(result, dict) and result.get('status') in ('failed', 'inconclusive'))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
