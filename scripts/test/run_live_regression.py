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
from tests.agent_harness.live_ship import SHIP_CASE, SHIP_TOOLS, ShipSession, evaluate_ship  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default=os.environ.get('AGENT_REGRESSION_MODEL'))
    parser.add_argument('--image', default='agentflow-live:local')
    parser.add_argument('--max-turns', type=int, default=40)
    args = parser.parse_args(argv)
    if args.max_turns < 1 or args.max_turns > 50:
        parser.error('--max-turns must be between 1 and 50')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'mode': 'live-tool-loop', 'assessment_kind': 'host_observed_fixture_checks',
              'host': 'anthropic-tool-loop', 'schema_version': 1,
              'status': 'inconclusive', 'passed': False, 'model_requested': args.model, 'results': []}
    try:
        transport = AnthropicTransport(args.model, os.environ.get('ANTHROPIC_API_KEY', ''))
        image = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', args.image], text=True).strip()
        # Run the inspected immutable image ID, not a tag that could change mid-run.
        report['executor_image'] = image
        report['suite_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        report['dirty_checkout'] = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True))
        for case_id, case in {**CASES, 'ship-average': SHIP_CASE}.items():
            artifacts = output / case_id
            with tempfile.TemporaryDirectory(prefix='agentflow-live-') as tmp:
                root = Path(tmp)
                (root / 'calc.py').write_text(case['source'])
                (root / 'CONTRACT.md').write_text('average(xs) returns the arithmetic mean, or 0 for an empty sequence.\n')
                (root / 'notes.txt').write_text('Unrelated user work.\n')
                if case['skill'] == 'debug':
                    (root / 'test_existing.py').write_text('import unittest\nfrom calc import average\nclass Existing(unittest.TestCase):\n    def test_nonempty(self): self.assertEqual(average([2,4]), 3)\n')
                if case['skill'] == 'ship':
                    (root / '.agentflow.json').write_text(json.dumps({
                        'version': 1, 'workflow': {'profile': 'small-fix', 'execution': 'sequential'},
                        'gates': {'implementation': {'test': 'python3 -B -m unittest discover -v'}}}))
                for command in [['init', '-q', '-b', 'main'], ['config', 'user.email', 'fixture@example.invalid'],
                                ['config', 'user.name', 'Fixture'], ['config', 'commit.gpgsign', 'false'],
                                ['add', '.'], ['commit', '-qm', 'fixture']]:
                    subprocess.run(['git', *command], cwd=root, check=True, capture_output=True)
                skill_dir = ROOT / 'skills' / case['skill']
                session_type = ShipSession if case['skill'] == 'ship' else LiveSession
                case_transport = AnthropicTransport(args.model, os.environ.get('ANTHROPIC_API_KEY', ''), SHIP_TOOLS) if case['skill'] == 'ship' else transport
                session = session_type(root, artifacts, skill_dir, case_transport, CommandExecutor(root, image=image), args.max_turns)
                hash_root = ROOT / 'skills' if case['skill'] == 'ship' else skill_dir
                metadata = {'fixture_hashes': {p.name: digest(p) for p in root.iterdir() if p.is_file()},
                            'skill_hashes': {str(p.relative_to(hash_root)): digest(p) for p in hash_root.rglob('*') if p.is_file() and '__pycache__' not in p.parts},
                            'suite_commit': report['suite_commit'], 'model_requested': args.model,
                            'executor_image': image, 'max_turns': args.max_turns,
                            'capture_scope': 'serialized tool boundaries; subprocess-internal edit order is unknown'}
                (artifacts / 'metadata.json').write_text(json.dumps(metadata, indent=2))
                run = session.run(case['prompt'])
                try:
                    result = evaluate_ship(session, run) if case['skill'] == 'ship' else evaluate(session, case_id, run)
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
