"""Regression tests for installed runtime and delivery enforcement boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ship.lifecycle.gates import validate_delivery_readiness
from ship.lifecycle.engine import LifecycleEngine
from ship.lifecycle.convergence import ConvergenceConfig
from ship.lifecycle.verification import verify_test_quality
from ship.mcp.tools import dispatch_tool


class StabilizationTests(unittest.TestCase):
    def test_delivery_requires_current_execution_verification(self):
        pkg = {'change': 'demo', 'total_tasks': 1, 'completed_tasks': 1, 'pending_tasks': 0}
        report = dict(status='complete', reviewer='judge', is_judge=True, change='demo', findings=[],
                      critical_or_high_count=0, test_evidence_passed=True, verdict='PASS', judge_report_valid=True)
        git = {'is_git': False, 'working_tree_fingerprint': 'current'}
        for execution in (None, {}, {'verdict': 'INCONCLUSIVE'}, {'verdict': 'SKIPPED'},
                          {'verdict': 'VERIFIED', 'metadata': {'snapshot_fingerprint': 'old'}}):
            with self.subTest(execution=execution):
                change = {'change_id': 'demo', 'verification': {'execution': execution}}
                self.assertEqual(validate_delivery_readiness(report, pkg, git, change)[1], 'VERIFICATION_FAILED')
        change = {'change_id': 'demo', 'verification': {'execution': {
            'verdict': 'VERIFIED', 'metadata': {'snapshot_fingerprint': 'current',
                'tests_run': 1, 'exit_code': 0, 'failed_count': 0}}}}
        self.assertEqual(validate_delivery_readiness(report, pkg, git, change)[1], 'DELIVERY_READY')

    def test_engine_passes_custom_convergence_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.agentflow.json').write_text(json.dumps({'version': 1, 'convergence': {'max_total_turns': 1}}))
            with patch('ship.lifecycle.engine.determine_lifecycle_state', return_value=('design', 'INITIAL_PROPOSAL', 'start')) as gate:
                LifecycleEngine().evaluate_repository(root)
            self.assertEqual(ConvergenceConfig.from_dict(gate.call_args.kwargs['verification_config']).max_total_turns, 1)

    def test_mcp_rejects_mutation_without_host_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            with self.assertRaises(PermissionError):
                dispatch_tool('ship_spike_run', {'command': 'touch forbidden', 'path': tmp})
            with self.assertRaises(PermissionError):
                dispatch_tool('ship_record_turn', {'skill': 'tdd', 'path': tmp})
            self.assertEqual(list(root.iterdir()), [])

    def test_mutation_tool_presence_does_not_prove_mutations_ran(self):
        with tempfile.TemporaryDirectory() as tmp, patch('ship.lifecycle.verification.shutil.which', return_value='/bin/true'):
            result = verify_test_quality(Path(tmp), changed_files=['service.py'])
            self.assertEqual(result.verdict, 'INCONCLUSIVE')

    def test_cli_starts_in_fresh_process(self):
        result = subprocess.run([sys.executable, '-m', 'ship.cli', '--version'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_successful_verification_review_cycles_do_not_halt(self):
        from ship.lifecycle.convergence import evaluate_convergence
        turns = [
            {'skill': 'verification', 'evidence': {'execution': {'verdict': 'VERIFIED'}}},
            {'skill': 'review', 'evidence': {'verdict': 'PASS'}},
        ] * 2
        self.assertFalse(evaluate_convergence({'turns': turns}).is_halted)

    def test_installer_preserves_invalid_mcp_config(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'skills'
            target.mkdir()
            config = target / 'mcp_config.json'
            config.write_text('{invalid existing configuration')
            bin_dir = Path(tmp) / 'bin'
            bin_dir.mkdir()
            executable = bin_dir / 'ship'
            executable.write_text('#!/bin/sh\nexit 0\n')
            executable.chmod(0o755)
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['bash', str(repo / 'scripts/setup/install_skills.sh'), '--target', str(target), '--mcp'],
                                    env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config.read_text(), '{invalid existing configuration')

    def test_mcp_execution_receipt_unblocks_delivery_then_goes_stale(self):
        import shlex
        import test_archive_recovery as fixtures
        from ship.lifecycle.vcs import GitClient
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'AGENTFLOW_MCP_ALLOW_MUTATIONS': '1'}):
            root = Path(tmp)
            fixtures.ArchiveRecoveryTests().workspace(root)
            command = shlex.quote(sys.executable) + ' -c ' + shlex.quote(
                'import unittest; from pathlib import Path; '
                'case=unittest.FunctionTestCase(lambda: unittest.TestCase().assertTrue(Path("openspec/changes/alpha/tasks.md").is_file())); '
                'result=unittest.TextTestRunner().run(case); raise SystemExit(not result.wasSuccessful())')
            (root / '.agentflow.json').write_text(json.dumps({'version': 1, 'gates': {'implementation': {'test': command}}}))
            report_path = root / '.agentflow/reviews/alpha/review_report.json'
            report = json.loads(report_path.read_text())
            report['working_tree_fingerprint'] = GitClient().compute_working_tree_fingerprint(root)
            report_path.write_text(json.dumps(report))
            engine = LifecycleEngine()
            self.assertEqual(engine.evaluate_repository(root, target_change='alpha')['state_key'], 'VERIFICATION_FAILED')
            result = dispatch_tool('ship_verify', {'path': tmp, 'change': 'alpha'})
            self.assertEqual(result['execution']['verdict'], 'VERIFIED')
            self.assertEqual(engine.evaluate_repository(root, target_change='alpha')['state_key'], 'DELIVERY_READY')
            (root / 'new_source.py').write_text('broken = True\n')
            self.assertNotEqual(engine.evaluate_repository(root, target_change='alpha')['state_key'], 'DELIVERY_READY')
