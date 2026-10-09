"""Executable adjudication for the bounded average review fixtures.

The same report contract is given to defective and clean controls. Expected
findings come from host-owned executions, never keyword matching or model prose.
This is fixture adjudication, not a general semantic code-review judge.
"""
import json
import math

REVIEW_PROMPT = '''Review calc.py against CONTRACT.md. Inspect actual files; do not edit them.
Return your final answer as a single JSON object with exactly verdict and findings.
verdict is "PASS" when there are no contract defects, otherwise "CHANGES_REQUIRED".
Each finding must have exactly: path (relative filename), line (integer source line),
function (function name), input (the concrete numeric list passed to average),
expected (an object with value), and actual (an object with either value or exception,
where exception is the exception class name). Report a minimal reproducing input
for each distinct contract defect. Do not include prose or code fences in the final
answer. Do not invent defects in correct code.'''

# These probes and their results are not supplied to the agent. A fresh process
# executes the unmodified fixture after the review, in the normal isolated executor.
PROBE = '''import importlib.util, json, traceback
spec = importlib.util.spec_from_file_location("candidate", "/workspace/calc.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
findings = []
cases = [[], [2, 4, 9], [-4, 0], [1, 2]]
for values in cases:
    expected = {"value": sum(values)/len(values) if values else 0}
    line = 2
    try:
        actual = {"value": module.average(values)}
    except Exception as exc:
        actual = {"exception": type(exc).__name__}
        for frame in traceback.extract_tb(exc.__traceback__):
            if frame.filename == module.__file__:
                line = frame.lineno
    if actual != expected:
        findings.append({"path": "calc.py", "line": line, "function": "average",
                         "input": values, "expected": expected, "actual": actual})
print(json.dumps({"cases_run": len(cases), "findings": findings}, allow_nan=False))
'''


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate report field')
        result[key] = value
    return result


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def valid_report(report):
    if not isinstance(report, dict) or set(report) != {'verdict', 'findings'}:
        return False
    if report['verdict'] not in ('PASS', 'CHANGES_REQUIRED') or not isinstance(report['findings'], list):
        return False
    if len(report['findings']) > 4:
        return False
    for finding in report['findings']:
        if not isinstance(finding, dict) or set(finding) != {'path', 'line', 'function', 'input', 'expected', 'actual'}:
            return False
        if finding['path'] != 'calc.py' or finding['function'] != 'average' or type(finding['line']) is not int or finding['line'] < 1:
            return False
        if not isinstance(finding['input'], list) or len(finding['input']) > 32 or not all(_number(n) for n in finding['input']):
            return False
        expected, actual = finding['expected'], finding['actual']
        if not isinstance(expected, dict) or set(expected) != {'value'} or not _number(expected['value']):
            return False
        if not isinstance(actual, dict):
            return False
        if set(actual) == {'value'}:
            if not _number(actual['value']):
                return False
        elif set(actual) == {'exception'}:
            if not isinstance(actual['exception'], str) or not actual['exception'].isidentifier():
                return False
        else:
            return False
    return (report['verdict'] == 'CHANGES_REQUIRED') == bool(report['findings'])


def adjudicate(session, final_output, expected_defects):
    checks = {'review_schema_valid': False, 'review_oracle_executed': False,
              'review_verdict_correct': False, 'review_findings_grounded': False}
    try:
        report = json.loads(final_output, object_pairs_hook=_unique_object)
        checks['review_schema_valid'] = valid_report(report)
    except (ValueError, TypeError, OverflowError):
        report = None
    code = PROBE if session.executor.backend == 'docker' else PROBE.replace('/workspace/calc.py', str(session.root / 'calc.py'))
    observation = session.executor.run(['python', '-I', '-B', '-c', code])
    (session.artifacts / 'review-oracle.json').write_text(json.dumps(observation, indent=2))
    try:
        oracle = json.loads(observation['stdout'])
        findings = oracle['findings']
        checks['review_oracle_executed'] = (observation['exit_code'] == 0 and oracle['cases_run'] == 4
                                            and isinstance(findings, list) and len(findings) == expected_defects)
        if checks['review_oracle_executed'] and checks['review_schema_valid']:
            verdict = 'CHANGES_REQUIRED' if findings else 'PASS'
            checks['review_verdict_correct'] = report['verdict'] == verdict
            # One minimal empty-input defect in the buggy seed, none in the clean
            # control. Exact structured facts reject duplicates, wrong locations,
            # incorrect expected/actual outcomes, and unrelated alleged findings.
            checks['review_findings_grounded'] = report['findings'] == findings
    except (ValueError, TypeError, KeyError):
        pass
    (session.artifacts / 'review-adjudication.json').write_text(json.dumps(checks, indent=2))
    return checks
