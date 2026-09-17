"""Exercise the installed CLI from a consumer project, without CI or source imports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_archive_recovery as fixtures

ROOT = Path(__file__).resolve().parents[1]


class LocalRolloutTests(unittest.TestCase):
    def test_installed_approval_resume_archive_and_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            install = base / 'installed skills'
            project = base / 'consumer project'
            project.mkdir()
            subprocess.run(['bash', str(ROOT / 'scripts/install.sh'), '--target', str(install), '--mode', 'copy'], check=True, capture_output=True)
            script = install / 'ship/scripts/inspect_lifecycle.py'
            def cli(*args, code=0):
                result = subprocess.run([sys.executable, str(script), *args], cwd=project, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
                return result
            self.assertEqual(cli("--version").stdout.strip(), "0.2.0-rc.1")
            self.assertTrue(json.loads(cli("--doctor", "--format", "json").stdout)["ok"])
            self.assertEqual(list(project.iterdir()), [])
            fixtures.ArchiveRecoveryTests().workspace(project)
            beta = project / 'openspec/changes/beta'
            beta.mkdir()
            (beta / 'tasks.md').write_text('- [ ] Beta task\n')
            os.utime(project / 'openspec/changes/alpha', (1000, 1000))
            os.utime(beta, (2000, 2000))
            cli('--set-active-change', 'alpha')
            digest = cli('--change', 'alpha', '--design-fingerprint').stdout.strip()
            cli('--change', 'alpha', '--approve-design', digest, '--approved-by', 'session-user')
            state = json.loads((project / '.ship/state.json').read_text())
            self.assertEqual(state['active_change_id'], 'alpha')
            self.assertEqual(json.loads(cli('--format', 'json').stdout)['target_change'], 'alpha')
            # A different change's approval must not steal or clear the selected change.
            beta_digest = cli('--change', 'beta', '--design-fingerprint').stdout.strip()
            cli('--change', 'beta', '--approve-design', beta_digest, '--approved-by', 'session-user')
            self.assertEqual(json.loads(cli('--format', 'json').stdout)['target_change'], 'alpha')
            # The review must cover the current workspace, including the other package.
            report_path = project / '.scratch/alpha/review_report.json'
            report = json.loads(report_path.read_text())
            report['working_tree_fingerprint'] = cli('--fingerprint').stdout.strip()
            report_path.write_text(json.dumps(report))
            cli('--change', 'alpha', '--record-review', str(report_path))
            cli('--change', 'alpha', '--status-check')
            archive = json.loads(cli('--archive', 'alpha', '--format', 'json').stdout)
            self.assertIn('Ship-Design: PASSED', archive['trailers'])
            self.assertIn('specify --change', cli('--generate-trailers', code=1).stderr)
            trailers = json.loads(cli('--generate-trailers', '--change', 'alpha', '--format', 'json').stdout)['trailers']
            self.assertEqual(trailers, archive['trailers'])
            (project / 'unrelated.py').write_text('changed = True\n')
            self.assertEqual(json.loads(cli('--generate-trailers', '--change', 'alpha', '--format', 'json').stdout)['trailers'], trailers)

    def test_bad_config_blocks_readiness_without_mutating_ledger(self):
        script = ROOT / 'skills/ship/scripts/inspect_lifecycle.py'
        for config in ('{broken', '[]', 'null', '{"gates": null}', '{"gates":{"implementation":{"test":false}}}', '{"gates":{"review":{"max_iterations":0}}}', '{"gates":{"implementaton":{}}}'):
            with self.subTest(config=config), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fixtures.ArchiveRecoveryTests().workspace(root)
                before = (root / '.ship/state.json').read_bytes()
                (root / '.ship.json').write_text(config)
                result = subprocess.run([sys.executable, str(script), '--path', str(root), '--status-check'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn('Invalid Ship configuration', result.stderr)
                self.assertEqual((root / '.ship/state.json').read_bytes(), before)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures.ArchiveRecoveryTests().workspace(root)
            result = subprocess.run([sys.executable, str(script), '--path', str(root), '--status-check', '--config', 'missing.json'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('missing.json', result.stderr)
