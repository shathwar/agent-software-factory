"""Bounded Ship trial using the real installed lifecycle inside the executor.

The host supplies one design approval and simulates a context reset and a later
source edit. These are fixture actions, never authentication or general quality proof.
"""
import json

from .live import LiveSession, TOOLS, bounded_path, digest, evaluate

CHANGE = 'average'
SHIP_TOOLS = TOOLS + [
    {'name': 'read_related_skill', 'description': 'Read a Ship specialist skill or reference.',
     'input_schema': {'type': 'object', 'properties': {
         'skill': {'enum': ['design', 'tdd', 'simplify', 'review', 'spike']},
         'path': {'type': 'string'}}, 'required': ['skill', 'path'], 'additionalProperties': False}},
    {'name': 'lifecycle', 'description': 'Execute the installed Ship inspector for change average. Approvals are host-owned.',
     'input_schema': {'type': 'object', 'properties': {
         'action': {'enum': ['doctor', 'next', 'fingerprint', 'design_digest', 'checkpoint_design',
                            'checkpoint_implementation', 'record_tests', 'record_review', 'verify', 'status', 'archive', 'trailers']},
         'report': {'type': 'string'}}, 'required': ['action'], 'additionalProperties': False}},
]
SHIP_CASE = {
    'skill': 'ship', 'source': 'def average(xs):\n    raise NotImplementedError\n',
    'prompt': 'Use Ship to implement average(xs), arithmetic mean and 0 for empty input, in change average. '
              'The design frontier is settled: preserve the existing function API and use Python stdlib unittest. '
              'Compile the ADR and OpenSpec package, then stop for approval of those artifacts. '
              'After approval complete implementation, review, verification and archive. Preserve notes.txt. '
              'Use the installed lifecycle tool; do not fabricate ledger or verification receipts. '
              'No branch commits, pushes or deployments are requested; internal checkpoints and Git notes are permitted.'}


