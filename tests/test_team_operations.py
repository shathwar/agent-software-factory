"""Local deployment contracts: doctor, migration, profiles, and one readiness rule."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_archive_recovery as fixtures
from lifecycle.config import ShipConfigManager
from lifecycle.operations import doctor, migrate_state
from lifecycle.ledger import FileLedgerStore


class TeamOperationsTests(unittest.TestCase):
    def test_doctor_never_initializes_or_repairs_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = doctor(root)
            self.assertTrue(result['ok'], result)
            self.assertEqual(list(root.iterdir()), [])
            (root / '.ship').mkdir()
            (root / '.ship/state.json').write_text('corrupt')
            before = (root / '.ship/state.json').read_bytes()
            result = doctor(root)
            self.assertFalse(result['ok'])
            self.assertEqual((root / '.ship/state.json').read_bytes(), before)
            self.assertFalse((root / '.ship/state.lock').exists())

    def test_doctor_reports_pending_recovery_without_running_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.ship').mkdir()
            journal = root / '.ship/archive-transaction.json'
            journal.write_text('not a real transaction')
            self.assertFalse(doctor(root)['ok'])
            self.assertEqual(journal.read_text(), 'not a real transaction')
            self.assertFalse((root / '.ship/state.lock').exists())

    def test_migration_preserves_legacy_bytes_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures.ArchiveRecoveryTests().workspace(root)
            path = root / '.ship/state.json'
            state = json.loads(path.read_text())
            state.pop('version')
            path.write_text(json.dumps(state, indent=4))
            before = path.read_bytes()
            result = migrate_state(root)
            self.assertTrue(result['changed'])
            self.assertEqual(Path(result['backup']).read_bytes(), before)
            expected = dict(state, version=1)
            self.assertEqual(json.loads(path.read_text()), expected)
            self.assertFalse(migrate_state(root)['changed'])
            self.assertEqual(len(list((root / '.ship').glob('state.pre-v1-*'))), 1)

    def test_migration_refuses_unknown_state_and_handles_failed_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.ship').mkdir()
            path = root / '.ship/state.json'
            path.write_text('{"version": 999, "changes": {}}')
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                migrate_state(root)
            self.assertEqual(path.read_bytes(), before)
            path.write_text('{"changes": {}}')
            before = path.read_bytes()
            with patch('lifecycle.operations.atomic_write', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    migrate_state(root)
            self.assertEqual(path.read_bytes(), before)

    def test_profiles_apply_defaults_then_explicit_team_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / '.ship.json'
            config.write_text(json.dumps({'workflow': {'profile': 'small-fix', 'execution': 'sequential'}}))
            self.assertEqual(ShipConfigManager.load(root)['gates']['review']['reviewers'], ['correctness', 'judge'])
            config.write_text(json.dumps({'workflow': {'profile': 'small-fix'}, 'gates': {'review': {'reviewers': ['design', 'judge']}}}))
            self.assertEqual(ShipConfigManager.load(root)['gates']['review']['reviewers'], ['design', 'judge'])
            for workflow in ({'profile': []}, {'profile': 'unknown'}, {'execution': 'pretend'}):
                config.write_text(json.dumps({'workflow': workflow}))
                with self.assertRaises(ValueError):
                    ShipConfigManager.load(root)

    def test_pending_tasks_block_every_surface_even_after_fresh_passing_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures.ArchiveRecoveryTests().workspace(root)
            (root / 'openspec/changes/alpha/tasks.md').write_text('- [ ] Done\n')
            report_path = root / '.scratch/alpha/review_report.json'
            report = json.loads(report_path.read_text())
            report['working_tree_fingerprint'] = fixtures.lifecycle.compute_working_tree_fingerprint(root)
            report_path.write_text(json.dumps(report))
            entry = fixtures.lifecycle.record_review_to_ledger(root, report_path, change_id='alpha')
            self.assertEqual(entry['phase'], 'implementation')
            self.assertEqual(fixtures.lifecycle.evaluate_repository(root, target_change='alpha')['state_key'], 'TDD_ACTIVE')
            trailers = fixtures.lifecycle.generate_gate_trailers(root, change_id='alpha')
            self.assertIn('Ship-Implementation: IN_PROGRESS (0/1 tasks)', trailers)
            self.assertIn('Ship-Delivery: BLOCKED', trailers)
            with self.assertRaisesRegex(RuntimeError, 'pending tasks'):
                fixtures.lifecycle.apply_and_archive_openspec(root, 'alpha')


    def test_local_envelope_is_archived_without_git_notes_recording(self):
        import re
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures.ArchiveRecoveryTests().workspace(root)
            (root / '.scratch/alpha/review_report.json').unlink()
            # Use the documented example as the consumer would, filling its snapshot.
            schema_doc = Path(__file__).resolve().parents[1] / 'skills/review/references/finding_schema.md'
            example = re.search(r"```json delivery_evidence\n(.*?)\n```", schema_doc.read_text(), re.S).group(1)
            report = json.loads(example)
            self.assertIn('change', report)
            report['change'] = 'alpha'
            report['snapshot'] = {'working_tree_fingerprint': fixtures.lifecycle.compute_working_tree_fingerprint(root)}
            (root / '.scratch/delivery_evidence.json').write_text(json.dumps(report))
            FileLedgerStore.mutate_change(root, 'alpha', lambda e: e['evidence'].update(review={'status': 'PENDING'}))
            self.assertEqual(fixtures.lifecycle.evaluate_repository(root, target_change='alpha')['state_key'], 'DELIVERY_READY')
            result = fixtures.lifecycle.apply_and_archive_openspec(root, 'alpha')
            self.assertIn('Ship-Review: PASS (by judge)', result['trailers'])
            self.assertEqual(fixtures.lifecycle.generate_gate_trailers(root, 'alpha'), result['trailers'])
