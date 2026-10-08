#!/usr/bin/env python3
"""Run real tool-using agents; requires explicit model, credentials and Docker."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from tests.agent_harness.live import AnthropicTransport, CASES, CommandExecutor, LiveSession, digest, evaluate  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default=os.environ.get('AGENT_REGRESSION_MODEL'))
    parser.add_argument('--image', default='agentflow-live:local')
    parser.add_argument('--max-turns', type=int, default=20)
    args = parser.parse_args(argv)
    if args.max_turns < 1 or args.max_turns > 50:
        parser.error('--max-turns must be between 1 and 50')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'mode': 'live-tool-loop', 'assessment_kind': 'host_observed_fixture_checks',
              'status': 'inconclusive', 'passed': False, 'model_requested': args.model, 'results': []}
    try:
        transport = AnthropicTransport(args.model, os.environ.get('ANTHROPIC_API_KEY', ''))
        image = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', args.image], text=True).strip()
        # Run the inspected immutable image ID, not a tag that could change mid-run.
        report['executor_image'] = image
        report['suite_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        report['dirty_checkout'] = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True))
        for case_id, case in CASES.items():
            artifacts = output / case_id
            with tempfile.TemporaryDirectory(prefix='agentflow-live-') as tmp:
                root = Path(tmp)
                (root / 'calc.py').write_text(case['source'])
                (root / 'CONTRACT.md').write_text('average(xs) returns the arithmetic mean, or 0 for an empty sequence.\n')
                (root / 'notes.txt').write_text('Unrelated user work.\n')
                if case['skill'] == 'debug':
                    (root / 'test_existing.py').write_text('import unittest\nfrom calc import average\nclass Existing(unittest.TestCase):\n    def test_nonempty(self): self.assertEqual(average([2,4]), 3)\n')
                for command in [['init', '-q'], ['config', 'user.email', 'fixture@example.invalid'],
                                ['config', 'user.name', 'Fixture'], ['config', 'commit.gpgsign', 'false'],
                                ['add', '.'], ['commit', '-qm', 'fixture']]:
                    subprocess.run(['git', *command], cwd=root, check=True, capture_output=True)
                skill_dir = ROOT / 'skills' / case['skill']
                session = LiveSession(root, artifacts, skill_dir, transport, CommandExecutor(root, image=image), args.max_turns)
                metadata = {'fixture_hashes': {p.name: digest(p) for p in root.iterdir() if p.is_file()},
                            'skill_hashes': {str(p.relative_to(skill_dir)): digest(p) for p in skill_dir.rglob('*') if p.is_file() and '__pycache__' not in p.parts},
                            'suite_commit': report['suite_commit'], 'model_requested': args.model,
                            'executor_image': image, 'max_turns': args.max_turns,
                            'capture_scope': 'serialized tool boundaries; subprocess-internal edit order is unknown'}
                (artifacts / 'metadata.json').write_text(json.dumps(metadata, indent=2))
                run = session.run(case['prompt'])
                try:
                    result = evaluate(session, case_id, run)
                except Exception as exc:
                    result = {'case': case_id, 'passed': False, 'error': f'{type(exc).__name__}: {exc}'}
                (artifacts / 'result.json').write_text(json.dumps(result, indent=2))
                report['results'].append(result)
                (output / 'report.json').write_text(json.dumps(report, indent=2))
        report['passed'] = bool(report['results']) and all(r['passed'] for r in report['results'])
        report['status'] = 'pass' if report['passed'] else 'fail'
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
