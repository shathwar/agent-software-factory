"""tests/test_enterprise_policy.py – Unit tests for Enterprise Policy Layer."""

import json
import tempfile
import unittest
from pathlib import Path

from ship.lifecycle.execution import ActionContext, CapabilityDenied, CapabilityGuard
from ship.lifecycle.policy import (
    AllowedConfig,
    EnterprisePolicy,
    EnterprisePolicyEngine,
    ForbiddenConfig,
    PolicyDecisionStatus,
    PolicyInheritanceError,
    PolicyRegistry,
    PolicyRisk,
    RequiresApprovalConfig,
    merge_and_validate_policy,
    parse_yaml_subset,
)


class TestYamlSubsetParser(unittest.TestCase):
    def test_parse_simple_mapping_and_types(self):
        yaml_content = """
        policy:
          skill: ship
          risk: high
          active: true
          retries: 3
          ratio: 0.75
          note: "quoted string"
        """
        parsed = parse_yaml_subset(yaml_content)
        self.assertIn("policy", parsed)
        p = parsed["policy"]
        self.assertEqual(p["skill"], "ship")
        self.assertEqual(p["risk"], "high")
        self.assertIs(p["active"], True)
        self.assertEqual(p["retries"], 3)
        self.assertEqual(p["ratio"], 0.75)
        self.assertEqual(p["note"], "quoted string")

    def test_parse_nested_and_lists(self):
        yaml_content = """
        # Comment line
        policy:
          skill: ship
          allowed:
            filesystem: workspace
            git: read/write
            tools:
              - ship_status
              - ship_evaluate
          forbidden:
            paths:
              - "*.env"
              - "id_rsa"
        """
        parsed = parse_yaml_subset(yaml_content)
        p = parsed["policy"]
        self.assertEqual(p["allowed"]["filesystem"], "workspace")
        self.assertEqual(p["allowed"]["git"], "read/write")
        self.assertEqual(p["allowed"]["tools"], ["ship_status", "ship_evaluate"])
        self.assertEqual(p["forbidden"]["paths"], ["*.env", "id_rsa"])


class TestMonotonicStrictnessLaw(unittest.TestCase):
    def setUp(self):
        self.org_policy = EnterprisePolicy(
            skill="org_default",
            risk=PolicyRisk.HIGH,
            allowed=AllowedConfig(filesystem="workspace", git="read/write"),
            requires_approval=RequiresApprovalConfig(commit=True, pull_request=True, deployment=True),
            forbidden=ForbiddenConfig(production=True, credentials=True, force_push=True),
            name="organization_default",
        )

    def test_relax_forbidden_credentials_raises_error(self):
        child = EnterprisePolicy(
            skill="rogue-skill",
            forbidden=ForbiddenConfig(credentials=False),
        )
        with self.assertRaises(PolicyInheritanceError) as ctx:
            merge_and_validate_policy(self.org_policy, child)
        self.assertIn("cannot relax forbidden.credentials", str(ctx.exception))

    def test_relax_forbidden_production_raises_error(self):
        child = EnterprisePolicy(
            skill="rogue-skill",
            forbidden=ForbiddenConfig(production=False),
        )
        with self.assertRaises(PolicyInheritanceError) as ctx:
            merge_and_validate_policy(self.org_policy, child)
        self.assertIn("cannot relax forbidden.production", str(ctx.exception))

    def test_relax_forbidden_force_push_raises_error(self):
        child = EnterprisePolicy(
            skill="rogue-skill",
            forbidden=ForbiddenConfig(force_push=False),
        )
        with self.assertRaises(PolicyInheritanceError) as ctx:
            merge_and_validate_policy(self.org_policy, child)
        self.assertIn("cannot relax forbidden.force_push", str(ctx.exception))

    def test_bypass_requires_approval_commit_raises_error(self):
        child = EnterprisePolicy(
            skill="rogue-skill",
            requires_approval=RequiresApprovalConfig(commit=False),
        )
        with self.assertRaises(PolicyInheritanceError) as ctx:
            merge_and_validate_policy(self.org_policy, child)
        self.assertIn("cannot bypass requires_approval.commit", str(ctx.exception))

    def test_bypass_requires_approval_pr_raises_error(self):
        child = EnterprisePolicy(
            skill="rogue-skill",
            requires_approval=RequiresApprovalConfig(pull_request=False),
        )
        with self.assertRaises(PolicyInheritanceError) as ctx:
            merge_and_validate_policy(self.org_policy, child)
        self.assertIn("cannot bypass requires_approval.pull_request", str(ctx.exception))

    def test_escalate_git_scope_raises_error(self):
        org = EnterprisePolicy(
            skill="org_default",
            allowed=AllowedConfig(git="read"),
        )
        child = EnterprisePolicy(
            skill="escalating-skill",
            allowed=AllowedConfig(git="read/write"),
        )
        with self.assertRaises(PolicyInheritanceError) as ctx:
            merge_and_validate_policy(org, child)
        self.assertIn("cannot escalate git scope", str(ctx.exception))

    def test_escalate_filesystem_scope_raises_error(self):
        org = EnterprisePolicy(
            skill="org_default",
            allowed=AllowedConfig(filesystem="scratch"),
        )
        child = EnterprisePolicy(
            skill="escalating-skill",
            allowed=AllowedConfig(filesystem="workspace"),
        )
        with self.assertRaises(PolicyInheritanceError) as ctx:
            merge_and_validate_policy(org, child)
        self.assertIn("cannot escalate filesystem scope", str(ctx.exception))

    def test_valid_tightening_succeeds(self):
        child = EnterprisePolicy(
            skill="read-only-reviewer",
            risk=PolicyRisk.LOW,
            allowed=AllowedConfig(filesystem="read_only", git="read"),
            forbidden=ForbiddenConfig(paths=["custom_secret.txt"]),
        )
        effective = merge_and_validate_policy(self.org_policy, child)
        self.assertEqual(effective.allowed.filesystem, "read_only")
        self.assertEqual(effective.allowed.git, "read")
        self.assertIn("custom_secret.txt", effective.forbidden.paths)
        self.assertTrue(effective.forbidden.credentials)


class TestPolicyLoadingAndDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_from_yaml_file(self):
        policy_yaml = self.root / ".agentflow" / "policy.yaml"
        policy_yaml.parent.mkdir(parents=True)
        policy_yaml.write_text(
            """
            policy:
              skill: ship
              risk: high
              allowed:
                filesystem: workspace
                git: read/write
              requires_approval:
                commit: true
                pull_request: true
                deployment: true
              forbidden:
                production: true
                credentials: true
            """,
            encoding="utf-8",
        )

        registry = PolicyRegistry.load_from_repo(self.root)
        pol = registry.get_policy_for_skill("ship")
        self.assertEqual(pol.skill, "ship")
        self.assertEqual(pol.risk, PolicyRisk.HIGH)
        self.assertEqual(pol.allowed.filesystem, "workspace")
        self.assertTrue(pol.requires_approval.commit)
        self.assertTrue(pol.forbidden.credentials)

    def test_load_from_agentflow_json(self):
        af_json = self.root / ".agentflow.json"
        af_json.write_text(
            json.dumps({
                "policy": {
                  "skill": "custom",
                  "risk": "medium",
                  "allowed": {"filesystem": "scratch", "git": "read"},
                  "forbidden": {"credentials": True, "production": True},
                }
            }),
            encoding="utf-8",
        )
        registry = PolicyRegistry.load_from_repo(self.root)
        pol = registry.get_policy_for_skill("custom")
        self.assertEqual(pol.allowed.filesystem, "scratch")
        self.assertEqual(pol.allowed.git, "read")


