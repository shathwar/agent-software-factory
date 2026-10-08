"""Offline contract tests execute real fixture tools; they are not live-model trials."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.agent_harness.live import CommandExecutor, LiveSession, bounded_path, evaluate

ROOT = Path(__file__).resolve().parents[1]


def call(name, arguments, cid):
    return {'type': 'tool_use', 'name': name, 'input': arguments, 'id': cid}


def response(*calls):
    return {'content': list(calls), 'stop_reason': 'tool_use'}


class LiveCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'workspace'
        self.root.mkdir()
        (self.root / 'calc.py').write_text('def average(xs):\n    raise NotImplementedError\n')
        (self.root / 'notes.txt').write_text('Unrelated user work.\n')
        self.artifacts = self.base / 'evidence'

    def session(self, responses, max_turns=20):
        iterator = iter(responses)
        def transport(messages, system):
            self.assertIn('TDD', system)
            return next(iterator)
        return LiveSession(self.root, self.artifacts, ROOT / 'skills/tdd', transport,
                           CommandExecutor(self.root, backend='local'), max_turns)

    def test_actual_red_edit_green_and_persisted_results(self):
        test = 'import unittest\nfrom calc import average\nclass Tests(unittest.TestCase):\n    def test_empty(self): self.assertEqual(average([]), 0)\n'
        session = self.session([
            response(call('write_file', {'path': 'test_calc.py', 'content': test}, 'a'), call('run_tests', {}, 'b')),
            response(call('write_file', {'path': 'calc.py', 'content': 'def average(xs):\n    return sum(xs)/len(xs) if xs else 0\n'}, 'c'), call('run_tests', {}, 'd')),
            {'content': [{'type': 'text', 'text': 'Done'}], 'stop_reason': 'end_turn'},
        ])
        run = session.run('Implement average')
        result = evaluate(session, 'tdd-average', run)
        self.assertTrue(result['passed'], result)
        trace = session.observer.get_trace()
        self.assertEqual(len(trace.tool_calls()), 4)
        self.assertEqual(len(trace.commands()), 2)
        self.assertEqual([t.exit_code for t in trace.test_results()], [1, 0])
        self.assertTrue(trace.verify_integrity()[0])
        records = [json.loads(line) for line in (self.artifacts / 'trace.jsonl').read_text().splitlines()]
        self.assertEqual(len(records), len(trace.events))
        self.assertIn('NotImplementedError', (self.artifacts / 'command-001.json').read_text())
        self.assertEqual(json.loads((self.artifacts / 'acceptance.json').read_text())['exit_code'], 0)

    def test_prose_only_is_not_execution_evidence(self):
        session = self.session([{'content': [{'type': 'text', 'text': 'Tests passed, red before green.'}], 'stop_reason': 'end_turn'}])
        result = evaluate(session, 'tdd-average', session.run('Implement'))
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['tools_observed'])
        self.assertFalse(result['checks']['red_before_edit_before_green'])

    def test_budget_exhaustion_preserves_partial_trace(self):
        session = self.session([response(call('write_file', {'path': 'new.txt', 'content': 'partial'}, 'a'))], max_turns=1)
        result = session.run('Implement')
        self.assertFalse(result['complete'])
        self.assertIn('budget exhausted', result['error'])
        self.assertTrue((self.artifacts / 'trace.jsonl').is_file())
        self.assertEqual(len(session.observer.get_trace().file_changes()), 1)

    def test_transport_failure_preserves_trace(self):
        session = self.session([response(call('read_file', {'path': 'calc.py'}, 'a'))])
        result = session.run('Implement')
        self.assertFalse(result['complete'])
        self.assertIn('StopIteration', result['error'])
        self.assertEqual(len(session.observer.get_trace().tool_calls()), 1)

    def test_path_escape_and_symlink_capture(self):
        secret = self.base / 'outside.txt'
        secret.write_text('DO NOT COLLECT')
        (self.root / 'alias').symlink_to(secret)
        with self.assertRaises(ValueError):
            bounded_path(self.root, 'alias')
        session = self.session([response(call('read_file', {'path': '../outside.txt'}, 'a'))], max_turns=1)
        session.run('Read')
        self.assertNotIn('DO NOT COLLECT', (self.artifacts / 'trace.jsonl').read_text())
        self.assertNotIn('alias', session.observer.file_contents)

    def test_command_failure_and_timeout_are_recorded(self):
        executor = CommandExecutor(self.root, backend='local', timeout=0.1)
        result = executor.run(['python', '-c', 'import time; time.sleep(2)'])
        self.assertEqual(result['exit_code'], 124)
        session = self.session([])
        session.executor = executor
        result = session.command(['python', '-c', 'raise SystemExit(7)'])
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(session.observer.get_trace().commands()[0].exit_code, 7)

    def test_test_process_cannot_receive_provider_key(self):
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'fixture-secret'}):
            result = CommandExecutor(self.root, backend='local').run(['python', '-c', 'import os; print(os.getenv("ANTHROPIC_API_KEY", "absent"))'])
        self.assertEqual(result['stdout'].strip(), 'absent')

    def test_in_process_edit_is_not_false_red_before_edit(self):
        session = self.session([])
        session.command(['python', '-c', 'from pathlib import Path; Path("calc.py").write_text("changed"); print("Ran 1 test"); raise SystemExit(1)'])
        trace = session.observer.get_trace()
        self.assertLess(trace.file_changes()[0].seq, trace.test_results()[0].seq)

    def test_missing_credentials_is_inconclusive_and_nonzero(self):
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': '', 'AGENT_REGRESSION_MODEL': ''}):
            proc = subprocess.run([sys.executable, str(ROOT / 'scripts/test/run_live_regression.py'), '--output', str(self.artifacts)], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        report = json.loads((self.artifacts / 'report.json').read_text())
        self.assertEqual(report['status'], 'inconclusive')
        self.assertFalse(report['passed'])

    def test_workflow_is_not_a_pr_job(self):
        workflow = (ROOT / '.github/workflows/live-agent-regression.yml').read_text()
        self.assertIn('schedule:', workflow)
        self.assertIn('release:', workflow)
        self.assertNotIn('pull_request', workflow)
        self.assertIn('if: always()', workflow)

    def test_legacy_repository_name_absent_from_tracked_files(self):
        old = ('shathwar/' + 'skills').encode()
        paths = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
        for name in paths:
            path = ROOT / name
            if path.is_file():
                self.assertNotIn(old, path.read_bytes(), name)

    def test_independent_acceptance_rejects_narrow_fake_fix(self):
        test = 'import unittest\nfrom calc import average\nclass Tests(unittest.TestCase):\n    def test_empty(self): self.assertEqual(average([]), 0)\n'
        session = self.session([
            response(call('write_file', {'path': 'test_calc.py', 'content': test}, 'a'), call('run_tests', {}, 'b')),
            response(call('write_file', {'path': 'calc.py', 'content': 'def average(xs):\n    return 0\n'}, 'c'), call('run_tests', {}, 'd')),
            {'content': [], 'stop_reason': 'end_turn'},
        ])
        result = evaluate(session, 'tdd-average', session.run('Implement'))
        self.assertTrue(result['checks']['red_before_edit_before_green'])
        self.assertFalse(result['checks']['independent_acceptance'])
        self.assertFalse(result['passed'])

    def test_container_gets_only_fixture_mount_and_no_network(self):
        executor = CommandExecutor(self.root, backend='docker', image='sha256:fixture')
        completed = subprocess.CompletedProcess([], 0, 'ok', '')
        with patch('tests.agent_harness.live.subprocess.run', return_value=completed) as run:
            executor.run(['python', '-m', 'unittest'])
        argv = run.call_args_list[0].args[0]
        self.assertEqual(argv[argv.index('--network') + 1], 'none')
        self.assertEqual(argv.count('--mount'), 1)
        self.assertIn('type=bind,src=' + str(self.root) + ',dst=/workspace', argv)
        self.assertNotIn('ANTHROPIC_API_KEY', run.call_args_list[0].kwargs['env'])
        self.assertIn('--read-only', argv)
