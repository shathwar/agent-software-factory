"""Regression checks for the organization rollout review."""

import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

from ship.lifecycle.checkpoints import CheckpointManager
from ship.lifecycle.verification import execute_and_verify_tests, runner_test_counts, verify_spec_coverage


class ReadinessTests(unittest.TestCase):
    def test_rollback_requires_explicit_opt_in_and_preserves_user_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.run(['git', '-C', tmp, *args], check=True, capture_output=True)
            git('init')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@example.com')
            source = root / 'source.py'
            source.write_text('original = True\n')
            git('add', '.')
            git('commit', '-m', 'initial')
            manager = CheckpointManager()
            manager.create_checkpoint(root, 'design', change='demo')
            source.write_text('user_edit = True\n')
            notes = root / 'user-notes.txt'
            notes.write_text('unrelated work\n')
            git('add', 'source.py')
            index = git('write-tree').stdout
            head = git('rev-parse', 'HEAD').stdout
            ledger = (root / '.agentflow/state.json').read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'explicit.*--force'):
                manager.perform_rollback(root, 'design', change='demo')
            self.assertEqual(source.read_text(), 'user_edit = True\n')
            self.assertEqual(notes.read_text(), 'unrelated work\n')
            self.assertEqual(git('write-tree').stdout, index)
            self.assertEqual(git('rev-parse', 'HEAD').stdout, head)
            self.assertEqual((root / '.agentflow/state.json').read_bytes(), ledger)
            # An explicitly authorized whole-checkout restoration still keeps backups.
            result = manager.perform_rollback(root, 'design', change='demo', force=True)
            self.assertEqual(source.read_text(), 'original = True\n')
            self.assertEqual((root / result['backup_directory'] / 'user-notes.txt').read_text(), 'unrelated work\n')

    def test_execution_requires_actual_runner_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertNotEqual(execute_and_verify_tests(root, 'true').verdict, 'VERIFIED')
            (root / 'test_sample.py').write_text(
                'import unittest\n'
                'class Sample(unittest.TestCase):\n'
                '    def test_value(self): self.assertEqual(2 + 2, 4)\n'
            )
            command = shlex.quote(sys.executable) + ' -B -m unittest discover'
            record = execute_and_verify_tests(root, command)
            self.assertEqual(record.verdict, 'VERIFIED', record.findings)
            self.assertEqual(record.metadata['tests_run'], 1)
            (root / 'test_sample.py').write_text(
                'import unittest\n'
                '@unittest.skip("not implemented")\n'
                'class Sample(unittest.TestCase):\n'
                '    def test_value(self): pass\n'
            )
            self.assertNotEqual(execute_and_verify_tests(root, command).verdict, 'VERIFIED')

    def test_file_presence_never_certifies_spec_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            specs = root / 'openspec/changes/demo/specs/auth'
            specs.mkdir(parents=True)
            (specs / 'spec.md').write_text('### Requirement: Authentication\nEvery request requires a token.\n')
            for filename in ('tests/test_unrelated.py', 'src/auth.test.ts', 'pkg/auth_test.go'):
                with self.subTest(filename=filename):
                    test = root / filename
                    test.parent.mkdir(parents=True, exist_ok=True)
                    test.write_text('unrelated test content\n')
                    self.assertEqual(verify_spec_coverage(root, 'demo').verdict, 'INCONCLUSIVE')
                    test.unlink()

    def test_copy_only_install_can_execute_verification(self):
        inspector = Path(__file__).resolve().parents[1] / 'skills/ship/scripts/inspect_lifecycle.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed = root / 'external skill copy'
            shutil.copytree(inspector.parent.parent, installed / 'ship')
            (root / '.agentflow.json').write_text(json.dumps({
                'version': 1, 'gates': {'implementation': {'test': 'true'}}}))
            command = [sys.executable, '-I', str(installed / 'ship/scripts' / inspector.name), '--path', tmp,
                       '--verify', '--tier', 'execution', '--format', 'json']
            result = subprocess.run(command,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue(result.stdout, result.stderr)
            self.assertEqual(json.loads(result.stdout)['execution']['verdict'], 'INCONCLUSIVE')
            (root / 'test_sample.py').write_text('import unittest\nclass Sample(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n')
            (root / '.agentflow.json').write_text(json.dumps({
                'version': 1, 'gates': {'implementation': {
                    'test': shlex.quote(sys.executable) + ' -B -m unittest test_sample'}}}))
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['execution']['metadata']['tests_run'], 1)

    def test_supported_runner_summaries_and_masked_failures(self):
        cases = {
            'Ran 2 tests in 0.010s\n\nOK (skipped=1)\n': (1, 0),
            'Ran 1 test in 0.001s\n': (None, 0),
            '=== 2 passed, 1 skipped in 0.10s ===\n': (2, 0),
            '1 failed, 2 passed in 0.10s\n': (2, 1),
            'Tests: 2 passed, 1 skipped, 3 total\n': (2, 0),
            ' Tests  2 passed (2)\n': (2, 0),
            '# pass 2\n# fail 0\n': (2, 0),
            'ℹ pass 2\nℹ fail 1\n': (2, 1),
            'Tests: 1 skipped, 1 total\n': (0, 0),
            'all good\n': (None, 0),
            'Ran 1 test in 0.001s\nOK\n1 failed, 2 passed in 0.10s\n': (3, 1),
        }
        for output, counts in cases.items():
            with self.subTest(output=output):
                self.assertEqual(runner_test_counts(output), counts)
        with tempfile.TemporaryDirectory() as tmp:
            # A shell wrapper masking the runner's nonzero exit cannot certify failure.
            command = shlex.quote(sys.executable) + ' -c ' + shlex.quote('print("1 failed, 2 passed in 0.10s")')
            self.assertEqual(execute_and_verify_tests(Path(tmp), command).verdict, 'NOT_VERIFIED')

    def test_ci_gates_bind_design_and_require_executed_tests(self):
        import test_archive_recovery as fixtures
        from ship.lifecycle.evidence import design_fingerprint
        from ship.lifecycle.vcs import GitClient
        gate = Path(__file__).resolve().parents[1] / 'scripts/verify/ci_gate.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures.ArchiveRecoveryTests().workspace(root)
            (root / '.agentflow.json').write_text(json.dumps({
                'version': 1, 'gates': {'implementation': {'test': 'true'}}}))
            digest = design_fingerprint(root, 'alpha')
            def run(phase, approved_digest=digest):
                return subprocess.run([sys.executable, str(gate), phase, '--path', tmp,
                                       '--change', 'alpha', '--digest', approved_digest,
                                       '--approved-by', 'ci-operator'], capture_output=True, text=True)
            self.assertEqual(run('prepare', '0' * 64).returncode, 1)
            self.assertEqual(run('prepare').returncode, 0)
            blocked = run('delivery')
            self.assertEqual(blocked.returncode, 1, blocked.stdout)
            self.assertIn('INCONCLUSIVE', blocked.stdout)
            (root / 'test_sample.py').write_text('import unittest\nclass Sample(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n')
            (root / '.agentflow.json').write_text(json.dumps({
                'version': 1, 'gates': {'implementation': {
                    'test': shlex.quote(sys.executable) + ' -B -m unittest test_sample'}}}))
            report_path = root / '.agentflow/reviews/alpha/review_report.json'
            report = json.loads(report_path.read_text())
            report['working_tree_fingerprint'] = GitClient().compute_working_tree_fingerprint(root)
            report_path.write_text(json.dumps(report))
            passed = run('delivery')
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            self.assertIn('DELIVERY_READY', passed.stdout)
            tasks = root / 'openspec/changes/alpha/tasks.md'
            tasks.write_text(tasks.read_text() + '\n- [ ] Unapproved requirement\n')
            blocked = run('delivery')
            self.assertEqual(blocked.returncode, 1)
            self.assertIn('Design differs', blocked.stderr)
