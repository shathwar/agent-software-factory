"""Subprocess boundary to the canonical TypeScript specialist tools (Bun 1.3+)."""
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

TOOLS = frozenset({"debug", "design", "evals", "sample_traces", "simplify", "skill", "tdd", "review", "spike", "ux"})


def js_executable():
    executable = os.environ.get("SHIP_NODE") or shutil.which("node")
    if not executable:
        raise RuntimeError("TypeScript runtime requires Node.js 22+. Install node and add it to PATH.")
    return executable


def call_tool(action, args=None, *, timeout=60):
    """Exchange one JSON request; never evaluate caller-supplied source or shell text here."""
    script = Path(__file__).resolve().parent / "tools" / "rpc.ts"
    result = subprocess.run(
        [js_executable(), str(script)],
        input=json.dumps({"action": action, "args": args or {}}, default=str, allow_nan=False),
        capture_output=True, text=True, timeout=timeout,
    )
    try:
        response = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"Specialist runtime returned invalid JSON: {result.stderr.strip()}") from exc
    if result.returncode or "error" in response:
        raise RuntimeError(response.get("error") or result.stderr.strip() or "Specialist runtime failed")
    return response["result"]


def run_tool_cli(tool, argv):
    if tool not in TOOLS:
        raise ValueError(f"Unknown specialist tool: {tool}")
    try:
        result = subprocess.run([js_executable(), str(Path(__file__).resolve().parent / "tools" / f"{tool}.ts"), *argv],
                                input=sys.stdin.read() if "-" in argv else None, capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


@lru_cache(maxsize=4096)
def classify_file(path):
    return call_tool("classify", {"path": str(path)})
