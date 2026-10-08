"""Regression checks for org rollout policy boundaries (no external effects)."""
import json
import tempfile
import unittest
from pathlib import Path

from ship.lifecycle.policy import (
    AllowedConfig, EnterprisePolicy, EnterprisePolicyEngine, PolicyRegistry,
    PolicyConfigurationError, PolicyInheritanceError,
)
from ship.lifecycle.execution import ActionContext, CapabilityDenied, ExternalActionAdapter
from ship.lifecycle.capabilities import CapabilityManager
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.provenance import ProvenanceManager


class PolicyBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.engine = EnterprisePolicyEngine(self.root)

    def test_workspace_canonical_containment(self):
        outside = self.root.parent / 'repo-other'
        outside.mkdir()
        (self.root / 'alias').symlink_to(outside, target_is_directory=True)
        for path in [str(outside / 'file'), '../repo-other/file', 'alias/file', '..']:
            with self.subTest(path=path):
                self.assertFalse(self.engine.evaluate_filesystem('ship', path, 'write').allowed)
        self.assertTrue(self.engine.evaluate_filesystem('ship', 'src/new/file.py', 'write').allowed)

    def test_scratch_canonical_containment(self):
        engine = EnterprisePolicyEngine(self.root, PolicyRegistry(EnterprisePolicy(
            allowed=AllowedConfig(filesystem='scratch'))))
        (self.root / '.scratch').mkdir()
        (self.root / '.scratch' / 'alias').symlink_to(self.root, target_is_directory=True)
        for path in ['.scratch/../../outside/file', '.scratch/../src.py', '.scratch/alias/src.py']:
            self.assertFalse(engine.evaluate_filesystem('ship', path, 'write').allowed)
        self.assertTrue(engine.evaluate_filesystem('ship', str(self.root / '.scratch' / 'new.py'), 'write').allowed)

    def test_secret_symlink_denied(self):
        (self.root / '.env').write_text('fixture only')
        (self.root / 'innocent').symlink_to(self.root / '.env')
        self.assertFalse(self.engine.evaluate_filesystem('ship', 'innocent').allowed)

    def test_invalid_config_does_not_fall_back(self):
        for data in ['{', '[]', '{"policy":null}', json.dumps({'policy': {'allowed': {'filesystem': 'typo'}}}),
                     json.dumps({'policy': {'allowed': {'filesystem': 'none'}, 'skills': {'child': {'forbidden': {'credentials': False}}}}})]:
            with self.subTest(data=data):
                (self.root / '.agentflow.json').write_text(data)
                with self.assertRaises((ValueError, PolicyInheritanceError)):
                    PolicyRegistry.load_from_repo(self.root)

    def test_invalid_types_and_yaml_rejected(self):
        for content in ['policy:\n  allowed:\n    network: typo', 'policy:\n  forbidden:\n    credentials: "false"',
                        'garbage', 'policy:\n  risk: high\n  risk: low', '{"allowed":{"tools":"*"}}']:
            with self.subTest(content=content), self.assertRaises(PolicyConfigurationError):
                PolicyRegistry.load_from_text(content)
        self.assertEqual(PolicyRegistry.load_from_text('allowed:\n  network: none').org_policy.allowed.network, 'none')

    def test_exact_allowlists(self):
        engine = EnterprisePolicyEngine(self.root, PolicyRegistry(EnterprisePolicy(
            allowed=AllowedConfig(commands=['pytest'], tools=['ship_status']))))
        self.assertTrue(engine.evaluate_command('ship', 'pytest').allowed)
        for command in ['touch src.py', 'pytest; touch src.py', 'pytest --unexpected']:
            self.assertFalse(engine.evaluate_command('ship', command).allowed)
        self.assertTrue(engine.evaluate_tool_call('ship', 'ship_status', {}).allowed)
        self.assertFalse(engine.evaluate_tool_call('ship', 'delete_file', {'path': 'file'}).allowed)

    def test_git_global_options_do_not_bypass_checks(self):
        for command in ['git -C . commit -m demo', 'git -C . push --force',
                        'git -c alias.x=commit x', 'git push -vf origin main', 'git push origin +HEAD:main', 'git commit -m demo']:
            with self.subTest(command=command):
                self.assertFalse(self.engine.evaluate_command('ship', command).allowed)
        engine = EnterprisePolicyEngine(self.root, PolicyRegistry(EnterprisePolicy(allowed=AllowedConfig(git='read'))))
        self.assertFalse(engine.evaluate_command('ship', 'git -C . add file').allowed)
        self.assertTrue(engine.evaluate_command('ship', 'git -C . status').allowed)
        self.assertTrue(self.engine.evaluate_command('ship', 'git -C . commit -m demo', approval_granted=True).allowed)

    def test_inheritance_cannot_widen_allowlists(self):
        for section, parent, child in [('tools', ['ship_status'], ['delete_file']),
                                       ('commands', ['pytest'], ['curl']), ('network', 'internal', 'external')]:
            with self.subTest(section=section), self.assertRaises(PolicyInheritanceError):
                PolicyRegistry.load_from_text(json.dumps({'allowed': {section: parent},
                    'skills': {'child': {'allowed': {section: child}}}}))
        registry = PolicyRegistry.load_from_text(json.dumps({'allowed': {'filesystem': 'none', 'tools': ['ship_status']},
                                                             'skills': {'child': {'risk': 'low'}}}))
        self.assertEqual(registry.get_policy_for_skill('child').allowed.filesystem, 'none')

    def test_network_policy_precedes_capability(self):
        change = 'demo'
        FileLedgerStore.save(self.root, {'version': 1, 'active_change_id': change, 'changes': {change: {}}})
        ProvenanceManager(self.root).register_identity('agent', role='MAKER', change_id=change)
        CapabilityManager(self.root).grant_capability('agent', 'NETWORK_WRITE', 'https://example.com/*',
                                                     change_id=change, approval_ref='sec_lead:audit')
        for policy in [{'allowed': {'network': 'none'}}, {'allowed': {'network': 'external'}, 'forbidden': {'network_egress': True}},
                       {'allowed': {'network': 'internal'}}, {'allowed': {'network': 'external'}, 'requires_approval': {'external_call': True}}]:
            (self.root / '.agentflow' / 'policy.json').write_text(json.dumps(policy))
            called = []
            with self.subTest(policy=policy), self.assertRaises(CapabilityDenied):
                ExternalActionAdapter(self.root).network(
                    ActionContext('agent', 'NETWORK_WRITE', 'https://example.com/*', change), lambda: called.append(True))
            self.assertEqual(called, [])
        (self.root / '.agentflow' / 'policy.json').write_text(json.dumps({'allowed': {'network': 'external'}}))
        self.assertEqual(ExternalActionAdapter(self.root).network(
            ActionContext('agent', 'NETWORK_WRITE', 'https://example.com/*', change), lambda: 'allowed'), 'allowed')

    def test_external_actions_require_policy_and_approval(self):
        self.assertFalse(self.engine.evaluate_external('ship', 'SECRET_READ', True).allowed)
        self.assertFalse(self.engine.evaluate_external('ship', 'CLOUD_MUTATE', True).allowed)
        for command in ['curl https://example.com', 'bash -c true', 'true && false']:
            self.assertFalse(self.engine.evaluate_command('ship', command).allowed)

    def test_custom_paths_cover_canonical_forms_without_credentials(self):
        (self.root / 'private').mkdir()
        (self.root / 'private' / 'data').write_text('fixture')
        (self.root / 'alias').symlink_to(self.root / 'private', target_is_directory=True)
        for credentials in (True, False):
            engine = EnterprisePolicyEngine(self.root, PolicyRegistry.load_from_text(json.dumps({
                'forbidden': {'paths': ['private/*'], 'credentials': credentials}})))
            for target in ['private/data', str(self.root / 'private/data'), 'alias/data']:
                with self.subTest(credentials=credentials, target=target):
                    decision = engine.evaluate_filesystem('ship', target)
                    self.assertFalse(decision.allowed)
                    self.assertEqual(decision.rule_violated, 'forbidden.paths')
            self.assertTrue(engine.evaluate_filesystem('ship', 'public.txt').allowed)
            self.assertEqual(engine.evaluate_filesystem('ship', '.env').allowed, not credentials)

    def test_production_command_destinations(self):
        engine = EnterprisePolicyEngine(self.root, PolicyRegistry.load_from_text(json.dumps({
            'allowed': {'network': 'external'}})))
        for command in ['git push origin HEAD:production', 'git push origin HEAD:refs/heads/prod',
                        'git push origin production', 'git push', 'git push --all origin',
                        'git push origin HEAD', 'git push origin refs/heads/*:refs/heads/*',
                        'kubectl --context prod apply -f app.yaml',
                        'kubectl apply --context=production -f app.yaml',
                        'kubectl apply -f app.yaml', 'terraform -chdir=infra apply']:
            with self.subTest(command=command):
                decision = engine.evaluate_command('ship', command, approval_granted=True)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.rule_violated, 'forbidden.production')
        self.assertTrue(engine.evaluate_command('ship', 'git push origin HEAD:feature').allowed)
        permitted = EnterprisePolicyEngine(self.root, PolicyRegistry.load_from_text(json.dumps({
            'allowed': {'network': 'external'}, 'forbidden': {'production': False}})))
        self.assertFalse(permitted.evaluate_command('ship', 'kubectl apply -f app.yaml').allowed)
        self.assertTrue(permitted.evaluate_command('ship', 'kubectl apply -f app.yaml', approval_granted=True).allowed)

    def test_dispatch_enforces_allowlist_before_handlers(self):
        from unittest.mock import patch, Mock
        from ship.mcp.tools import dispatch_tool
        (self.root / '.agentflow').mkdir()
        (self.root / '.agentflow/policy.json').write_text(json.dumps({'allowed': {'tools': []}}))
        with patch.dict('os.environ', {'AGENTFLOW_MCP_ROOT': str(self.root), 'AGENTFLOW_MCP_ALLOW_MUTATIONS': '1'}):
            for name in ['ship_review_validate', 'ship_record_tests']:
                handler = Mock(return_value={'called': True})
                with patch.dict('ship.mcp.tools.HANDLERS', {name: handler}):
                    with self.assertRaises(PermissionError):
                        dispatch_tool(name, {'path': str(self.root)})
                    handler.assert_not_called()
            (self.root / '.agentflow/policy.json').write_text(json.dumps({'allowed': {'tools': ['ship_review_validate']}}))
            result = dispatch_tool('ship_review_validate', {'report_data': {'fixture': True}})
            self.assertFalse(result['valid'])  # Real handler ran; malformed report is expected.

    def test_dispatch_cannot_switch_policy_root_or_read_excluded_report(self):
        from unittest.mock import patch, Mock
        from ship.mcp.tools import dispatch_tool
        (self.root / '.agentflow').mkdir()
        (self.root / '.agentflow/policy.json').write_text(json.dumps({'forbidden': {'paths': ['private/*']}}))
        (self.root / 'private').mkdir()
        (self.root / 'alias').symlink_to(self.root / 'private', target_is_directory=True)
        handler = Mock()
        with patch.dict('os.environ', {'AGENTFLOW_MCP_ROOT': str(self.root)}), patch.dict(
                'ship.mcp.tools.HANDLERS', {'ship_review_validate': handler}):
            for arguments in [{'path': str(self.root.parent)}, {'path': str(self.root / 'nested')},
                              {'report_path': 'alias/report.json'}]:
                with self.subTest(arguments=arguments), self.assertRaises(PermissionError):
                    dispatch_tool('ship_review_validate', arguments)
            handler.assert_not_called()

    def test_dispatch_mutation_respects_read_only_filesystem(self):
        from unittest.mock import patch, Mock
        from ship.mcp.tools import dispatch_tool
        (self.root / '.agentflow').mkdir()
        (self.root / '.agentflow/policy.json').write_text(json.dumps({'allowed': {'filesystem': 'read_only'}}))
        handler = Mock()
        with patch.dict('os.environ', {'AGENTFLOW_MCP_ROOT': str(self.root), 'AGENTFLOW_MCP_ALLOW_MUTATIONS': '1'}), patch.dict(
                'ship.mcp.tools.HANDLERS', {'ship_record_tests': handler}):
            with self.assertRaises(PermissionError):
                dispatch_tool('ship_record_tests', {})
            handler.assert_not_called()
