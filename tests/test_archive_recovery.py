"""Process-death recovery and filesystem boundaries for lifecycle transactions."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/ship/scripts"
sys.path.insert(0, str(SCRIPTS))
import inspect_lifecycle as lifecycle
from verification_fixture import verify_fixture

CHILD = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import inspect_lifecycle as lifecycle
from lifecycle import specs, transactions
from lifecycle.ledger import FileLedgerStore
root, step = Path(sys.argv[2]), sys.argv[3]
if step == 'journal':
    original = specs.begin_archive
    def stop(*a, **kw):
        original(*a, **kw)
        os._exit(91)
    specs.begin_archive = stop
elif step in ('spec1', 'spec2'):
    original = specs.atomic_write
    calls = []
    def stop(*a, **kw):
        original(*a, **kw)
        calls.append(1)
        if len(calls) == int(step[-1]): os._exit(91)
    specs.atomic_write = stop
elif step in ('spec-write', 'recovery-write'):
    original = transactions.os.replace
    def stop(src, dst):
        if Path(dst).parent.name == 'specs': os._exit(91)
        return original(src, dst)
    transactions.os.replace = stop
    if step == 'recovery-write':
        lifecycle.evaluate_repository(root, target_change='alpha')
        raise AssertionError('recovery did not run')
elif step == 'move':
    original = specs.shutil.move
    def stop(*a, **kw):
        original(*a, **kw)
        os._exit(91)
    specs.shutil.move = stop
elif step == 'ledger':
    original = FileLedgerStore.save
    def stop(cls, root, ledger):
        original(root, ledger)
        os._exit(91)
    FileLedgerStore.save = classmethod(stop)
elif step == 'cleanup':
    original = specs.recover_archive
    def stop(*a, **kw):
        original(*a, **kw)
        os._exit(91)
    specs.recover_archive = stop
elif step == 'recovery':
    original = transactions.atomic_write
    def stop(*a, **kw):
        original(*a, **kw)
        os._exit(91)
    transactions.atomic_write = stop
    lifecycle.evaluate_repository(root, target_change='alpha')
    raise AssertionError('recovery did not run')
lifecycle.apply_and_archive_openspec(root, 'alpha')
raise AssertionError('archive was not interrupted')
'''


class ArchiveRecoveryTests(unittest.TestCase):
    def workspace(self, root):
        pkg = root / 'openspec/changes/alpha'
        (pkg / 'specs').mkdir(parents=True)
        (pkg / 'tasks.md').write_text('- [x] Done\n')
        (pkg / 'specs/shared.md').write_text('### Requirement: Alpha\nAlpha behavior\n')
        (pkg / 'specs/new.md').write_text('### Requirement: New\nNew behavior\n')
        living = root / 'openspec/specs/shared.md'
        living.parent.mkdir(parents=True)
        living.write_bytes(b'### Requirement: Base\r\nBase behavior\r\n')
        for args in [('init', '-b', 'main'), ('config', 'user.name', 'Test'),
                     ('config', 'user.email', 'test@example.com'), ('config', 'commit.gpgsign', 'false'),
                     ('add', '.'), ('commit', '-m', 'initial')]:
            subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        report = root / '.agentflow/reviews/alpha/review_report.json'
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({
            'change': 'alpha', 'reviewer': 'judge', 'status': 'complete', 'verdict': 'PASS',
            'findings': [], 'coverage': ['checked'], 'questions': [], 'routing_notes': [],
            'test_evidence': True, 'commit': sha,
        }))
        from lifecycle.evidence import design_fingerprint
        from lifecycle.ledger import FileLedgerStore
        FileLedgerStore.approve_design(root, "alpha", design_fingerprint(root, "alpha"), "test-reviewer")
        lifecycle.sync_ledger_from_workspace(root)
        verify_fixture(root)
        return living.read_bytes(), (root / '.agentflow/state.json').read_bytes()

    def stop_process(self, root, step):
        result = subprocess.run([sys.executable, '-c', CHILD, str(SCRIPTS), str(root), step],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 91, result.stderr)

    def test_restart_at_every_archive_boundary_is_idempotent(self):
        for step in ('journal', 'spec-write', 'spec1', 'spec2', 'move', 'ledger', 'cleanup'):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                original_spec, original_state = self.workspace(root)
                self.stop_process(root, step)
                committed = step in ('ledger', 'cleanup')
                for _ in range(2):
                    result = lifecycle.evaluate_repository(root, target_change='alpha')
                    self.assertEqual(result['state_key'], 'ARCHIVED' if committed else 'DELIVERY_READY')
                    self.assertFalse((root / '.agentflow/archive-transaction.json').exists())
                    self.assertEqual(list((root / 'openspec/specs').glob('.agentflow-write-*')), [])
                    if committed:
                        self.assertFalse((root / 'openspec/changes/alpha').exists())
                        self.assertIn('Alpha behavior', (root / 'openspec/specs/shared.md').read_text())
                        self.assertTrue((root / 'openspec/specs/new.md').exists())
                    else:
                        self.assertEqual((root / 'openspec/specs/shared.md').read_bytes(), original_spec)
                        self.assertEqual((root / '.agentflow/state.json').read_bytes(), original_state)
                        self.assertFalse((root / 'openspec/specs/new.md').exists())
                        self.assertTrue((root / 'openspec/changes/alpha').is_dir())
                if not committed:
                    lifecycle.apply_and_archive_openspec(root, 'alpha')
                    self.assertEqual(lifecycle.evaluate_repository(root, target_change='alpha')['state_key'], 'ARCHIVED')

    def test_recovery_itself_can_be_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_spec, original_state = self.workspace(root)
            self.stop_process(root, 'move')
            self.stop_process(root, 'recovery-write')
            self.stop_process(root, 'recovery')
            for _ in range(2):
                self.assertEqual(lifecycle.evaluate_repository(root, target_change='alpha')['state_key'], 'DELIVERY_READY')
            self.assertEqual((root / 'openspec/specs/shared.md').read_bytes(), original_spec)
            self.assertEqual((root / '.agentflow/state.json').read_bytes(), original_state)

    def test_invalid_journal_stops_operations_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.workspace(root)
            self.stop_process(root, 'move')
            journal = root / '.agentflow/archive-transaction.json'
            data = json.loads(journal.read_text())
            data['specs'][0]['path'] = '../outside'
            journal.write_text(json.dumps(data))
            before = journal.read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'journal preserved'):
                lifecycle.set_active_change(root, 'other')
            self.assertEqual(journal.read_bytes(), before)

    def test_recovery_preserves_external_edits_and_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.workspace(root)
            self.stop_process(root, 'move')
            living = root / 'openspec/specs/shared.md'
            living.write_text('manual work after interruption')
            with self.assertRaisesRegex(RuntimeError, 'spec changed outside'):
                lifecycle.evaluate_repository(root, target_change='alpha')
            self.assertEqual(living.read_text(), 'manual work after interruption')
            self.assertTrue((root / '.agentflow/archive-transaction.json').exists())

    def test_unsafe_identifiers_rejected_across_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / 'repo'
            root.mkdir()
            self.workspace(root)
            outside = base / 'external'
            outside.mkdir()
            sentinel = outside / 'valuable.txt'
            sentinel.write_text('keep')
            state = (root / '.agentflow/state.json').read_bytes()
            for bad in (str(outside), '../external', '../../external', r'..\external', '.', '..', 'alpha/beta'):
                actions = (
                    lambda: lifecycle.apply_and_archive_openspec(root, bad, force=True),
                    lambda: lifecycle.inspect_openspec(root, target_change=bad),
                    lambda: lifecycle.create_checkpoint(root, 'design', change=bad),
                    lambda: lifecycle.perform_rollback(root, 'design', change=bad, force=True),
                    lambda: lifecycle.set_active_change(root, bad),
                )
                for action in actions:
                    with self.subTest(change=bad, action=action), self.assertRaises(ValueError):
                        action()
                self.assertEqual(sentinel.read_text(), 'keep')
                self.assertEqual((root / '.agentflow/state.json').read_bytes(), state)

    def test_symlinked_managed_paths_are_rejected(self):
        for location in ('package', 'changes', 'spec-file', 'living-dir', 'ledger-dir', 'lock-file'):
            with self.subTest(location=location), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = base / 'repo'
                root.mkdir()
                self.workspace(root)
                paths = {
                    'package': root / 'openspec/changes/alpha',
                    'changes': root / 'openspec/changes',
                    'spec-file': root / 'openspec/changes/alpha/specs/shared.md',
                    'living-dir': root / 'openspec/specs',
                    'ledger-dir': root / '.agentflow',
                    'lock-file': root / '.agentflow/state.lock',
                }
                managed = paths[location]
                outside = base / 'external'
                managed.rename(outside)
                managed.symlink_to(outside, target_is_directory=outside.is_dir())
                before = {str(p.relative_to(outside)): p.read_bytes() for p in outside.rglob('*') if p.is_file()} if outside.is_dir() else outside.read_bytes()
                with self.assertRaisesRegex(ValueError, 'Symlinks'):
                    lifecycle.apply_and_archive_openspec(root, 'alpha', force=True)
                after = {str(p.relative_to(outside)): p.read_bytes() for p in outside.rglob('*') if p.is_file()} if outside.is_dir() else outside.read_bytes()
                self.assertEqual(before, after)
                self.assertTrue(managed.is_symlink())
                if location in ('package', 'changes'):
                    with self.assertRaisesRegex(ValueError, 'Symlinks'):
                        lifecycle.create_checkpoint(root, 'design', change='alpha')
                    with self.assertRaisesRegex(ValueError, 'Symlinks'):
                        lifecycle.inspect_openspec(root, target_change='alpha')


if __name__ == '__main__':
    unittest.main()
