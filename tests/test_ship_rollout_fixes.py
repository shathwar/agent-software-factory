"""Regression checks for rollout fixes; scripted models are not live evidence."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.verify.live_release import REQUIRED_CASES, CASE_CHECKS, validate
from ship.lifecycle.capabilities import CapabilityManager, ExecutionRing
from ship.lifecycle.policy import AllowedConfig, EnterprisePolicy, EnterprisePolicyEngine
from ship.lifecycle.turns import get_next_turn_contract
from tests.agent_harness.live import CommandExecutor
from tests.agent_harness.live_ship import ShipSession, evaluate_ship
from tests.test_live_agent_harness import call, response

ROOT = Path(__file__).resolve().parents[1]


class ReleaseEvidenceTests(unittest.TestCase):
    def report(self):
        return {'mode': 'live-tool-loop', 'host': 'anthropic-tool-loop', 'suite_commit': 'candidate',
                'dirty_checkout': False, 'model_requested': 'approved', 'passed': True, 'status': 'pass',
                'results': [{'case': case, 'passed': True, 'complete': True, 'error': None,
                             'checks': {k: True for k in CASE_CHECKS[case]}} for case in REQUIRED_CASES]}

    def test_reject_missing_failed_stale_dirty_and_wrong_model_evidence(self):
        report = self.report()
        self.assertEqual(validate(report, 'candidate', 'approved'), [])
        variants = []
        for field, value in [('mode', 'stub'), ('suite_commit', 'old'), ('dirty_checkout', True),
                             ('model_requested', 'other'), ('passed', False), ('results', [])]:
            altered = copy.deepcopy(report)
            altered[field] = value
            variants.append(altered)
        altered = copy.deepcopy(report)
        altered['results'][0]['checks']['independent_acceptance'] = False
        variants.append(altered)
        altered = copy.deepcopy(report)
        altered['results'][-1] = altered['results'][0]
        variants.append(altered)
        for altered in variants:
            with self.subTest(altered=altered):
                self.assertTrue(validate(altered, 'candidate', 'approved'))

    def test_spike_contract_path_matches_scratch_policy(self):
        contract = get_next_turn_contract({'state_key': 'SPIKE_ACTIVE', 'target_change': 'example'})
        with tempfile.TemporaryDirectory() as tmp:
            engine = EnterprisePolicyEngine(Path(tmp))
            engine.registry.register_skill_policy(EnterprisePolicy(skill='spike', allowed=AllowedConfig(filesystem='scratch')))
            path = contract.inputs['sandbox_dir'] + 'example/worker.py'
            self.assertTrue(engine.evaluate_filesystem('spike', path, mode='write').allowed)
            self.assertEqual(CapabilityManager.classify_target_ring(path), ExecutionRing.RING_3_WORKSPACE)

    def test_release_requires_review_adjudication_and_clean_control(self):
        report = self.report()
        report['results'] = [r for r in report['results'] if r['case'] != 'review-average-clean']
        self.assertTrue(validate(report, 'candidate', 'approved'))
        report = self.report()
        review = next(r for r in report['results'] if r['case'] == 'review-average')
        review['checks'] = {'completed': True, 'no_symlinks': True, 'trace_integrity': True,
                            'tools_observed': True, 'notes_preserved': True, 'source_read': True,
                            'contract_read': True, 'no_edits': True, 'defect_reported': True}
        self.assertTrue(validate(report, 'candidate', 'approved'))


class ShipLiveHarnessTests(unittest.TestCase):
    def test_full_lifecycle_context_reset_and_stale_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'workspace'
            root.mkdir()
            (root / 'calc.py').write_text('def average(xs):\n    raise NotImplementedError\n')
            (root / 'notes.txt').write_text('Unrelated user work.\n')
            (root / '.agentflow.json').write_text(json.dumps({'version': 1,
                'workflow': {'profile': 'small-fix', 'execution': 'sequential'},
                'gates': {'implementation': {'test': 'python3 -B -m unittest discover -v'}}}))
            for args in [('init', '-q', '-b', 'main'), ('config', 'user.name', 'Fixture'),
                         ('config', 'user.email', 'fixture@example.invalid'), ('config', 'commit.gpgsign', 'false'),
                         ('add', '.'), ('commit', '-qm', 'fixture')]:
                subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
            def write(path, content, cid):
                return call('write_file', {'path': path, 'content': content}, cid)
            def lifecycle(action, cid, **kwargs):
                return call('lifecycle', {'action': action, **kwargs}, cid)
            task_path = 'openspec/changes/average/tasks.md'
            report_path = '.agentflow/reviews/average/review_report.json'
            counter = 0
            reset_seen = False
            def transport(messages, system):
                nonlocal counter, reset_seen
                counter += 1
                if counter == 1:
                    return response(write('docs/adr/ADR-001-average.md', '# Average\nPreserve the API.', 'a'),
                        write('openspec/changes/average/proposal.md', '# Average\nImplement arithmetic mean.', 'b'),
                        write('openspec/changes/average/specs/average.md', '### Requirement: Average\nMean or zero for empty input.\n', 'c'),
                        write(task_path, '- [ ] Implement average\n', 'd'))
                if counter == 2:
                    return {'content': [{'type': 'text', 'text': 'Approve the package?'}], 'stop_reason': 'end_turn'}
                if counter == 3:
                    reset_seen = len(messages) == 1 and 'interrupted' in messages[0]['content']
                    test = 'import unittest\nfrom calc import average\nclass Tests(unittest.TestCase):\n    def test_empty(self): self.assertEqual(average([]), 0)\n'
                    return response(lifecycle('next', 'e'), write('test_calc.py', test, 'f'), call('run_tests', {}, 'g'))
                if counter == 4:
                    return response(write('calc.py', 'def average(xs):\n    return sum(xs)/len(xs) if xs else 0\n', 'h'),
                        call('run_tests', {}, 'i'), write(task_path, '- [x] Implement average\n', 'j'),
                        lifecycle('record_tests', 'k'), lifecycle('verify', 'l'), lifecycle('fingerprint', 'm'))
                if counter in (5, 8):
                    output = json.loads(messages[-1]['content'][-1]['content'])
                    report = {'change': 'average', 'reviewer': 'judge', 'status': 'complete', 'verdict': 'PASS',
                        'findings': [], 'coverage': ['correctness'], 'questions': [], 'routing_notes': [],
                        'test_evidence': {'passed': True, 'tests_run': 1, 'failed_count': 0, 'exit_code': 0},
                        'working_tree_fingerprint': output['stdout'].strip()}
                    return response(write(report_path, json.dumps(report), f'n{counter}'),
                                    lifecycle('record_review', f'o{counter}', report=report_path), lifecycle('status', f'p{counter}'))
                if counter == 6:
                    return response(call('read_file', {'path': 'calc.py'}, 'q'), call('run_tests', {}, 'r'))
                if counter == 7:
                    return response(lifecycle('record_tests', 's'), lifecycle('verify', 't'), lifecycle('fingerprint', 'u'))
                if counter == 9:
                    return response(lifecycle('archive', 'v'), lifecycle('trailers', 'w'))
                return {'content': [{'type': 'text', 'text': 'Complete; sequential review.'}], 'stop_reason': 'end_turn'}
            session = ShipSession(root, Path(tmp) / 'evidence', ROOT / 'skills/ship', transport,
                                  CommandExecutor(root, backend='local'), 20)
            result = evaluate_ship(session, session.run('Implement average'))
            self.assertTrue(reset_seen)
            self.assertTrue(result['passed'], json.dumps(result, indent=2))

    def test_approval_boundary_rejects_code_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'workspace'
            root.mkdir()
            (root / 'calc.py').write_text('original')
            (root / '.agentflow.json').write_text('{}')
            session = ShipSession(root, Path(tmp) / 'evidence', ROOT / 'skills/ship', None,
                                  CommandExecutor(root, backend='local'))
            (root / 'calc.py').write_text('implementation before approval')
            with self.assertRaisesRegex(RuntimeError, 'before design approval'):
                session.on_completion()
