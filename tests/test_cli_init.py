"""
Unit tests for AgentFlow initialization scaffolding (agentflow init / ship init).
Tests auto-detection of test commands, .agentflow.json generation, .gitignore integration,
and CLI dispatch.
"""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ship.lifecycle.operations import detect_test_command, init_agentflow
from ship.cli import main as ship_cli_main


class TestCliInit(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name).resolve()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_detect_test_command_python(self):
        # Python repo with tests dir
        (self.root / "tests").mkdir()
        cmd = detect_test_command(self.root)
        self.assertEqual(cmd, "pytest")

    def test_detect_test_command_empty(self):
        cmd = detect_test_command(self.root)
        self.assertEqual(cmd, "")

    def test_detect_test_command_cargo(self):
        (self.root / "Cargo.toml").write_text("[package]\nname = 'foo'\n", encoding="utf-8")
        cmd = detect_test_command(self.root)
        self.assertEqual(cmd, "cargo test")

    def test_detect_test_command_go(self):
        (self.root / "go.mod").write_text("module example.com/foo\n", encoding="utf-8")
        cmd = detect_test_command(self.root)
        self.assertEqual(cmd, "go test ./...")

    def test_detect_test_command_node_npm(self):
        pkg = {"name": "foo", "scripts": {"test": "jest"}}
        (self.root / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        cmd = detect_test_command(self.root)
        self.assertEqual(cmd, "npm test")

    def test_detect_test_command_node_pnpm(self):
        pkg = {"name": "foo", "scripts": {"test": "vitest"}}
        (self.root / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        (self.root / "pnpm-lock.yaml").write_text("lockfileVersion: 5.4\n", encoding="utf-8")
        cmd = detect_test_command(self.root)
        self.assertEqual(cmd, "pnpm test")

    def test_detect_test_command_node_yarn(self):
        pkg = {"name": "foo", "scripts": {"test": "mocha"}}
        (self.root / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        (self.root / "yarn.lock").write_text("# yarn lock\n", encoding="utf-8")
        cmd = detect_test_command(self.root)
        self.assertEqual(cmd, "yarn test")

    def test_init_agentflow_creates_manifest_and_gitignore(self):
        res = init_agentflow(self.root, profile="standard", scope="src")
        self.assertTrue(res["ok"])

        config_path = self.root / ".agentflow.json"
        self.assertTrue(config_path.exists())

        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["workflow"]["profile"], "standard")
        self.assertEqual(config["project"]["scope"], "src")
        self.assertIn("agentflow.schema.json", config.get("$schema", ""))
        self.assertEqual(config["gates"]["implementation"]["test"], "")

        gitignore_path = self.root / ".gitignore"
        self.assertTrue(gitignore_path.exists())
        self.assertIn(".agentflow/", gitignore_path.read_text(encoding="utf-8"))

    def test_init_agentflow_refuses_overwrite_without_force(self):
        self.assertTrue(init_agentflow(self.root)["ok"])
        # Second call without force must raise FileExistsError
        with self.assertRaises(FileExistsError):
            init_agentflow(self.root, force=False)
        # With force must succeed
        res = init_agentflow(self.root, force=True, profile="small-fix")
        self.assertTrue(res["ok"])
        config = json.loads((self.root / ".agentflow.json").read_text(encoding="utf-8"))
        self.assertEqual(config["workflow"]["profile"], "small-fix")

    def test_init_cli_dispatch(self):
        ret = ship_cli_main(["init", "--profile", "high-risk", "--path", str(self.root), "--test-cmd", "make test"])
        self.assertEqual(ret, 0)

        config_path = self.root / ".agentflow.json"
        self.assertTrue(config_path.exists())
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["workflow"]["profile"], "high-risk")
        self.assertEqual(config["gates"]["implementation"]["test"], "make test")

    def test_init_cli_already_exists_fails_without_force(self):
        (self.root / ".agentflow.json").write_text("{}", encoding="utf-8")
        ret = ship_cli_main(["init", "--path", str(self.root)])
        self.assertEqual(ret, 1)

        # But passes with --force
        ret = ship_cli_main(["init", "--path", str(self.root), "--force"])
        self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