class TestEnterprisePolicyEngineEnforcement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine = EnterprisePolicyEngine(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_filesystem_credential_patterns_denied(self):
        for bad_path in [".env", ".env.local", "secrets.json", "id_rsa", "server.pem"]:
            dec = self.engine.evaluate_filesystem("ship", bad_path, mode="read")
            self.assertFalse(dec.allowed)
            self.assertEqual(dec.status, PolicyDecisionStatus.DENIED)
            self.assertEqual(dec.rule_violated, "forbidden.credentials")

    def test_filesystem_path_traversal_denied(self):
        dec = self.engine.evaluate_filesystem("ship", "../../etc/passwd", mode="read")
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.status, PolicyDecisionStatus.DENIED)
        self.assertEqual(dec.rule_violated, "allowed.filesystem: workspace_escape")

    def test_filesystem_read_only_blocks_mutations(self):
        # Register read_only skill
        child = EnterprisePolicy(
            skill="reviewer",
            allowed=AllowedConfig(filesystem="read_only"),
        )
        self.engine.registry.register_skill_policy(child)

        read_dec = self.engine.evaluate_filesystem("reviewer", "src/code.py", mode="read")
        self.assertTrue(read_dec.allowed)

        write_dec = self.engine.evaluate_filesystem("reviewer", "src/code.py", mode="write")
        self.assertFalse(write_dec.allowed)
        self.assertEqual(write_dec.rule_violated, "allowed.filesystem: read_only")

    def test_git_force_push_strictly_denied(self):
        dec = self.engine.evaluate_git("ship", "force_push")
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.status, PolicyDecisionStatus.DENIED)
        self.assertEqual(dec.rule_violated, "forbidden.force_push")

    def test_git_production_branch_denied(self):
        dec = self.engine.evaluate_git("ship", "push", target_branch="production")
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.status, PolicyDecisionStatus.DENIED)
        self.assertEqual(dec.rule_violated, "forbidden.production")

    def test_git_commit_approval_gate(self):
        # Without approval: requires approval
        dec = self.engine.evaluate_git("ship", "commit", approval_granted=False)
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.status, PolicyDecisionStatus.REQUIRES_APPROVAL)
        self.assertEqual(dec.required_approval_type, "COMMIT_APPROVAL")

        # With approval: allowed
        dec_ok = self.engine.evaluate_git("ship", "commit", approval_granted=True)
        self.assertTrue(dec_ok.allowed)
        self.assertEqual(dec_ok.status, PolicyDecisionStatus.ALLOWED)

    def test_command_credential_leak_denied(self):
        commands = [
            "cat .env",
            "grep API_KEY ~/.ssh/id_rsa",
            "cat credentials.json",
            "export GITHUB_TOKEN=ghp_secret",
        ]
        for cmd in commands:
            dec = self.engine.evaluate_command("ship", cmd)
            self.assertFalse(dec.allowed)
            self.assertEqual(dec.rule_violated, "forbidden.credentials")

    def test_command_force_push_denied(self):
        dec = self.engine.evaluate_command("ship", "git push origin main --force")
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.rule_violated, "forbidden.force_push")

    def test_command_production_deploy_denied(self):
        dec = self.engine.evaluate_command("ship", "kubectl apply -f app.yaml --context=prod")
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.rule_violated, "forbidden.production")

    def test_command_commit_requires_approval(self):
        dec = self.engine.evaluate_command("ship", "git commit -m 'feat: ship'", approval_granted=False)
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.status, PolicyDecisionStatus.REQUIRES_APPROVAL)

        dec_ok = self.engine.evaluate_command("ship", "git commit -m 'feat: ship'", approval_granted=True)
        self.assertTrue(dec_ok.allowed)

    def test_tool_call_forbidden_file_denied(self):
        dec = self.engine.evaluate_tool_call("ship", "write_to_file", {"TargetFile": ".env"})
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.rule_violated, "forbidden.credentials")


class TestCapabilityGuardIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.guard = CapabilityGuard(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_guard_intercepts_forbidden_credential_read(self):
        ctx = ActionContext(
            agent_id="test-agent",
            operation="SECRET_READ",
            target="AWS_SECRET_KEY",
            skill="ship",
        )
        with self.assertRaises(CapabilityDenied) as cm:
            self.guard.require(ctx)
        self.assertEqual(cm.exception.decision.violation_code, "forbidden.credentials")

    def test_guard_intercepts_forbidden_file_path(self):
        ctx = ActionContext(
            agent_id="test-agent",
            operation="FILE_READ",
            target=".env",
            skill="ship",
        )
        with self.assertRaises(CapabilityDenied) as cm:
            self.guard.require(ctx)
        self.assertEqual(cm.exception.decision.violation_code, "forbidden.credentials")

    def test_guard_intercepts_unapproved_commit(self):
        ctx = ActionContext(
            agent_id="test-agent",
            operation="COMMAND",
            target="git commit -m 'auto-commit'",
            skill="ship",
            approval_granted=False,
        )
        with self.assertRaises(CapabilityDenied) as cm:
            self.guard.require(ctx)
        self.assertEqual(cm.exception.decision.violation_code, "requires_approval.commit")


if __name__ == "__main__":
    unittest.main()
