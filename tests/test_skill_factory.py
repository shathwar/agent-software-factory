"""tests/test_skill_factory.py – Unit tests for Skill Factory, Native Claude Skills, Matrix, and Cost."""

import json
from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.skill_factory import (
    CompatibilityLevel,
    KNOWN_HOSTS,
    KNOWN_MODELS,
    RunUsageMetadata,
    SkillCompatibility,
    SkillFactory,
    SkillRequirements,
    compute_cost_usd,
    evaluate_compatibility,
    generate_compatibility_matrix,
    get_model_pricing,
    render_compatibility_markdown,
)
from ship.cli import run_skill_cli, run_cost_cli
from ship.mcp.tools import dispatch_tool


class TestSkillRequirements(unittest.TestCase):
    def test_requirements_defaults_and_normalization(self):
        req = SkillRequirements.from_dict({
            "name": "My New Skill!",
            "role": "Security Lead",
            "description": "Performs security audits",
        })
        self.assertEqual(req.name, "my-new-skill-")
        self.assertEqual(req.role, "Security Lead")
        self.assertEqual(req.version, "1.0.0")
        self.assertEqual(req.domain, "engineering")
        self.assertIsInstance(req.compatibility, SkillCompatibility)


class TestNativeClaudeSkillsOutput(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.factory = SkillFactory(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_generate_skill_md_structure(self):
        req = SkillRequirements(
            name="perf-audit",
            role="Principal Performance Engineer",
            description="Stress-test API latency and throughput ceilings.",
            hard_constraints=["Zero mock benchmarks in production.", "Always record p99 percentiles."],
            turn_contract_items=["1. Profile baseline latency.", "2. Validate latency invariants."],
        )
        content = self.factory.generate_skill_md(req)
        self.assertTrue(content.startswith("---"))
        self.assertIn("name: perf-audit", content)
        self.assertIn("description: Stress-test API latency and throughput ceilings.", content)
        self.assertIn("<hard_constraints>", content)
        self.assertIn("- Zero mock benchmarks in production.", content)
        self.assertIn("- Always record p99 percentiles.", content)
        self.assertIn("<turn_contract>", content)
        self.assertIn("1. Profile baseline latency.", content)
        self.assertIn("scripts/validate_perf_audit.py", content)

    def test_generate_skill_md_with_claude_frontmatter(self):
        req = SkillRequirements(
            name="claude-custom",
            role="Claude Specialist",
            description="Specialized Claude skill with frontmatter constraints.",
            model="claude-3-7-sonnet",
            effort="high",
            allowed_tools=["Read", "Edit", "Bash"],
        )
        content = self.factory.generate_skill_md(req)
        self.assertIn("model: claude-3-7-sonnet", content)
        self.assertIn("effort: high", content)
        self.assertIn("allowed-tools:\n  - Read\n  - Edit\n  - Bash", content)

    def test_build_native_skill_directory_layout(self):
        req = SkillRequirements(
            name="api-linter",
            role="API Standards Architect",
            description="Lint and enforce OpenAPI 3.1 contracts.",
            version="1.2.0",
        )
        out_dir = self.root / "skills" / "api-linter"
        artifact = self.factory.build_skill(req, output_dir=out_dir, package_archive=True)

        self.assertEqual(artifact.name, "api-linter")
        self.assertEqual(artifact.version, "1.2.0")
        self.assertTrue(artifact.skill_md.exists())
        self.assertTrue(artifact.version_file.exists())
        self.assertEqual(artifact.version_file.read_text().strip(), "1.2.0")
        self.assertTrue((out_dir / "CHANGELOG.md").exists())

        # Check scripts/
        self.assertTrue(len(artifact.scripts) >= 1)
        validator_script = artifact.scripts[0]
        self.assertTrue(validator_script.exists())
        self.assertEqual(validator_script.name, "validate_api_linter.py")

        # Check references/
        self.assertTrue(len(artifact.references) >= 1)
        self.assertTrue(artifact.references[0].exists())

        # Check assets/
        self.assertTrue(len(artifact.assets) >= 1)
        self.assertTrue(artifact.assets[0].exists())

        # Check evals/
        self.assertTrue(len(artifact.evals) >= 1)
        evals_json = json.loads(artifact.evals[0].read_text())
        self.assertTrue(len(evals_json) >= 2)

        # Check packaging archive
        self.assertIsNotNone(artifact.archive_file)
        self.assertTrue(artifact.archive_file.exists())

        # Validate with structure validator
        val_res = self.factory.validate_skill_structure(out_dir)
        self.assertTrue(val_res["valid"])
        self.assertEqual(len(val_res["errors"]), 0)


class TestCompatibilityMatrix(unittest.TestCase):
    def test_known_hosts_and_models(self):
        self.assertIn("claude_code", KNOWN_HOSTS)
        self.assertIn("antigravity", KNOWN_HOSTS)
        self.assertIn("claude-3-7-sonnet", KNOWN_MODELS)
        self.assertIn("gpt-4o", KNOWN_MODELS)

    def test_evaluate_compatibility_levels(self):
        compat = SkillCompatibility(
            required_host_features=["terminal_execution", "filesystem_mutations", "subagents"],
            min_reasoning_score=8,
        )

        # Claude Code has terminal, filesystem, and subagents -> FULL
        res_claude = evaluate_compatibility(compat, "ship", "claude_code", "claude-3-7-sonnet")
        self.assertEqual(res_claude.level, CompatibilityLevel.FULL)

        # Cursor lacks subagents -> PARTIAL with sequential fallback
        res_cursor = evaluate_compatibility(compat, "ship", "cursor", "claude-3-7-sonnet")
        self.assertEqual(res_cursor.level, CompatibilityLevel.PARTIAL)
        self.assertTrue(any("subagent" in r.lower() for r in res_cursor.reasons))

        # Model with low reasoning score -> DEGRADED
        res_haiku = evaluate_compatibility(compat, "ship", "claude_code", "claude-3-5-haiku")
        self.assertEqual(res_haiku.level, CompatibilityLevel.DEGRADED)

    def test_generate_and_render_matrix(self):
        compat = SkillCompatibility()
        matrix = generate_compatibility_matrix(compat, "test-skill", hosts=["claude_code", "cursor"], models=["claude-3-7-sonnet", "gpt-4o"])
        self.assertIn("matrix", matrix)
        self.assertEqual(matrix["skill"], "test-skill")
        md = render_compatibility_markdown(matrix)
        self.assertIn("Compatibility Matrix", md)
        self.assertIn("Claude Code", md)


class TestCostAndUsageMetadata(unittest.TestCase):
    def test_pricing_lookup(self):
        p_sonnet = get_model_pricing("claude-3-7-sonnet")
        self.assertEqual(p_sonnet.input_per_m, 3.00)
        self.assertEqual(p_sonnet.output_per_m, 15.00)

        p_gpt = get_model_pricing("gpt-4o")
        self.assertEqual(p_gpt.input_per_m, 2.50)
        self.assertEqual(p_gpt.output_per_m, 10.00)

    def test_compute_cost_usd_calculation(self):
        # 1,000,000 in ($3) + 1,000,000 out ($15) on Sonnet = $18
        cost = compute_cost_usd("claude-3-7-sonnet", input_tokens=1_000_000, output_tokens=1_000_000)
        self.assertEqual(cost, 18.0)

        # 10,000 in ($0.03) + 2,000 out ($0.03) = $0.06
        cost_small = compute_cost_usd("claude-3-7-sonnet", input_tokens=10_000, output_tokens=2_000)
        self.assertEqual(cost_small, 0.06)

        # Cached tokens discount
        # 100,000 input tokens of which 80,000 are cached ($0.30/M) + 20,000 uncached ($3.00/M)
        cost_cached = compute_cost_usd("claude-3-7-sonnet", input_tokens=100_000, output_tokens=0, cached_tokens=80_000)
        expected = (20_000 / 1e6 * 3.00) + (80_000 / 1e6 * 0.30)
        self.assertAlmostEqual(cost_cached, expected, places=4)

    def test_run_usage_metadata_dataclass(self):
        meta = RunUsageMetadata(
            model="claude-3-7-sonnet",
            input_tokens=5000,
            output_tokens=1000,
            duration_ms=450.5,
            tool_calls_count=3,
        )
        self.assertEqual(meta.total_tokens, 6000)
        self.assertGreater(meta.estimated_cost_usd, 0.0)
        d = meta.to_dict()
        self.assertEqual(d["model"], "claude-3-7-sonnet")
        self.assertEqual(d["total_tokens"], 6000)


class TestCliIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cli_skill_create_and_validate(self):
        out_dir = self.root / "skills" / "cli-skill"
        exit_code = run_skill_cli(["create", "cli-skill", "--role", "Tester", "--output-dir", str(out_dir)])
        self.assertEqual(exit_code, 0)
        self.assertTrue((out_dir / "SKILL.md").exists())

        exit_code_val = run_skill_cli(["validate", str(out_dir), "--strict"])
        self.assertEqual(exit_code_val, 0)

    def test_cli_cost_calculation(self):
        exit_code = run_cost_cli(["--model", "gpt-4o", "--input", "10000", "--output", "2000", "--json"])
        self.assertEqual(exit_code, 0)


class TestMcpToolIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_mcp_skill_tools(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"AGENTFLOW_MCP_ROOT": str(self.root), "AGENTFLOW_MCP_ALLOW_MUTATIONS": "1"}):
            # Create skill
            res_create = dispatch_tool("ship_skill_create", {
                "name": "mcp-test-skill",
                "role": "MCP Architect",
            })
            self.assertEqual(res_create["name"], "mcp-test-skill")
            self.assertEqual(res_create["version"], "1.0.0")

            # Validate skill
            res_val = dispatch_tool("ship_skill_validate", {
                "skill_path": str(self.root / "skills" / "mcp-test-skill"),
            })
            self.assertTrue(res_val["valid"])

            # Matrix
            res_matrix = dispatch_tool("ship_skill_matrix", {
                "skill": "mcp-test-skill",
            })
            self.assertIn("matrix", res_matrix)

            # Cost
            res_cost = dispatch_tool("ship_cost", {
                "model": "claude-3-7-sonnet",
                "input_tokens": 10000,
                "output_tokens": 2000,
            })
            self.assertEqual(res_cost["estimated_cost_usd"], 0.06)


if __name__ == "__main__":
    unittest.main()
