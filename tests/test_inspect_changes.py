"""Behavior checks against isolated Git repositories; no user Git config/hooks."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(os.environ.get("INSPECTOR_SCRIPT", str(
    Path(__file__).resolve().parents[1]
    / "skills/review/scripts/inspect_changes.sh"
)))


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Inspector test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.write("worker.py", "value = 1\n")
        self.commit()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, env=self.env,
                              text=True, capture_output=True, check=True).stdout

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-m", "fixture")

    def inspect(self, *args, success=True):
        result = subprocess.run(["bash", str(SCRIPT), *args], cwd=self.root,
                                env=self.env, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertTrue(result.stderr.strip())
            self.assertNotIn("END OF CHANGE INSPECTOR REPORT", result.stdout)
        return result.stdout

    def test_invalid_ref_fails_visibly(self):
        self.inspect("--no-diff", "does-not-exist", success=False)

    def test_invalid_range_fails_visibly(self):
        self.inspect("main...does-not-exist", success=False)

    def test_unknown_option_is_rejected(self):
        self.inspect("--wat", success=False)

    def test_multiple_targets_are_rejected(self):
        self.inspect("HEAD", "main", success=False)

    def test_root_commit_is_reviewed(self):
        self.assertIn("+value = 1", self.inspect())

    def test_remote_only_base(self):
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-b", "feature")
        self.git("branch", "-D", "main")
        self.write("new.py", "feature = True\n")
        self.commit()
        self.assertIn("+feature = True", self.inspect())

    def test_nested_untracked_files_are_read_without_staging(self):
        self.write("new/runner.py", "asyncio.create_task(work())\n")
        before = self.git("status", "--porcelain=v1", "-uall")
        output = self.inspect()
        self.assertIn("  + new/runner.py", output)
        self.assertIn("THREAD / ASYNC LIFECYCLE REVIEW", output)
        self.assertIn("+asyncio.create_task(work())", output)
        self.assertEqual(before, self.git("status", "--porcelain=v1", "-uall"))

    def test_renames_include_both_paths_in_analysis(self):
        (self.root / "api").mkdir()
        self.git("mv", "worker.py", "api/routes.py")
        self.write("consumer.py", "import worker\n")
        self.git("add", "consumer.py")
        output = self.inspect("--no-diff")
        self.assertIn("CONTRACT REVIEW", output)
        self.assertIn("[MISSING TEST] api/routes.py", output)
        self.assertIn("Callers of worker:", output)

    def test_committed_rename_with_modification(self):
        self.write("worker.py", "value = 1\n" * 30)
        self.commit()
        self.git("mv", "worker.py", "renamed.py")
        self.write("renamed.py", "value = 1\n" * 30 + "extra = 2\n")
        self.commit()
        output = self.inspect("HEAD~1..HEAD")
        self.assertIn("[MISSING TEST] renamed.py", output)
        self.assertIn("+extra = 2", output)

    def test_deleted_source_keeps_callers_and_tests(self):
        self.write("consumer.py", "import worker\n")
        self.write("test_worker.py", "import worker\n")
        self.commit()
        (self.root / "worker.py").unlink()
        output = self.inspect("--no-diff")
        self.assertIn("Callers of worker:", output)
        self.assertIn("consumer.py", output)
        self.assertIn("test_worker.py (exists", output)

    def test_large_diff_keeps_async_trigger(self):
        self.write("worker.py", "asyncio.create_task(work())\n" + "value = 2\n" * 100000)
        self.assertIn("THREAD / ASYNC LIFECYCLE REVIEW", self.inspect("--no-diff"))
        self.commit()
        self.assertIn("THREAD / ASYNC LIFECYCLE REVIEW",
                      self.inspect("--no-diff", "HEAD~1..HEAD"))

    def test_staged_and_unstaged_edits(self):
        self.write("worker.py", "staged = True\n")
        self.git("add", "worker.py")
        self.write("worker.py", "staged = True\nunstaged = True\n")
        output = self.inspect()
        self.assertIn("+staged = True", output)
        self.assertIn("+unstaged = True", output)

    def test_unusual_filenames(self):
        for name in ("space name.py", "tab\tname.py", "café.py", "-leading.py"):
            with self.subTest(name=name):
                self.write(name, "asyncio.create_task(work())\n")
                output = self.inspect("--no-diff")
                self.assertIn("  + " + name, output)
                self.assertIn("THREAD / ASYNC LIFECYCLE REVIEW", output)
                self.commit()
                self.write(name, "asyncio.create_task(other())\n")
                self.assertIn("  * " + name, self.inspect("--no-diff"))
                self.commit()

    def test_no_diff_omits_patch(self):
        self.write("new.py", "unique_content = 42\n")
        self.assertNotIn("+unique_content", self.inspect("--no-diff"))

    def test_explicit_empty_diff_stays_empty(self):
        output = self.inspect("--no-diff", "HEAD..HEAD")
        self.assertIn("  (No production source files changed)", output)
        self.assertNotIn("  + worker.py", output)

    def test_prod_files_with_test_or_spec_substrings_are_not_skipped(self):
        self.write("src/inspector.py", "def inspect(): pass\n")
        self.write("src/specification.py", "def specify(): pass\n")
        output = self.inspect("--no-diff")
        self.assertIn("[MISSING TEST] src/inspector.py", output)
        self.assertIn("[MISSING TEST] src/specification.py", output)
        self.assertNotIn("(No production source files changed)", output)

    def test_modern_triggers(self):
        self.write("uv.lock", "version = 1\n")
        self.write("drizzle/schema.ts", "export const users = {};\n")
        self.write("finance.py", "total = Decimal('100.50')\n")
        output = self.inspect("--no-diff")
        self.assertIn("DEPENDENCY REVIEW", output)
        self.assertIn("MIGRATION REVIEW", output)
        self.assertIn("FINANCIAL / PRECISION REVIEW", output)

    def test_modern_lockfiles_and_infra_triggers(self):
        self.write("yarn.lock", "# yarn lockfile v1\n")
        self.write("Containerfile", "FROM alpine:latest\n")
        self.write("sync_helper.py", "latch = CountDownLatch(1)\n")
        self.write("billing.py", "subtotal = 500\n")
        output = self.inspect("--no-diff")
        self.assertIn("DEPENDENCY REVIEW", output)
        self.assertIn("CONFIG REVIEW", output)
        self.assertIn("CONCURRENCY REVIEW", output)
        self.assertIn("FINANCIAL / PRECISION REVIEW", output)

    def test_untracked_spec_discovery(self):
        self.write(".agentflow/feature_spec.md", "# Feature Spec\n")
        output = self.inspect("--no-diff")
        self.assertIn("Available Spec / PRD Documents:", output)
        self.assertIn(".agentflow/feature_spec.md", output)

    def test_openspec_and_adr_discovery(self):
        self.write("openspec/changes/order-stream/specs/exit.md", "# Requirement: Exit\n")
        self.write("docs/adr/ADR-001-trail.md", "# ADR 001\n")
        output = self.inspect("--no-diff")
        self.assertIn("Available Spec / PRD Documents:", output)
        self.assertIn("openspec/changes/order-stream/specs/exit.md", output)
        self.assertIn("docs/adr/ADR-001-trail.md", output)

    def test_untracked_test_matching_prefix_and_case(self):
        self.write("service.py", "class Service: pass\n")
        self.write("tests/test_service.py", "def test_service(): pass\n")
        output = self.inspect("--no-diff")
        self.assertIn("[UPDATED TEST] service.py", output)
        self.assertIn("-> tests/test_service.py", output)
        self.assertNotIn("[MISSING TEST] service.py", output)

    def test_caller_discovery_with_compound_caller_name(self):
        self.write("background_worker.py", "import worker\n")
        self.write("custom_worker.py", "import worker\n")
        self.commit()
        self.write("worker.py", "value = 2\n")
        output = self.inspect("--no-diff")
        self.assertIn("Callers of worker:", output)
        self.assertIn("background_worker.py", output)
        self.assertIn("custom_worker.py", output)

    def test_language_agnostic_test_file_filtering(self):
        self.write("test_client.ts", "describe('client', () => {});\n")
        self.write("test_main.go", "package main\n")
        output = self.inspect("--no-diff")
        self.assertNotIn("[MISSING TEST] test_client.ts", output)
        self.assertNotIn("[MISSING TEST] test_main.go", output)

    def test_develop_and_trunk_base_branches(self):
        self.git("checkout", "-b", "develop")
        self.git("checkout", "-b", "feature")
        self.git("branch", "-D", "main")
        self.write("feature.py", "done = True\n")
        self.commit()
        output = self.inspect("--no-diff")
        self.assertIn("Base:   refs/heads/develop", output)

    def test_graphql_contract_trigger(self):
        self.write("schema.graphql", "type Query { me: String }\n")
        output = self.inspect("--no-diff")
        self.assertIn("CONTRACT REVIEW", output)

    def test_expanded_linter_configs(self):
        self.write("mypy.ini", "[mypy]\nignore_missing_imports = True\n")
        output = self.inspect("--no-diff")
        self.assertIn("mypy.ini", output)

    def test_base_option_inspects_base_plus_working_tree(self):
        """Reproduction for Issue 3: inspect_changes.sh --base <branch> must succeed and inspect uncommitted edits."""
        self.git("checkout", "-b", "feature")
        self.write("committed_on_feature.py", "step = 1\n")
        self.commit()
        # Uncommitted staged and unstaged edits
        self.write("worker.py", "value = 99\n")
        # Untracked file
        self.write("untracked_feature.py", "untracked = True\n")

        output = self.inspect("--base", "main")
        self.assertIn("Scope:  refs/heads/main (BASE_WORKING_TREE)", output)
        self.assertIn("committed_on_feature.py", output)
        self.assertIn("worker.py", output)
        self.assertIn("untracked_feature.py", output)
        self.assertIn("+value = 99", output)
        self.assertIn("+untracked = True", output)

    def test_base_option_equals_syntax_and_validation(self):
        self.git("checkout", "-b", "feature2")
        self.write("worker.py", "value = 100\n")
        output = self.inspect("--base=main")
        self.assertIn("BASE_WORKING_TREE", output)
        self.assertIn("+value = 100", output)

        # Missing arg
        self.inspect("--base", success=False)
        # Non-existent base ref
        self.inspect("--base", "nonexistent-branch", success=False)
        # Both base and explicit target
        self.inspect("--base", "main", "HEAD~1..HEAD", success=False)

    def test_dotfiles_and_repo_metadata_are_not_flagged_as_missing_tests(self):
        self.write(".gitignore", "*.pyc\nnode_modules/\n")
        self.write("LICENSE", "MIT License\nCopyright 2026\n")
        self.write("Cargo.lock", "# lockfile v3\n")
        output = self.inspect("--no-diff")
        self.assertNotIn("[MISSING TEST] .gitignore", output)
        self.assertNotIn("[MISSING TEST] LICENSE", output)
        self.assertNotIn("[MISSING TEST] Cargo.lock", output)
        self.assertNotIn("Callers of :", output)

    def test_build_and_container_files_are_not_flagged_as_missing_tests(self):
        self.write("Dockerfile", "FROM python:3.11-slim\nCMD [\"python3\"]\n")
        self.write("Makefile", "all:\n\techo build\n")
        self.write("Containerfile", "FROM alpine:latest\n")
        output = self.inspect("--no-diff")
        self.assertNotIn("[MISSING TEST] Dockerfile", output)
        self.assertNotIn("[MISSING TEST] Makefile", output)
        self.assertNotIn("[MISSING TEST] Containerfile", output)

    def test_shell_script_and_c_matching_tests_are_discovered(self):
        self.write("scripts/deploy.sh", "#!/usr/bin/env bash\necho deploy\n")
        self.write("tests/test_deploy.py", "def test_deploy(): pass\n")
        self.write("src/core.c", "int run() { return 0; }\n")
        self.write("tests/core_test.cpp", "TEST(Core, Run) {}\n")
        self.commit()

        # Modify deploy.sh and core.c
        self.write("scripts/deploy.sh", "#!/usr/bin/env bash\necho deploy v2\n")
        self.write("src/core.c", "int run() { return 1; }\n")
        output = self.inspect("--no-diff")

        self.assertIn("[UNTOUCHED]    scripts/deploy.sh", output)
        self.assertIn("-> tests/test_deploy.py", output)
        self.assertNotIn("[MISSING TEST] scripts/deploy.sh", output)

        self.assertIn("[UNTOUCHED]    src/core.c", output)
        self.assertIn("-> tests/core_test.cpp", output)
        self.assertNotIn("[MISSING TEST] src/core.c", output)

    def test_max_diff_lines_truncation_and_scope(self):
        # Generate a large diff
        large_content = "\n".join(f"line_{i} = {i}" for i in range(50)) + "\n"
        self.write("worker.py", large_content)
        output = self.inspect("--max-diff-lines", "15", "--full-diff")
        self.assertIn("[!] TRUNCATED: Diff output exceeded 15 lines", output)

        # Test scope option execution
        scoped_output = self.inspect("--scope", "src", "--no-diff")
        self.assertIn("END OF CHANGE INSPECTOR REPORT", scoped_output)


if __name__ == "__main__":
    unittest.main()

