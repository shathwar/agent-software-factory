"""Live model tool loop with host-owned traces and isolated fixture execution.

Only the host writes evidence. Model text and supplied test results are never
accepted as execution evidence. Use Docker for live runs; local execution exists
for deterministic harness tests and explicitly trusted development fixtures.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from ship.lifecycle.observability import ExecutionObserver

TOOLS = [
    {"name": "read_file", "description": "Read a fixture file by relative path.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "read_skill", "description": "Read a reference from the selected skill directory by relative path.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
    {"name": "write_file", "description": "Write a complete UTF-8 fixture file. Every edit is recorded.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}},
    {"name": "run_tests", "description": "Run Python unittest discovery in the fixture; returns actual process output.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "run_command", "description": "Inspect Git state using a host-defined command.",
     "input_schema": {"type": "object", "properties": {"command": {"enum": ["git_status", "git_diff"]}}, "required": ["command"], "additionalProperties": False}},
]

ORACLE = '''import importlib.util, unittest
spec = importlib.util.spec_from_file_location("candidate", "/workspace/calc.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class Acceptance(unittest.TestCase):
    def test_empty(self): self.assertEqual(module.average([]), 0)
    def test_positive(self): self.assertEqual(module.average([2, 4, 9]), 5)
    def test_negative(self): self.assertEqual(module.average([-4, 0]), -2)
    def test_fraction(self): self.assertEqual(module.average([1, 2]), 1.5)
unittest.main()
'''

CASES = {
    "tdd-average": {"skill": "tdd", "source": "def average(xs):\n    raise NotImplementedError\n",
                    "prompt": "Implement average(xs): arithmetic mean, returning 0 for empty input. Follow the TDD skill. Add meaningful unittest tests before implementing. Preserve notes.txt."},
    "debug-average": {"skill": "debug", "source": "def average(xs):\n    return sum(xs) / len(xs)\n",
                      "prompt": "Fix average([]) raising ZeroDivisionError; it must return 0. Follow the debug skill: add and run a reproduction test before fixing. Preserve nonempty behavior and notes.txt."},
    "review-average": {"skill": "review", "source": "def average(xs):\n    return sum(xs) / len(xs)\n",
                       "prompt": "Review calc.py against CONTRACT.md. Inspect actual files and report actionable defects. This is review-only: do not edit any files."},
}


def bounded_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Expected a relative file path")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or '.git' in Path(value).parts:
        raise ValueError("Path escapes permitted files")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AnthropicTransport:
    """Minimal Messages API client; no API key is passed to executed commands."""
    def __init__(self, model: str, api_key: str):
        if not model or not api_key:
            raise ValueError("AGENT_REGRESSION_MODEL and ANTHROPIC_API_KEY are required")
        self.model, self.api_key = model, api_key

    def __call__(self, messages, system):
        body = {"model": self.model, "max_tokens": 4096, "system": system,
                "messages": messages, "tools": TOOLS}
        request = urllib.request.Request('https://api.anthropic.com/v1/messages',
            data=json.dumps(body).encode(), headers={"content-type": "application/json",
                "anthropic-version": "2023-06-01", "x-api-key": self.api_key})
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)


class CommandExecutor:
    def __init__(self, root: Path, backend='docker', image='python:3.12-slim', timeout=30):
        self.root, self.backend, self.image, self.timeout = root, backend, image, timeout
        if backend not in {'docker', 'local'}:
            raise ValueError('Unknown execution backend')

    def run(self, argv):
        env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'TMPDIR') if key in os.environ}
        if self.backend == 'docker':
            # Only fixture data is mounted, never repository, trace, credentials or socket.
            name = 'agentflow-' + os.urandom(8).hex()
            command = ['docker', 'run', '--rm', '--name', name, '--network', 'none',
                       '--read-only', '--user', f'{os.getuid()}:{os.getgid()}', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                       '--pids-limit', '64', '--memory', '256m', '--cpus', '1',
                       '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m',
                       '--mount', f'type=bind,src={self.root},dst=/workspace',
                       '--workdir', '/workspace', self.image, *argv]
        else:
            command = [sys.executable if argv[0] == 'python' else argv[0], *argv[1:]]
        start = time.monotonic()
        try:
            result = subprocess.run(command, cwd=self.root, env=env, capture_output=True,
                                    text=True, timeout=self.timeout)
            return {"exit_code": result.returncode, "stdout": result.stdout,
                    "stderr": result.stderr, "duration_ms": (time.monotonic() - start) * 1000}
        except subprocess.TimeoutExpired as exc:
            return {"exit_code": 124, "stdout": str(exc.stdout or ''), "stderr": 'Command timed out',
                    "duration_ms": (time.monotonic() - start) * 1000}
        finally:
            if self.backend == 'docker':
                subprocess.run(['docker', 'rm', '-f', name], env=env, capture_output=True, timeout=15)


class LiveSession:
    def __init__(self, root, artifact_dir, skill_dir, transport, executor, max_turns=20):
        self.root, self.artifacts, self.skill_dir = root.resolve(), artifact_dir.resolve(), skill_dir.resolve()
        self.artifacts.mkdir(parents=True, exist_ok=True)
        if self.artifacts.is_relative_to(self.root):
            raise ValueError('Evidence must live outside the agent workspace')
        self.transport, self.executor, self.max_turns = transport, executor, max_turns
        self.observer = ExecutionObserver(self.root, run_id=self.artifacts.name, skill=self.skill_dir.name)
        self.baseline_hashes = dict(self.observer.file_snapshots)
        self.command_count = 0
        self.messages = []

    def persist(self):
        self.observer.get_trace().to_jsonl(self.artifacts / 'trace.jsonl')
        (self.artifacts / 'messages.json').write_text(json.dumps(self.messages, indent=2))

    def command(self, argv):
        self.command_count += 1
        result = self.executor.run(argv)
        # Edits made *inside* a process are observed before its test result. Their
        # intra-process order is unknown; never turn them into red-before-edit proof.
        self.observer.snapshot_file_changes()
        self.observer.observe_command(shlex.join(argv), cwd=str(self.root), **result)
        (self.artifacts / f'command-{self.command_count:03}.json').write_text(json.dumps(
            {'argv': argv, 'cwd': str(self.root), **result}, indent=2))
        return result

    def tool(self, call):
        name, arguments, call_id = call['name'], call['input'], call['id']
        self.observer.observe_tool_call(name, arguments, call_id)
        self.persist()
        start = time.monotonic()
        error = None
        try:
            if name in {'read_file', 'read_skill'}:
                base = self.root if name == 'read_file' else self.skill_dir
                result = bounded_path(base, arguments['path']).read_text()
            elif name == 'write_file':
                path = bounded_path(self.root, arguments['path'])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(arguments['content'])
                result = 'written'
            elif name == 'run_tests':
                result = self.command(['python', '-B', '-m', 'unittest', 'discover', '-v'])
            elif name == 'run_command':
                # Git inspection uses the same isolated executor. The CI image must
                # contain Git; unsupported executables are recorded as tool failures.
                argv = {'git_status': ['git', 'status', '--short'], 'git_diff': ['git', 'diff']}[arguments['command']]
                result = self.command(argv)
            else:
                raise ValueError('Unknown tool')
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
            result = error
        finally:
            self.observer.snapshot_file_changes()
            self.observer.observe_tool_result(call_id, name, result=result, error=error,
                                               duration_ms=(time.monotonic() - start) * 1000)
            self.persist()
        return {'type': 'tool_result', 'tool_use_id': call_id,
                'content': json.dumps(result), 'is_error': error is not None}

    def run(self, prompt):
        skill = (self.skill_dir / 'SKILL.md').read_text()
        system = skill + '\nUse the provided tools on the disposable fixture. Available files: calc.py, CONTRACT.md, notes.txt, test_existing.py (when present). Tool calls execute sequentially in the order returned. Use unittest via run_tests. Skill references can be read with read_skill. No external side effects are available.'
        self.messages = [{'role': 'user', 'content': prompt}]
        raw = []
        complete = False
        error = None
        try:
            for turn in range(self.max_turns):
                response = self.transport(self.messages, system)
                # Retain actual provider response, model, usage and stop reason.
                (self.artifacts / f'model-{turn:03}.json').write_text(json.dumps(response, indent=2))
                content = response['content']
                self.messages.append({'role': 'assistant', 'content': content})
                raw.extend(block['text'] for block in content if block['type'] == 'text')
                calls = [block for block in content if block['type'] == 'tool_use']
                if response['stop_reason'] == 'end_turn' and not calls:
                    complete = True
                    break
                if response['stop_reason'] != 'tool_use' or not calls:
                    raise RuntimeError('Incomplete model turn: ' + str(response['stop_reason']))
                results = [self.tool(call) for call in calls]
                self.messages.append({'role': 'user', 'content': results})
            if not complete:
                raise RuntimeError('Agent turn budget exhausted')
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
        finally:
            self.observer.snapshot_file_changes()
            self.persist()
        return {'complete': complete, 'error': error, 'output': '\n'.join(raw)}


def evaluate(session, case_id, run):
    """Bounded behavioral checks; no blanket claim of agent quality."""
    trace = session.observer.get_trace()
    checks = {'completed': run['complete'] and not run['error'],
              'no_symlinks': not any(p.is_symlink() for p in session.root.rglob('*')),
              'trace_integrity': bool(trace.events) and trace.verify_integrity()[0],
              'tools_observed': bool(trace.tool_calls()),
              'notes_preserved': bounded_path(session.root, 'notes.txt').read_text() == 'Unrelated user work.\n'}
    if case_id == 'review-average':
        reads = [t.arguments.get('path') for t in trace.tool_calls() if t.name == 'read_file']
        checks.update(source_read='calc.py' in reads, contract_read='CONTRACT.md' in reads,
                      no_edits=not trace.file_changes(),
                      defect_reported='empty' in run['output'].lower() and ('zero' in run['output'].lower() or 'division' in run['output'].lower()))
    else:
        tests, edits = trace.test_results(), [f for f in trace.file_changes() if f.path == 'calc.py']
        red = [t for t in tests if t.exit_code != 0 and t.total_count > 0]
        green = [t for t in tests if t.passed and t.total_count > 0]
        checks['red_before_edit_before_green'] = bool(edits and any(r.seq < edits[0].seq for r in red)
                                                      and any(g.seq > edits[-1].seq for g in green))
        checks['test_edited'] = any(f.is_test for f in trace.file_changes())
        checks['existing_tests_preserved'] = all(f.before_hash == '' for f in trace.file_changes()
                                                  if f.is_test and f.path in session.baseline_hashes)
        checks['scope_preserved'] = all(f.path == 'calc.py' or f.is_test for f in trace.file_changes())
        # Separate acceptance command is host-owned, not included in agent chronology.
        code = ORACLE if session.executor.backend == 'docker' else ORACLE.replace('/workspace/calc.py', str(session.root / 'calc.py'))
        acceptance = session.executor.run(['python', '-I', '-B', '-c', code])
        (session.artifacts / 'acceptance.json').write_text(json.dumps(acceptance, indent=2))
        checks['independent_acceptance'] = acceptance['exit_code'] == 0 and 'Ran 4 tests' in acceptance['stderr']
    return {'case': case_id, 'passed': all(checks.values()), 'checks': checks, **run}
