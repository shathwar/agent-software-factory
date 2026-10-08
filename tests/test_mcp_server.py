"""Tests for Ship stdio Model Context Protocol (MCP) server."""

import io
import os
from unittest.mock import patch
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ship.mcp.schemas import TOOLS_MANIFEST
from ship.mcp.server import handle_request, run_stdio_server


class MCPServerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"AGENTFLOW_MCP_ALLOW_MUTATIONS": "1"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.stdout_buf = io.StringIO()
        self.stderr_buf = io.StringIO()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = self.stdout_buf
        sys.stderr = self.stderr_buf

    def tearDown(self):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

    def _get_responses(self):
        output = self.stdout_buf.getvalue().strip()
        if not output:
            return []
        lines = [line.strip() for line in output.split("\n") if line.strip()]
        return [json.loads(line) for line in lines]

    def test_tools_manifest_has_all_ship_tools(self):
        """TOOLS_MANIFEST contains all registered ship_* tools with valid schemas."""
        self.assertEqual(len(TOOLS_MANIFEST), 20)
        tool_names = {t["name"] for t in TOOLS_MANIFEST}
        expected_tools = {
            "ship_steps_begin", "ship_steps_record", "ship_steps_report",
            "ship_next_turn",
            "ship_status",
            "ship_evaluate",
            "ship_record_turn",
            "ship_checkpoint",
            "ship_rollback",
            "ship_approve_design",
            "ship_record_tests",
            "ship_record_review",
            "ship_archive",
            "ship_trailers",
            "ship_doctor",
            "ship_verify",
            "ship_tdd_verify",
            "ship_simplify_scan",
            "ship_spike_run",
            "ship_review_validate",
        }
        self.assertEqual(tool_names, expected_tools)
        for tool in TOOLS_MANIFEST:
            self.assertTrue(tool["name"].startswith("ship_"))
            self.assertIn("description", tool)
            self.assertIn("inputSchema", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_initialize_request(self):
        """Server responds to initialize with protocolVersion and serverInfo."""
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        handle_request(req)
        resps = self._get_responses()
        self.assertEqual(len(resps), 1)
        resp = resps[0]
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(resp["result"]["serverInfo"]["name"], "ship")
        self.assertEqual(resp["result"]["serverInfo"]["version"], "1.0.0")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_ping_request(self):
        """Server responds to ping with empty result."""
        req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
        handle_request(req)
        resps = self._get_responses()
        self.assertEqual(len(resps), 1)
        self.assertEqual(resps[0]["result"], {})

    def test_tools_list_request(self):
        """Server responds to tools/list with all registered tools."""
        req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
        handle_request(req)
        resps = self._get_responses()
        self.assertEqual(len(resps), 1)
        tools = resps[0]["result"]["tools"]
        self.assertEqual(len(tools), 20)

    def test_unknown_method_returns_error(self):
        """Unknown methods return JSON-RPC -32601 Method not found."""
        req = {"jsonrpc": "2.0", "id": 4, "method": "unknown/method"}
        handle_request(req)
        resps = self._get_responses()
        self.assertEqual(len(resps), 1)
        self.assertEqual(resps[0]["error"]["code"], -32601)

    def test_tools_call_doctor(self):
        """Server executes ship_doctor via tools/call."""
        req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "ship_doctor", "arguments": {"path": "."}},
        }
        handle_request(req)
        resps = self._get_responses()
        self.assertEqual(len(resps), 1)
        result = resps[0]["result"]
        text = result["content"][0]["text"]
        self.assertIn('"version": "1.0.0"', text)
        self.assertIn('"ok": true', text)

    def test_tools_call_simplify_scan(self):
        """Server executes ship_simplify_scan via tools/call."""
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"AGENTFLOW_MCP_ROOT": tmp}):
            f = Path(tmp) / "module.py"
            f.write_text("# simplify: Quick stub. Ceiling: 10 calls. Upgrade: AsyncEngine.\n")
            req = {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "ship_simplify_scan",
                    "arguments": {"path": tmp, "format": "markdown"},
                },
            }
            handle_request(req)
            resps = self._get_responses()
            self.assertEqual(len(resps), 1)
            result = resps[0]["result"]
            self.assertFalse(result["isError"])
            text = result["content"][0]["text"]
            self.assertIn("Operational Ceiling", text)

    def test_tools_call_lifecycle_in_git_repo(self):
        """Server executes ship_next_turn and ship_status on a real repo."""
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"AGENTFLOW_MCP_ROOT": tmp}):
            root = Path(tmp).resolve()
            for args in [("init", "-b", "main"), ("config", "user.name", "Dev"),
                         ("config", "user.email", "dev@example.com"), ("config", "commit.gpgsign", "false")]:
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            (root / "README.md").write_text("# Test Repo\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)

            # Test ship_next_turn
            req_turn = {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "ship_next_turn", "arguments": {"path": str(root)}},
            }
            handle_request(req_turn)
            resps = self._get_responses()
            self.assertEqual(len(resps), 1)
            text = resps[0]["result"]["content"][0]["text"]
            self.assertIn("TURN CONTRACT: DESIGN", text)

            # Clear buffer and test ship_status
            self.stdout_buf.truncate(0)
            self.stdout_buf.seek(0)
            req_status = {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "ship_status", "arguments": {"path": str(root)}},
            }
            handle_request(req_status)
            resps = self._get_responses()
            self.assertEqual(len(resps), 1)
            status_data = json.loads(resps[0]["result"]["content"][0]["text"])
            self.assertEqual(status_data["status"], "BLOCKED")
            self.assertEqual(status_data["active_gate"], "design")

            # Test ship_checkpoint
            self.stdout_buf.truncate(0)
            self.stdout_buf.seek(0)
            req_chk = {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "ship_checkpoint", "arguments": {"path": str(root), "gate": "design", "change": "mcp-feat"}},
            }
            handle_request(req_chk)
            resps = self._get_responses()
            self.assertEqual(len(resps), 1)
            self.assertFalse(resps[0]["result"]["isError"])
            chk_data = json.loads(resps[0]["result"]["content"][0]["text"])
            self.assertIn("refs/ship/mcp-feat/design", chk_data["checkpoint_ref"])

            # Test ship_rollback
            self.stdout_buf.truncate(0)
            self.stdout_buf.seek(0)
            req_rb = {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "ship_rollback", "arguments": {"path": str(root), "gate": "design", "change": "mcp-feat", "force": True}},
            }
            handle_request(req_rb)
            resps = self._get_responses()
            self.assertEqual(len(resps), 1)
            self.assertFalse(resps[0]["result"]["isError"])
            rb_data = json.loads(resps[0]["result"]["content"][0]["text"])
            self.assertEqual(rb_data["status"], "success")

            # Test ship_trailers
            self.stdout_buf.truncate(0)
            self.stdout_buf.seek(0)
            req_tr = {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "ship_trailers", "arguments": {"path": str(root), "change": "mcp-feat"}},
            }
            handle_request(req_tr)
            resps = self._get_responses()
            self.assertEqual(len(resps), 1)
            self.assertFalse(resps[0]["result"]["isError"])
            tr_data = json.loads(resps[0]["result"]["content"][0]["text"])
            self.assertIn("Ship-Change: mcp-feat", tr_data["formatted"])

            # Test ship_trailers omitting change argument (auto-resolving active change)
            self.stdout_buf.truncate(0)
            self.stdout_buf.seek(0)
            req_tr_auto = {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {"name": "ship_trailers", "arguments": {"path": str(root)}},
            }
            handle_request(req_tr_auto)
            resps = self._get_responses()
            self.assertEqual(len(resps), 1)
            self.assertFalse(resps[0]["result"]["isError"])
            tr_auto_data = json.loads(resps[0]["result"]["content"][0]["text"])
            self.assertIn("Ship-Change: mcp-feat", tr_auto_data["formatted"])
            self.assertEqual(tr_auto_data["change_id"], "mcp-feat")

            # Test ship_record_review
            self.stdout_buf.truncate(0)
            self.stdout_buf.seek(0)
            req_rev = {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "ship_record_review",
                    "arguments": {
                        "path": str(root),
                        "change": "mcp-feat",
                        "report_data": {
                            "reviewer": "judge",
                            "status": "complete",
                            "verdict": "PASS",
                            "findings": [],
                            "coverage": ["all"],
                            "questions": [],
                            "routing_notes": []
                        }
                    }
                },
            }
            handle_request(req_rev)
            resps = self._get_responses()
            self.assertEqual(len(resps), 1)
            self.assertFalse(resps[0]["result"]["isError"])
            rev_data = json.loads(resps[0]["result"]["content"][0]["text"])
            self.assertEqual(rev_data["status"], "RECORDED")

            # Set up change package for mcp-feat to test ship_archive without change argument
            change_dir = root / "openspec/changes/mcp-feat"
            (change_dir / "specs").mkdir(parents=True, exist_ok=True)
            (change_dir / "specs/feature.md").write_text("# Feature Spec\n")
            (change_dir / "proposal.md").write_text("# Proposal\n")
            (change_dir / "tasks.md").write_text("- [x] Done\n")

            self.stdout_buf.truncate(0)
            self.stdout_buf.seek(0)
            req_arch = {
                "jsonrpc": "2.0",
                "id": 14,
                "method": "tools/call",
                "params": {"name": "ship_archive", "arguments": {"path": str(root), "force": True}},
            }
            handle_request(req_arch)
            resps = self._get_responses()
            self.assertEqual(len(resps), 1)
            self.assertFalse(resps[0]["result"]["isError"])
            arch_data = json.loads(resps[0]["result"]["content"][0]["text"])
            self.assertEqual(arch_data["status"], "ARCHIVED")
            self.assertEqual(arch_data["change_id"], "mcp-feat")

    def test_stdio_server_loop(self):
        """Full stdio server loop handles lines and parse error gracefully."""
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 10, "method": "ping"}),
            "not a json line",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        ]
        stdin_mock = io.StringIO("\n".join(lines) + "\n")
        old_stdin = sys.stdin
        try:
            sys.stdin = stdin_mock
            ret = run_stdio_server()
        finally:
            sys.stdin = old_stdin

        self.assertEqual(ret, 0)
        resps = self._get_responses()
        self.assertEqual(len(resps), 2)
        self.assertEqual(resps[0]["id"], 10)
        self.assertEqual(resps[0]["result"], {})
        # Parse error for second line
        self.assertEqual(resps[1]["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
