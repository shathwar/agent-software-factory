"""Correlated skill-step observations; completion is a claim, not a quality verdict.

The event stream is the only trace state. Every read/transition is integrity checked
under the existing process lock. No ledger migration or readiness change is needed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

from .events import EventLogger
from .ledger import FileLedgerStore
from .paths import repository_path, validate_change_id
from .step_catalog import SKILLS

STATUSES = ('unobserved', 'started', 'completed', 'failed', 'skipped')
EVENTS = {status: 'STEP_' + status.upper() for status in STATUSES[1:]}


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')
    return value


class StepTrace:
    def __init__(self, repo_root: Path):
        self.root = Path(repo_root).resolve()
        self.logger = EventLogger(self.root)

    @staticmethod
    def catalog(skills=None):
        names = list(SKILLS) if skills is None else skills
        if not isinstance(names, list) or not names or any(not isinstance(n, str) or n not in SKILLS for n in names):
            raise ValueError('Select one or more registered skills')
        if len(set(names)) != len(names):
            raise ValueError('Duplicate skills')
        return deepcopy({name: SKILLS[name] for name in names})

    def _events(self):
        valid, message, _ = self.logger.verify_integrity()
        if not valid:
            raise ValueError(f'Cannot trust step trace: {message}')
        return self.logger.read_all()

    def begin(self, skills, *, change_id=None, task_id=None, agent_id=None, session_id=None, model=None):
        if skills is None:
            raise ValueError('Select one or more registered skills')
        catalog = self.catalog(skills)
        if change_id is not None:
            validate_change_id(change_id)
        for name, value in [('task_id', task_id), ('agent_id', agent_id), ('session_id', session_id), ('model', model)]:
            if value is not None:
                _text(value, name)
        run_id = 'run-' + uuid4().hex
        with FileLedgerStore.lock(self.root, recover=False):
            self._events()
            event = self.logger.emit('SKILL_RUN_STARTED', change_id=change_id, task_id=task_id,
                                     agent_id=agent_id, session_id=session_id, target=run_id,
                                     payload={'schema_version': 1, 'run_id': run_id, 'skills': catalog,
                                              'model': model, 'capture_kind': 'reported'})
        return {'run_id': run_id, 'event_id': event.event_id, 'skills': catalog}

    def _run(self, run_id, events):
        _text(run_id, 'run_id')
        matches = [e for e in events if e.event_type == 'SKILL_RUN_STARTED' and e.payload.get('run_id') == run_id]
        if len(matches) != 1:
            raise ValueError(f'Unknown or ambiguous run: {run_id}')
        return matches[0]

    def _steps(self, run, events):
        steps = {s['id']: {**deepcopy(s), 'status': 'unobserved', 'attempts': []}
                 for skill in run.payload['skills'].values() for s in skill['steps']}
        for event in events:
            if event.payload.get('run_id') != run.payload['run_id'] or event.event_type not in EVENTS.values():
                continue
            p = event.payload
            if event.event_type != EVENTS.get(p.get('status')) or p.get('step_id') not in steps:
                raise ValueError('Invalid step event type or ID')
            _text(p.get('attempt_id'), 'attempt_id')
            step = steps[p['step_id']]
            attempts = step['attempts']
            active = attempts[-1] if attempts and attempts[-1]['status'] == 'started' else None
            creates_attempt = p['status'] == 'started' or (p['status'] == 'skipped' and not p.get('started_event_id'))
            if creates_attempt and active:
                raise ValueError('Overlapping step attempts in event history')
            if not creates_attempt and (not active or active['attempt_id'] != p['attempt_id']
                                        or active['started_event_id'] != p.get('started_event_id')):
                raise ValueError('Step result has no matching active start')
            if p['status'] in ('failed', 'skipped'):
                _text(p.get('reason'), 'reason')
            if p['status'] == 'completed' and not p.get('evidence'):
                raise ValueError('Completion has no evidence')
            if p['status'] == 'started' or (p['status'] == 'skipped' and not p.get('started_event_id')):
                attempts.append({'attempt_id': p['attempt_id'], 'attempt_number': len(attempts) + 1,
                                 'started_at': event.timestamp if p['status'] == 'started' else None,
                                 'started_event_id': event.event_id if p['status'] == 'started' else None})
            if not attempts or attempts[-1]['attempt_id'] != p['attempt_id']:
                raise ValueError('Invalid step attempt history')
            attempts[-1].update(status=p['status'], event_id=event.event_id, reason=p.get('reason'),
                                evidence=deepcopy(p.get('evidence', [])),
                                ended_at=None if p['status'] == 'started' else event.timestamp,
                                duration_seconds=p.get('duration_seconds'))
            step['status'] = p['status']
        return steps

    def _evidence(self, paths):
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
            raise ValueError('evidence must be a list of repository-relative file paths')
        if len(set(paths)) != len(paths):
            raise ValueError('Duplicate evidence paths')
        records = []
        for relative in paths:
            path = repository_path(self.root, relative)
            if path == self.logger.event_file or path.name == 'state.lock':
                raise ValueError('Mutable trace infrastructure cannot be evidence')
            if not path.is_file():
                raise ValueError(f'Evidence file not found: {relative}')
            digest = hashlib.sha256()
            size = 0
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(65536), b''):
                    digest.update(block)
                    size += len(block)
            records.append({'path': relative, 'sha256': digest.hexdigest(), 'bytes': size})
        return records

    def record(self, run_id, step_id, status, *, attempt_id=None, evidence=None, reason=None):
        if status not in EVENTS:
            raise ValueError('status must be started, completed, failed, or skipped')
        _text(step_id, 'step_id')
        if status in ('failed', 'skipped'):
            _text(reason, 'reason')
        elif reason is not None:
            _text(reason, 'reason')
        if status == 'started' and (evidence or reason or attempt_id):
            raise ValueError('A start generates its attempt ID and has no result evidence or reason')
        with FileLedgerStore.lock(self.root, recover=False):
            events = self._events()
            run = self._run(run_id, events)
            steps = self._steps(run, events)
            if step_id not in steps:
                raise ValueError(f'Step not registered in this run: {step_id}')
            attempts = steps[step_id]['attempts']
            active = attempts[-1] if attempts and attempts[-1]['status'] == 'started' else None
            if status == 'started':
                if active:
                    raise ValueError('Step already started; finish the active attempt first')
                attempt_id = 'attempt-' + uuid4().hex
            elif status == 'skipped' and active is None and attempt_id is None:
                attempt_id = 'attempt-' + uuid4().hex
            elif not active or attempt_id != active['attempt_id']:
                raise ValueError('Result must reference the active attempt ID')
            receipts = self._evidence([] if evidence is None else evidence)
            if status == 'completed' and not receipts:
                raise ValueError('Completion requires at least one evidence file')
            now = datetime.now(timezone.utc)
            duration = None
            if active:
                duration = max(0.0, (now - datetime.fromisoformat(active['started_at'])).total_seconds())
            payload = {'schema_version': 1, 'run_id': run_id, 'step_id': step_id,
                       'attempt_id': attempt_id, 'status': status, 'reason': reason,
                       'evidence': receipts, 'capture_kind': 'reported',
                       'started_event_id': active['started_event_id'] if active else None,
                       'duration_seconds': duration}
            event = self.logger.emit(EVENTS[status], change_id=run.change_id, task_id=run.task_id,
                                     agent_id=run.agent_id, session_id=run.session_id, target=step_id,
                                     payload=payload, timestamp=now.isoformat())
            return {**payload, 'event_id': event.event_id}

    def report(self, run_id):
        with FileLedgerStore.lock(self.root, recover=False):
            events = self._events()
            run = self._run(run_id, events)
            steps = list(self._steps(run, events).values())
            issues = 0
            for step in steps:
                for attempt in step['attempts']:
                    for receipt in attempt['evidence']:
                        try:
                            current = self._evidence([receipt['path']])[0]
                            receipt['integrity'] = 'current' if current['sha256'] == receipt['sha256'] else 'changed'
                        except (ValueError, OSError):
                            receipt['integrity'] = 'missing_or_unsafe'
                        issues += receipt['integrity'] != 'current'
            counts = {status: sum(s['status'] == status for s in steps) for status in STATUSES}
            return {'schema_version': 1, 'run_id': run_id, 'change_id': run.change_id,
                    'task_id': run.task_id, 'agent_id': run.agent_id, 'session_id': run.session_id,
                    'model': run.payload['model'], 'skills': run.payload['skills'], 'steps': steps,
                    'counts': counts, 'evidence_issues': issues,
                    'fully_observed': counts['unobserved'] == 0 and counts['started'] == 0,
                    'capture_kind': 'reported',
                    'limitations': ['Recorded completion is not independent verification of behavior or quality.',
                                    'Timestamps establish recording order, not uninstrumented edit/tool chronology.',
                                    'Interrupted attempts remain started; evidence contents are not stored.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, prog='agentflow steps')
    actions = parser.add_subparsers(dest='action', required=True)
    catalog = actions.add_parser('catalog', help='List stable step IDs and evidence expectations')
    catalog.add_argument('--skill', action='append', dest='skills')
    begin = actions.add_parser('begin', help='Begin a run for one task/invocation')
    begin.add_argument('--skill', action='append', dest='skills', required=True)
    for option in ('change', 'task', 'agent', 'session', 'model'):
        begin.add_argument('--' + option)
    for action in ('started', 'completed', 'failed', 'skipped'):
        sub = actions.add_parser(action)
        sub.add_argument('run_id')
        sub.add_argument('step_id')
        sub.add_argument('--attempt', dest='attempt_id')
        sub.add_argument('--evidence', action='append', default=[])
        sub.add_argument('--reason')
    report = actions.add_parser('report', help='Show observed and unobserved steps (not a quality gate)')
    report.add_argument('run_id')
    for sub in actions.choices.values():
        sub.add_argument('--path', default='.')
    args = parser.parse_args(argv)
    try:
        trace = StepTrace(Path(args.path))
        if args.action == 'catalog':
            result = trace.catalog(args.skills)
        elif args.action == 'begin':
            result = trace.begin(args.skills, change_id=args.change, task_id=args.task,
                                 agent_id=args.agent, session_id=args.session, model=args.model)
        elif args.action == 'report':
            result = trace.report(args.run_id)
        else:
            result = trace.record(args.run_id, args.step_id, args.action, attempt_id=args.attempt_id,
                                  evidence=args.evidence, reason=args.reason)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'Step trace error: {exc}', file=sys.stderr)
        return 1
