"""Exercise step tracing through its public interface, including cold resumption."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ship.lifecycle.events import EventLogger
from ship.lifecycle.step_tracing import StepTrace

ROOT = Path(__file__).resolve().parents[1]


class StepTraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.trace = StepTrace(self.root)
        self.run = self.trace.begin(['tdd'], change_id='feature', task_id='task-1')['run_id']
        (self.root / 'receipt.txt').write_text('one test failed: AssertionError')

    def record(self, status, **kwargs):
        return self.trace.record(self.run, 'tdd.red', status, **kwargs)

    def test_unobserved_incomplete_and_evidence_integrity(self):
        report = self.trace.report(self.run)
        self.assertEqual(report['counts']['unobserved'], 8)
        attempt = self.record('started')['attempt_id']
        self.assertEqual(StepTrace(self.root).report(self.run)['counts']['started'], 1)
        self.record('completed', attempt_id=attempt, evidence=['receipt.txt'])
        report = self.trace.report(self.run)
        step = next(s for s in report['steps'] if s['id'] == 'tdd.red')
        self.assertEqual(step['status'], 'completed')
        self.assertEqual(step['attempts'][0]['evidence'][0]['integrity'], 'current')
        self.assertFalse(report['fully_observed'])
        (self.root / 'receipt.txt').write_text('changed')
        self.assertEqual(self.trace.report(self.run)['evidence_issues'], 1)
        (self.root / 'receipt.txt').unlink()
        self.assertEqual(self.trace.report(self.run)['evidence_issues'], 1)

    def test_invalid_transitions_do_not_append(self):
        for kwargs in ({}, {'attempt_id': 'unknown', 'evidence': ['receipt.txt']}):
            with self.assertRaises(ValueError):
                self.record('completed', **kwargs)
        attempt = self.record('started')['attempt_id']
        for status, kwargs in [('started', {}), ('completed', {'attempt_id': attempt}),
                               ('failed', {'attempt_id': attempt}), ('skipped', {'attempt_id': attempt})]:
            with self.assertRaises(ValueError):
                self.record(status, **kwargs)
        self.assertEqual(len(EventLogger(self.root).read_all()), 2)

    def test_retry_preserves_attempts_and_reason(self):
        first = self.record('started')['attempt_id']
        self.record('failed', attempt_id=first, reason='runner crashed')
        second = self.record('started')['attempt_id']
        with self.assertRaises(ValueError):
            self.record('completed', attempt_id=first, evidence=['receipt.txt'])
        self.record('completed', attempt_id=second, evidence=['receipt.txt'])
        step = next(s for s in self.trace.report(self.run)['steps'] if s['id'] == 'tdd.red')
        self.assertEqual([a['status'] for a in step['attempts']], ['failed', 'completed'])
        self.assertEqual(step['attempts'][0]['reason'], 'runner crashed')
        self.assertGreaterEqual(step['attempts'][1]['duration_seconds'], 0)

    def test_skip_requires_reason_and_remains_distinct(self):
        with self.assertRaises(ValueError):
            self.record('skipped')
        self.record('skipped', reason='documentation-only task')
        self.assertEqual(self.trace.report(self.run)['counts']['skipped'], 1)
        self.assertEqual(self.trace.report(self.run)['counts']['completed'], 0)

    def test_run_isolation_unknown_ids_and_catalog_snapshot(self):
        other = self.trace.begin(['tdd'], task_id='task-2')['run_id']
        self.record('started')
        self.assertEqual(self.trace.report(other)['counts']['unobserved'], 8)
        for run, step in [(self.run, 'tdd.typo'), (self.run, 'debug.fix'), ('missing', 'tdd.red')]:
            with self.assertRaises(ValueError):
                self.trace.record(run, step, 'started')
        with patch('ship.lifecycle.step_tracing.SKILLS', {}):
            self.assertEqual(len(self.trace.report(self.run)['steps']), 8)

    def test_evidence_cannot_escape_repository(self):
        attempt = self.record('started')['attempt_id']
        (self.root / 'link').symlink_to('/etc/hosts')
        for path in ('../outside', '/etc/hosts', 'link', 'missing', '.'):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                self.record('completed', attempt_id=attempt, evidence=[path])

    def test_corrupt_stream_fails_closed(self):
        log = EventLogger(self.root)
        with log.event_file.open('a') as stream:
            stream.write('{invalid\n')
        with self.assertRaises(ValueError):
            self.trace.report(self.run)
        with self.assertRaises(ValueError):
            self.record('started')

    def test_concurrent_starts_only_one_attempt(self):
        def start(_):
            try:
                return self.record('started')
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(start, range(4)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertTrue(EventLogger(self.root).verify_integrity()[0])

    def test_catalog_all_steps_and_current_generated_distribution(self):
        data = json.loads((ROOT / 'tests/skill_coverage.json').read_text())
        run = self.trace.begin(list(data['skills']))['run_id']
        ids = {s['id'] for s in self.trace.report(run)['steps']}
        self.assertEqual(ids, {s['id'] for sk in data['skills'].values() for s in sk['steps']})
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/verify/build_step_catalog.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cli_and_standalone_distribution(self):
        from ship.cli import main
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['steps', 'report', self.run, '--path', str(self.root)]), 0)
        self.assertEqual(json.loads(output.getvalue())['run_id'], self.run)
        installed = self.root / 'installed-ship'
        shutil.copytree(ROOT / 'skills/ship', installed, ignore=shutil.ignore_patterns('__pycache__'))
        result = subprocess.run([sys.executable, str(installed / 'scripts/trace_steps.py'),
                                 'report', self.run, '--path', str(self.root)], cwd=self.root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['counts']['unobserved'], 8)

    def test_mcp_read_and_mutation_permissions(self):
        from ship.mcp.tools import dispatch_tool
        with patch.dict('os.environ', {'AGENTFLOW_MCP_ALLOW_MUTATIONS': '0'}):
            report = dispatch_tool('ship_steps_report', {'path': str(self.root), 'run_id': self.run})
            self.assertEqual(report['counts']['unobserved'], 8)
            with self.assertRaises(PermissionError):
                dispatch_tool('ship_steps_record', {'path': str(self.root), 'run_id': self.run,
                              'step_id': 'tdd.red', 'status': 'started'})
        with patch.dict('os.environ', {'AGENTFLOW_MCP_ALLOW_MUTATIONS': '1'}):
            result = dispatch_tool('ship_steps_record', {'path': str(self.root), 'run_id': self.run,
                                   'step_id': 'tdd.red', 'status': 'started'})
            self.assertIn('attempt_id', result)

    def test_failure_is_observed_but_not_completed(self):
        run = self.trace.begin(['spike'])['run_id']
        for step in self.trace.report(run)['steps']:
            self.trace.record(run, step['id'], 'skipped', reason='not applicable to selected experiment')
        started = self.trace.record(run, 'spike.measure', 'started')
        self.trace.record(run, 'spike.measure', 'failed', attempt_id=started['attempt_id'], reason='timeout')
        report = self.trace.report(run)
        self.assertTrue(report['fully_observed'])
        self.assertEqual(report['counts']['completed'], 0)
        self.assertEqual(report['counts']['failed'], 1)
        self.assertEqual(report['counts']['skipped'], 5)

    def test_absent_provenance_stays_unknown_and_empty_selection_rejected(self):
        report = self.trace.report(self.run)
        self.assertIsNone(report['model'])
        self.assertIsNone(report['agent_id'])
        for selection in (None, [], ['typo'], ['tdd', 'tdd'], 'tdd'):
            with self.assertRaises(ValueError):
                self.trace.begin(selection)

    def test_cli_complete_cycle_and_error_exit(self):
        from ship.cli import main
        def invoke(*args):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(['steps', *args, '--path', str(self.root)])
            return code, json.loads(output.getvalue()) if output.getvalue() else None
        code, run = invoke('begin', '--skill', 'debug', '--task', 'repair')
        self.assertEqual(code, 0)
        code, attempt = invoke('started', run['run_id'], 'debug.reproduce')
        self.assertEqual(code, 0)
        code, result = invoke('completed', run['run_id'], 'debug.reproduce', '--attempt',
                              attempt['attempt_id'], '--evidence', 'receipt.txt')
        self.assertEqual((code, result['status']), (0, 'completed'))
        from contextlib import redirect_stderr
        with redirect_stderr(io.StringIO()):
            self.assertEqual(invoke('report', 'unknown')[0], 1)

    def test_telemetry_does_not_trigger_archive_recovery(self):
        journal = self.root / '.agentflow/archive-transaction.json'
        journal.write_text('{interrupted archive')
        self.trace.report(self.run)
        self.record('started')
        self.trace.begin(['debug'])
        self.assertEqual(journal.read_text(), '{interrupted archive')

    def test_hash_valid_but_invalid_step_event_is_rejected(self):
        attempt = self.record('started')
        EventLogger(self.root).emit('STEP_COMPLETED', payload={
            'run_id': self.run, 'step_id': 'tdd.red', 'attempt_id': attempt['attempt_id'],
            'status': 'invented-status'})
        self.assertTrue(EventLogger(self.root).verify_integrity()[0])
        with self.assertRaises(ValueError):
            self.trace.report(self.run)
