"""External SDD handoffs preserve Ship gates without a provider file layout."""
import copy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import shlex
import unittest

from ship.lifecycle.config import ShipConfigManager
from ship.lifecycle.engine import LifecycleEngine
from ship.lifecycle.evidence import design_fingerprint, validate_design_approval
from ship.lifecycle.specs import OpenSpecRepository
from ship.lifecycle.turns import get_next_turn_contract


class ExternalSDDTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / '.agentflow').mkdir()
        (self.root / 'planning').mkdir()
        (self.root / 'planning/feature.txt').write_text('Return zero for empty input.')
        self.config = {'version': 1, 'sdd': {'provider': 'example', 'skills': {
            op: f'example-{op}' for op in ('prepare', 'inspect', 'verify', 'finalize')}}}
        self.change = {'change': 'feature', 'artifacts': [
            {'id': 'requirements', 'path': 'planning/feature.txt'}],
            'tasks': [{'id': 'one', 'description': 'Implement empty input', 'completed': False}]}
        self.save()

    def save(self):
        (self.root / '.agentflow.json').write_text(json.dumps(self.config))
        (self.root / '.agentflow/sdd.json').write_text(json.dumps({
            'version': 1, 'provider': self.config['sdd']['provider'], 'changes': [self.change]}))

    def test_external_layout_drives_approval_tasks_and_turns(self):
        engine = LifecycleEngine()
        evaluation = engine.evaluate_repository(self.root, target_change='feature')
        self.assertEqual(evaluation['state_key'], 'DESIGN_APPROVAL_REQUIRED')
        digest = design_fingerprint(self.root, 'feature')
        engine.ledger.approve_design(self.root, 'feature', digest, 'user')
        evaluation = engine.evaluate_repository(self.root, target_change='feature')
        self.assertEqual(evaluation['state_key'], 'TDD_ACTIVE')
        turn = get_next_turn_contract(evaluation)
        self.assertEqual(turn.inputs['sdd']['skills']['inspect'], 'example-inspect')
        self.assertNotIn('openspec/', json.dumps(turn.__dict__))
        self.change['tasks'][0]['completed'] = True
        self.save()
        self.assertEqual(design_fingerprint(self.root, 'feature'), digest)
        self.assertEqual(engine.evaluate_repository(self.root, target_change='feature')['state_key'], 'REVIEW_ACTIVE')
        self.change['tasks'][0]['description'] = 'Change the API'
        self.save()
        self.assertEqual(engine.evaluate_repository(self.root, target_change='feature')['state_key'], 'DESIGN_APPROVAL_REQUIRED')

    def test_content_provider_and_artifact_inventory_bind_approval(self):
        digest = design_fingerprint(self.root, 'feature')
        entry = {'evidence': {'design': {'approval': {'change': 'feature', 'approved_by': 'user', 'fingerprint': digest}}}}
        (self.root / 'planning/feature.txt').write_text('Changed requirement')
        self.assertIsNotNone(validate_design_approval(self.root, 'feature', entry))
        (self.root / 'planning/feature.txt').write_text('Return zero for empty input.')
        self.config['sdd']['skills']['prepare'] = 'different-prepare'
        self.save()
        self.assertIsNotNone(validate_design_approval(self.root, 'feature', entry))

    def test_relocation_preserves_design_but_missing_and_unsafe_artifacts_fail(self):
        digest = design_fingerprint(self.root, 'feature')
        (self.root / 'planning/feature.txt').rename(self.root / 'planning/archived.txt')
        self.change['artifacts'][0]['path'] = 'planning/archived.txt'
        self.save()
        self.assertEqual(design_fingerprint(self.root, 'feature'), digest)
        for path in ('../outside', '/tmp/outside', 'planning/missing.txt'):
            self.change['artifacts'][0]['path'] = path
            self.save()
            with self.assertRaises((ValueError, OSError)):
                OpenSpecRepository().inspect_openspec(self.root, target_change='feature')

    def test_invalid_handoffs_fail_closed(self):
        original = copy.deepcopy(self.change)
        for tasks in ([{'id': 'one', 'description': 'Task', 'completed': 'false'}],
                      [original['tasks'][0], original['tasks'][0]]):
            self.change['tasks'] = tasks
            self.save()
            with self.assertRaises(ValueError):
                OpenSpecRepository().inspect_openspec(self.root)
        self.change = original
        self.config['sdd']['skills'].pop('verify')
        self.save()
        with self.assertRaises(ValueError):
            ShipConfigManager.load(self.root)

    def test_missing_snapshot_never_falls_back_to_legacy(self):
        (self.root / '.agentflow/sdd.json').unlink()
        (self.root / 'openspec/changes/other').mkdir(parents=True)
        self.assertEqual(OpenSpecRepository().inspect_openspec(self.root), [])
        with self.assertRaises(ValueError):
            OpenSpecRepository().inspect_openspec(self.root, target_change='feature')

    def test_verified_delivery_finalize_and_stale_evidence(self):
        from ship.lifecycle.vcs import GitClient
        from ship.lifecycle.trailers import CommitTrailerGenerator
        self.change['tasks'][0]['completed'] = True
        self.config['gates'] = {'implementation': {'test': f'{shlex.quote(sys.executable)} -B -m unittest discover -v'}}
        self.save()
        (self.root / '.gitignore').write_text('.agentflow/\n__pycache__/\n')
        (self.root / 'calc.py').write_text('def empty(): return 0\n')
        (self.root / 'test_calc.py').write_text('import unittest\nfrom calc import empty\nclass Check(unittest.TestCase):\n    def test_empty(self): self.assertEqual(empty(), 0)\n')
        for args in [('init', '-q', '-b', 'main'), ('config', 'user.name', 'Fixture'),
                     ('config', 'user.email', 'fixture@example.invalid'), ('config', 'commit.gpgsign', 'false'),
                     ('add', '.'), ('commit', '-qm', 'initial')]:
            subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)
        engine = LifecycleEngine()
        digest = design_fingerprint(self.root, 'feature')
        engine.ledger.approve_design(self.root, 'feature', digest, 'user')
        fp = GitClient().compute_working_tree_fingerprint(self.root)
        (self.root / '.agentflow/spec-review.md').write_text('Empty-input requirement checked against implementation and test.')
        self.change['verification'] = {'verdict': 'PASS', 'report': '.agentflow/spec-review.md',
            'design_fingerprint': digest, 'tree_fingerprint': fp}
        self.save()
        report = {'change': 'feature', 'reviewer': 'judge', 'status': 'complete', 'verdict': 'PASS',
                  'findings': [], 'coverage': ['correctness'], 'questions': [], 'routing_notes': [],
                  'test_evidence': {'passed': True, 'tests_run': 1, 'failed_count': 0, 'exit_code': 0},
                  'working_tree_fingerprint': fp}
        report_path = self.root / '.agentflow/reviews/feature/review_report.json'
        report_path.parent.mkdir(parents=True)
        report_path.write_text(json.dumps(report))
        engine.ledger.record_review(self.root, report_path, change_id='feature')
        engine.verify_change(self.root, 'feature', tiers=['execution'])
        self.assertEqual(engine.evaluate_repository(self.root, 'feature')['state_key'], 'DELIVERY_READY')
        self.assertIn('Ship-Delivery: READY', CommitTrailerGenerator.generate(self.root, 'feature'))
        with self.assertRaisesRegex(RuntimeError, 'finalize skill'):
            engine.archive_change(self.root, 'feature')
        for field in ('tree_fingerprint', 'design_fingerprint'):
            old = self.change['verification'][field]
            self.change['verification'][field] = 'stale'
            self.save()
            self.assertEqual(engine.evaluate_repository(self.root, 'feature')['state_key'], 'REVIEW_ACTIVE')
            with self.assertRaises(RuntimeError):
                engine.archive_change(self.root, 'feature')
            self.change['verification'][field] = old
        (self.root / '.agentflow/finalized.md').write_text('Provider finalized feature. Artifacts retained at planning/feature.txt.')
        self.change['finalization'] = '.agentflow/finalized.md'
        self.save()
        result = engine.archive_change(self.root, 'feature')
        self.assertEqual(result['provider'], 'example')
        self.assertEqual(engine.evaluate_repository(self.root, 'feature')['state_key'], 'ARCHIVED')
        self.assertIn('Ship-Delivery: ARCHIVED', CommitTrailerGenerator.generate(self.root, 'feature'))
        self.assertEqual(engine.archive_change(self.root, 'feature'), result)
        self.assertTrue((self.root / 'planning/feature.txt').is_file())
        self.assertEqual(OpenSpecRepository().inspect_openspec(self.root), [])
        other = copy.deepcopy(self.change)
        other['change'] = 'next-feature'
        other['tasks'][0]['completed'] = False
        (self.root / '.agentflow/sdd.json').write_text(json.dumps({
            'version': 1, 'provider': 'example', 'changes': [self.change, other]}))
        self.assertEqual(engine.evaluate_repository(self.root)['target_change'], 'next-feature')

    def test_archive_cannot_bypass_ship_gates_or_invoke_provider(self):
        with self.assertRaises(RuntimeError):
            LifecycleEngine().archive_change(self.root, 'feature', force=True)
        self.assertTrue((self.root / 'planning/feature.txt').exists())


if __name__ == '__main__':
    unittest.main()
