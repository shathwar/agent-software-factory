"""Turn contracts and provenance must behave identically across both distributions."""
import contextlib
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'skills/ship/scripts'))


class TurnRegressionTests(unittest.TestCase):
    def test_all_emitted_design_states_require_design_work(self):
        for namespace in ('lifecycle', 'ship.lifecycle'):
            turns = importlib.import_module(namespace + '.turns')
            engine = importlib.import_module(namespace + '.engine').LifecycleEngine()
            for status in ('ADR_PROPOSED', 'ADR_ACCEPTED', 'SPEC_UNFINISHED'):
                with self.subTest(namespace=namespace, status=status), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    if status == 'SPEC_UNFINISHED':
                        pkg = root / 'openspec/changes/alpha'
                        pkg.mkdir(parents=True)
                        (pkg / 'proposal.md').write_text('Incomplete specification\n')
                    else:
                        adr = root / 'docs/adr/ADR-1.md'
                        adr.parent.mkdir(parents=True)
                        adr.write_text('**Status**: ' + ('ACCEPTED' if status == 'ADR_ACCEPTED' else 'PROPOSED'))
                    evaluation = engine.evaluate_repository(root)
                    self.assertEqual(evaluation['state_key'], status)
                    contract = turns.get_next_turn_contract(evaluation)
                    self.assertEqual(contract.skill, 'design')
                    self.assertNotIn('Lifecycle is clean', contract.action_prompt)
            with self.assertRaisesRegex(ValueError, 'Unsupported lifecycle state'):
                turns.get_next_turn_contract({'state_key': 'NEW_UNHANDLED_STATE'})
            self.assertIn('Lifecycle is clean', turns.get_next_turn_contract({'state_key': 'ARCHIVED'}).action_prompt)

    def test_review_contract_honors_team_policy_and_dirty_snapshot(self):
        for namespace in ('lifecycle', 'ship.lifecycle'):
            planner = importlib.import_module(namespace + '.turns').get_next_turn_contract
            evaluation = {'state_key': 'REVIEW_ACTIVE', 'target_change': 'alpha',
                          'git': {'commit': 'same-head', 'working_tree_fingerprint': 'dirty-a'},
                          'config': {'gates': {'review': {'base_branch': 'develop', 'max_iterations': 5,
                                                         'reviewers': ['correctness', 'judge'], 'critical_paths': ['billing/']}}}}
            contract = planner(evaluation)
            self.assertEqual(contract.inputs['base_branch'], 'develop')
            self.assertEqual(contract.inputs['reviewers'], ['correctness', 'judge'])
            self.assertEqual(contract.inputs['critical_paths'], ['billing/'])
            self.assertEqual(contract.inputs['max_iterations'], 5)
            self.assertIn('5 repair iterations', ' '.join(contract.hard_constraints))
            self.assertEqual(contract.inputs['tree_fingerprint'], 'dirty-a')
            evaluation['git']['working_tree_fingerprint'] = 'dirty-b'
            self.assertEqual(planner(evaluation).inputs['tree_fingerprint'], 'dirty-b')

    def test_invalid_turns_do_not_write_or_increment_revision(self):
        invalid = [[], {'inputs': ['app.py']}, {'evidence': None}, {'state_delta': False},
                   {'skill': 5}, {'harness': ''}, {'execution_mode': 'invented'}, {'change_id': 'other'}]
        for namespace in ('lifecycle', 'ship.lifecycle'):
            store = importlib.import_module(namespace + '.ledger').FileLedgerStore
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                store.record_turn(root, {'skill': 'review', 'inputs': {'file': 'app.py'}}, change_id='alpha')
                path = root / '.agentflow/state.json'
                before = path.read_bytes()
                for payload in invalid:
                    with self.subTest(namespace=namespace, payload=payload):
                        with self.assertRaises(ValueError):
                            store.record_turn(root, payload, change_id='alpha')
                        self.assertEqual(path.read_bytes(), before)

    def test_legacy_bad_records_remain_exportable_without_text_rendering(self):
        for module_name in ('inspect_lifecycle', 'ship.cli'):
            cli = importlib.import_module(module_name)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / '.agentflow').mkdir()
                turns = [{'skill': 'review', 'inputs': ['app.py']}]
                state = {'version': 1, 'active_change_id': 'alpha', 'changes': {'alpha': {'turns': turns}}}
                path = root / '.agentflow/state.json'
                path.write_text(json.dumps(state))
                before = path.read_bytes()
                stdout = io.StringIO()
                with patch.object(cli, 'format_turns_log', side_effect=AssertionError('JSON invoked text formatter')), contextlib.redirect_stdout(stdout):
                    self.assertEqual(cli.main(['--path', str(root), '--turns', '--format', 'json']), 0)
                self.assertEqual(json.loads(stdout.getvalue()), turns)
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(cli.main(['--path', str(root), '--turns']), 0)
                self.assertIn('INVALID', stdout.getvalue())
                self.assertEqual(path.read_bytes(), before)

    def test_cli_rejects_bad_records_and_accepts_valid_records(self):
        for module_name in ('inspect_lifecycle', 'ship.cli'):
            cli = importlib.import_module(module_name)
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                args = ['--path', tmp, '--change', 'alpha', '--record-turn']
                for payload in ('{"inputs":["app.py"]}', '{broken', '[]'):
                    self.assertEqual(cli.main(args + [payload]), 1)
                    self.assertFalse((Path(tmp) / '.agentflow/state.json').exists())
                self.assertEqual(cli.main(args + [json.dumps({'skill': 'review', 'inputs': {'context': 'x' * 500}})]), 0)


    def test_mcp_provenance_validates_and_returns_the_saved_entry(self):
        from ship.mcp.tools import handle_ship_record_turn
        with tempfile.TemporaryDirectory() as tmp:
            for extra in ({'inputs': []}, {'evidence': False}, {'execution_mode': ''}):
                with self.assertRaises(ValueError):
                    handle_ship_record_turn(dict(path=tmp, change='alpha', skill='review', **extra))
                self.assertFalse((Path(tmp) / '.agentflow/state.json').exists())
            result = handle_ship_record_turn({'path': tmp, 'change': 'alpha', 'skill': 'review', 'inputs': {}})
            self.assertEqual(result['change_id'], 'alpha')
            self.assertEqual(result['turns'][-1]['skill'], 'review')