class ShipSession(LiveSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.approved = False
        self.drift_injected = False
        self.drift_rejected = False
        self.ready_after_drift = False
        self.archived = False
        self.config_hash = digest(self.root / '.agentflow.json')
        self.approval_seq = None

    def session_context(self):
        return ('\nThis fixture has the full installed Ship suite. Use lifecycle for inspector actions and '
                'read_related_skill for specialists. The host supplies design approval only after you '
                'present the package and end your turn. Change ID is average. .agentflow.json defines '
                'the test command. Shell execution is restricted to these typed tools. Budget accounting '
                'is unavailable; report not recorded. Existing approvals survive a context reset.')

    def inspector(self, *args):
        script = ('/opt/agentflow/skills/ship/scripts/inspect_lifecycle.py' if self.executor.backend == 'docker'
                  else str(self.skill_dir / 'scripts/inspect_lifecycle.py'))
        return self.command(['python', '-B', script, '--change', CHANGE, *args])

    def execute_tool(self, name, arguments):
        if name == 'read_related_skill':
            if arguments['skill'] not in {'design', 'tdd', 'simplify', 'review', 'spike'}:
                raise ValueError('Unknown specialist')
            return bounded_path(self.skill_dir.parent / arguments['skill'], arguments['path']).read_text()
        if name == 'write_file':
            path = bounded_path(self.root, arguments['path'])
            relative = path.relative_to(self.root).as_posix()
            if relative == '.agentflow.json' or (relative.startswith('.agentflow/') and
                                                 not relative.startswith('.agentflow/reviews/')):
                raise ValueError('Host config and lifecycle evidence are not writable through write_file')
        if name != 'lifecycle':
            return super().execute_tool(name, arguments)
        action = arguments['action']
        operations = {
            'doctor': ['--doctor', '--format', 'json'], 'next': ['--next-turn', '--format', 'json'],
            'fingerprint': ['--fingerprint'], 'design_digest': ['--design-fingerprint'],
            'checkpoint_design': ['--checkpoint', 'design'],
            'checkpoint_implementation': ['--checkpoint', 'implementation'],
            'record_tests': ['--record-tests', 'pass'],
            'verify': ['--verify', '--tier', 'execution', '--format', 'json'],
            'status': ['--status-check', '--format', 'json'],
            'archive': ['--archive', CHANGE, '--format', 'json'],
            'trailers': ['--generate-trailers', '--format', 'json'],
        }
        if action == 'record_review':
            report = bounded_path(self.root, arguments['report']).relative_to(self.root).as_posix()
            argv = ['--record-review', report]
        else:
            argv = operations[action]
        result = self.inspector(*argv)
        if action == 'status' and result['exit_code'] == 0:
            if not self.drift_injected:
                # Change the tested snapshot after a genuine ready verdict. Observe
                # the host edit separately and prove stale delivery is rejected.
                with (self.root / 'calc.py').open('a') as stream:
                    stream.write('\n# Host fixture edit after readiness.\n')
                self.observer.snapshot_file_changes()
                self.drift_injected = True
                blocked = self.inspector('--status-check', '--format', 'json')
                self.drift_rejected = blocked['exit_code'] != 0
                (self.artifacts / 'stale-readiness.json').write_text(json.dumps(blocked, indent=2))
                result = {**result, 'host_event': 'The user changed calc.py after this check. Inspect the edit and refresh evidence before delivery.',
                          'current_status': blocked}
            else:
                self.ready_after_drift = True
        if action == 'archive' and result['exit_code'] == 0:
            self.archived = self.ready_after_drift and self.approved
        return result

    def on_completion(self):
        if self.approved:
            return None
        # Do not silently repair incomplete artifacts or approve an implementation
        # that has already skipped the human boundary.
        if digest(self.root / 'calc.py') != self.baseline_hashes['calc.py']:
            raise RuntimeError('Production changed before design approval')
        package = self.root / 'openspec/changes' / CHANGE
        required = [package / 'proposal.md', package / 'tasks.md']
        if not all(p.is_file() and p.read_text().strip() for p in required) or not list(package.glob('specs/**/*.md')) or not list((self.root / 'docs/adr').glob('*.md')):
            raise RuntimeError('Design package incomplete at approval boundary')
        result = self.inspector('--design-fingerprint')
        if result['exit_code']:
            raise RuntimeError('Cannot fingerprint design')
        fingerprint = result['stdout'].strip()
        approval = self.inspector('--approve-design', fingerprint, '--approved-by', 'fixture-host')
        if approval['exit_code']:
            raise RuntimeError('Cannot record fixture approval')
        self.approved = True
        self.approval_seq = len(self.observer.get_trace().events)
        (self.artifacts / 'host-approval.json').write_text(json.dumps({
            'design_digest': fingerprint, 'approval_seq': self.approval_seq,
            'context_reset': True, 'kind': 'synthetic_fixture_authorization'}, indent=2))
        # A new model context must discover and resume from the real workspace.
        return ('The session was interrupted after I approved the average ADR/OpenSpec package '
                f'with digest {fingerprint}. Approval is recorded. Resume Ship from the workspace, '
                'implement average, review, verify, and archive. Preserve notes.txt and any user edits. '
                'Use sequential specialist passes and disclose that mode.')


def evaluate_ship(session, run):
    result = evaluate(session, 'ship-average', run)
    checks = result['checks']
    # Ship legitimately writes design and review artifacts as well as source/tests.
    permitted = ('docs/adr/', 'openspec/', '.agentflow/reviews/')
    changes = session.observer.get_trace().file_changes()
    checks['scope_preserved'] = all(f.path == 'calc.py' or f.is_test or f.path.startswith(permitted) for f in changes)
    edits = [f for f in changes if f.path == 'calc.py']
    checks.update(design_approved_before_code=bool(session.approval_seq and edits and edits[0].seq > session.approval_seq),
                  resumed_after_approval=session.approved,
                  stale_delivery_rejected=session.drift_rejected,
                  fresh_delivery_after_drift=session.ready_after_drift,
                  archived_through_runtime=session.archived,
                  config_preserved=digest(session.root / '.agentflow.json') == session.config_hash,
                  host_edit_preserved='# Host fixture edit after readiness.' in (session.root / 'calc.py').read_text(),
                  archive_exists=bool(list((session.root / 'openspec/archive').glob('*-average'))))
    result['passed'] = all(checks.values())
    return result
