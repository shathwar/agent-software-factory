"""Guard coverage mappings against stale sources and falsely elevated test coverage."""

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_skill_coverage", ROOT / "scripts/verify/check_coverage.py")
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


class SkillCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "tests/skill_coverage.json").read_text())

    def setUp(self):
        self.data = deepcopy(self.manifest)

    def assert_invalid(self, message):
        with self.assertRaisesRegex(coverage.CoverageError, message):
            coverage.validate_manifest(self.data)

    def test_current_inventory_covers_all_skills_and_contracts(self):
        coverage.validate_manifest(self.data)
        self.assertEqual(set(self.data['skills']),
                         {p.parent.name for p in (ROOT / 'skills').glob('*/SKILL.md')})

    def test_deleted_skill_or_contract_mapping_fails(self):
        del self.data['skills']['debug']
        self.assert_invalid('every skill')
        self.data = deepcopy(self.manifest)
        for step in self.data['skills']['debug']['steps']:
            step['turn_contracts'] = []
        self.assert_invalid('unmapped turn contracts')

    def test_changed_skill_requires_review(self):
        self.data['source_digests']['skills/debug/SKILL.md'] = '0' * 64
        self.assert_invalid('source drift')

    def test_new_contract_is_caught_even_after_digest_refresh(self):
        # A minimal repository demonstrates detection of new requirements, not
        # just checksum changes. No real skill source is modified.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'skills/example/SKILL.md'
            source.parent.mkdir(parents=True)
            source.write_text('<turn_contract>\n✓ 1. First\n✓ 2. New requirement\n</turn_contract>')
            data = {
                'schema_version': 1, 'scope': 'Example', 'limitations': ['Inventory only'],
                'source_digests': {'skills/example/SKILL.md': hashlib.sha256(source.read_bytes()).hexdigest()},
                'validators': {}, 'eval_cases': {},
                'skills': {'example': {'source': 'skills/example/SKILL.md', 'steps': [{
                    'id': 'example.first', 'title': 'First',
                    'requirement': {'path': 'skills/example/SKILL.md', 'text': 'First'},
                    'applies_when': 'Always', 'turn_contracts': [1],
                    'expected_evidence': ['Receipt'], 'validators': [], 'eval_cases': [], 'gaps': ['No capture'],
                }]}},
            }
            with self.assertRaisesRegex(coverage.CoverageError, 'unmapped turn contracts'):
                coverage.validate_manifest(data, root)

    def test_stale_validator_or_test_symbol_fails(self):
        self.data['validators']['execution']['reference']['symbol'] = 'removed_function'
        self.assert_invalid('missing symbol')
        self.data = deepcopy(self.manifest)
        self.data['eval_cases']['runner-receipts']['reference']['symbol'] = 'RemovedTests.test_missing'
        self.assert_invalid('missing symbol')

    def test_stale_manual_case_and_requirement_selectors_fail(self):
        self.data['eval_cases']['m-red']['reference']['text'] = 'Removed acceptance scenario'
        self.assert_invalid('missing text selector')
        self.data = deepcopy(self.manifest)
        self.data['skills']['tdd']['steps'][0]['requirement']['text'] = 'Removed requirement'
        self.assert_invalid('missing text selector')

    def test_untracked_requirement_digest_fails(self):
        del self.data['source_digests']['skills/debug/SKILL.md']
        self.assert_invalid('source_digests')

    def test_unknown_reference_duplicate_id_and_empty_evidence_fail(self):
        step = self.data['skills']['debug']['steps'][0]
        step['validators'] = ['nonexistent']
        self.assert_invalid('unknown validators')
        step['validators'] = []
        step['expected_evidence'] = []
        self.assert_invalid('must not be empty')
        step['expected_evidence'] = ['Receipt']
        self.data['skills']['debug']['steps'].append(deepcopy(step))
        self.assert_invalid('duplicate step ID')

    def test_paths_cannot_escape_repository(self):
        for path in ('../outside.py', '/tmp/outside.py'):
            with self.subTest(path=path):
                self.data['validators']['execution']['reference']['path'] = path
                self.assert_invalid('repository-relative')

    def test_malformed_fields_fail_as_validation_errors(self):
        for value in (None, [], 'wrong shape'):
            with self.subTest(value=value):
                self.data['skills']['debug']['steps'] = value
                self.assert_invalid('missing steps')

    def test_component_checks_are_not_agent_evaluations(self):
        report = coverage.inventory_report(self.data, 'ux')
        self.assertGreater(report['skills']['ux']['with_automated_component_cases'], 0)
        self.assertEqual(report['skills']['ux']['with_manual_agent_cases'], 0)
        self.assertTrue(all(s['agent_evaluation'] == 'missing' for s in report['steps']))
        self.data['eval_cases']['ux-fixtures']['kind'] = 'automated_agent'
        self.assert_invalid('unsupported eval kind')

    def test_manual_cases_remain_manual_and_gaps_are_not_failures(self):
        coverage.validate_manifest(self.data)
        report = coverage.inventory_report(self.data, 'design')
        self.assertEqual(report['inventory_status'], 'valid')
        self.assertTrue(any(s['agent_evaluation'] == 'manual_only' for s in report['steps']))
        self.assertTrue(all(s['gaps'] for s in report['steps']))

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(coverage.CoverageError, 'Duplicate JSON key'):
            json.loads('{"skills": {}, "skills": {}}', object_pairs_hook=coverage.unique_object)

    def test_cli_reports_json_and_rejects_invalid_inputs(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(coverage.main(['--skill', 'tdd', '--json']), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(list(report['skills']), ['tdd'])
        self.assertEqual(report['total_steps'], len(self.manifest['skills']['tdd']['steps']))
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(coverage.main(['--skill', 'missing', '--json']), 1)
        self.assertEqual(json.loads(output.getvalue())['inventory_status'], 'invalid')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'invalid.json'
            path.write_text('[]')
            with redirect_stdout(io.StringIO()):
                self.assertEqual(coverage.main(['--manifest', str(path)]), 1)


if __name__ == '__main__':
    unittest.main()
