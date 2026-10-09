"""Read the small, provider-neutral handoff produced by an external SDD skill.

No dynamic imports, shell dispatch, or provider-owned artifact mutations. The host
invokes configured skills; their reports remain local workflow evidence.
"""
import hashlib
import json
from pathlib import Path

from .config import ShipConfigManager
from .paths import repository_path, validate_change_id

OPERATIONS = ('prepare', 'inspect', 'verify', 'finalize')


def settings(root: Path) -> dict:
    return ShipConfigManager.load(root)['sdd']


def external(root: Path) -> bool:
    return settings(root)['provider'] != 'legacy'


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'SDD {label} must be a nonempty string')
    return value


def _file(root, value):
    path = repository_path(root, _text(value, 'artifact path'))
    if not path.is_file():
        raise ValueError(f'SDD artifact does not exist: {value}')
    return path


def read_changes(root: Path) -> list:
    cfg = settings(root)
    path = repository_path(root, cfg['snapshot'])
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1
            or data.get('provider') != cfg['provider'] or not isinstance(data.get('changes'), list)):
        raise ValueError('Invalid SDD handoff version, provider, or changes')
    ids = set()
    for change in data['changes']:
        if not isinstance(change, dict):
            raise ValueError('SDD change must be an object')
        cid = validate_change_id(change.get('change'))
        if cid in ids:
            raise ValueError(f'Duplicate SDD change: {cid}')
        ids.add(cid)
        for field in ('artifacts', 'tasks'):
            if not isinstance(change.get(field), list):
                raise ValueError(f'SDD {field} must be a list')
            seen = set()
            for item in change[field]:
                if not isinstance(item, dict):
                    raise ValueError(f'SDD {field} entries must be objects')
                key = _text(item.get('id'), f'{field} id')
                if key in seen:
                    raise ValueError(f'Duplicate SDD {field} id: {key}')
                seen.add(key)
                if field == 'artifacts':
                    _file(root, item.get('path'))
                    if item.get('normalization', 'none') not in ('none', 'markdown-checkboxes'):
                        raise ValueError('Unsupported SDD artifact normalization')
                else:
                    _text(item.get('description'), 'task description')
                    if type(item.get('completed')) is not bool:
                        raise ValueError('SDD task completed must be boolean')
        if 'finalization' in change:
            _file(root, change['finalization'])
        if 'verification' in change:
            v = change['verification']
            if not isinstance(v, dict) or v.get('verdict') not in ('PASS', 'FAIL', 'INCONCLUSIVE'):
                raise ValueError('Invalid SDD verification')
            _file(root, v.get('report'))
            for key in ('design_fingerprint', 'tree_fingerprint'):
                _text(v.get(key), key)
    return data['changes']


def selected(root: Path, change: str) -> dict:
    validate_change_id(change)
    for item in read_changes(root):
        if item['change'] == change:
            return item
    raise ValueError(f'SDD change not found in provider handoff: {change}')


def fingerprint(root: Path, change: str) -> str:
    import re
    cfg = settings(root)
    item = selected(root, change)
    if not item['artifacts']:
        raise ValueError('SDD design artifacts are empty')
    records = []
    for artifact in sorted(item['artifacts'], key=lambda a: a['id']):
        data = _file(root, artifact['path']).read_bytes()
        normalization = artifact.get('normalization', 'none')
        if normalization == 'markdown-checkboxes':
            data = re.sub(rb'(?m)^(\s*[-*] )\[[xX ]\]', rb'\1[ ]', data)
        records.append((artifact['id'], normalization, hashlib.sha256(data).hexdigest()))
    # Stable logical IDs permit provider archive moves; task status is not scope.
    payload = {'provider': cfg, 'change': change, 'artifacts': records,
               'tasks': [(t['id'], t['description']) for t in item['tasks']]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def packages(root: Path, target=None, active=None) -> list:
    changes = read_changes(root)
    if target is not None:
        validate_change_id(target)
        changes = [c for c in changes if c['change'] == target]
        if not changes:
            raise ValueError(f'SDD change not found in provider handoff: {target}')
    if target is None:
        from .ledger import FileLedgerStore
        ledger = FileLedgerStore.load(root, auto_sync=False)
        changes = [c for c in changes if ledger.get('changes', {}).get(c['change'], {})
                   .get('evidence', {}).get('delivery', {}).get('status') != 'ARCHIVED']
    result = []
    for item in changes:
        tasks = item['tasks']
        pending = [t for t in tasks if not t['completed']]
        result.append({'change': item['change'], 'path': settings(root)['snapshot'],
                       'has_proposal': bool(item['artifacts']), 'has_specs': bool(item['artifacts']),
                       'has_tasks': bool(tasks), 'total_tasks': len(tasks),
                       'completed_tasks': len(tasks) - len(pending), 'pending_tasks': len(pending),
                       'next_task': pending[0]['description'] if pending else None,
                       'task_list': [dict(t, task_id=t['id']) for t in tasks],
                       'mtime': 0, 'is_active_target': item['change'] == (target or active),
                       'sdd': item})
    return sorted(result, key=lambda p: (not p['is_active_target'], p['change']))


def verification_error(root: Path, change: str, tree_fingerprint: str) -> str | None:
    item = selected(root, change)
    report = item.get('verification', {})
    if report.get('verdict') != 'PASS':
        return 'Run the configured SDD verify skill and record a passing handoff.'
    if report.get('design_fingerprint') != fingerprint(root, change):
        return 'SDD verification is stale for the current design.'
    if not tree_fingerprint or report.get('tree_fingerprint') != tree_fingerprint:
        return 'SDD verification is stale for the current working tree.'
    return None


def finalize(root: Path, change=None, force=False) -> dict:
    """Record provider finalization only after Ship's normal readiness checks."""
    from .ledger import FileLedgerStore
    from .evidence import inspect_review_reports, inspect_spikes, validate_design_approval
    from .gates import validate_delivery_readiness
    from .vcs import GitClient
    from .trailers import CommitTrailerGenerator
    if force:
        raise RuntimeError('External SDD finalization cannot bypass delivery gates')
    cid = change or FileLedgerStore.get_active_change(root)
    if not cid:
        raise ValueError('Select an SDD change before finalization')
    item = selected(root, cid)
    entry = FileLedgerStore.load(root, auto_sync=False).get('changes', {}).get(cid)
    if (entry or {}).get('evidence', {}).get('delivery', {}).get('status') == 'ARCHIVED':
        return dict(entry['evidence']['delivery'], change=cid)
    decision = validate_delivery_readiness(
        inspect_review_reports(root, change=cid), packages(root, target=cid)[0],
        GitClient().get_info(root), entry,
        design_error=validate_design_approval(root, cid, entry), spikes=inspect_spikes(root),
        repo_root=root, verification_config=ShipConfigManager.load(root))
    if decision[1] != 'DELIVERY_READY':
        raise RuntimeError(f'Cannot finalize {cid}: {decision[2]}')
    if not item.get('finalization'):
        raise RuntimeError('Run the configured SDD finalize skill and record its finalization artifact first')
    trailers = [t for t in CommitTrailerGenerator.generate(root, change_id=cid) if not t.startswith('Ship-Delivery:')]
    trailers.append('Ship-Delivery: ARCHIVED')
    result = {'status': 'ARCHIVED', 'provider': settings(root)['provider'],
              'finalization': item['finalization'], 'trailers': trailers}
    def update(entry):
        entry['phase'] = 'delivery'
        entry['evidence']['delivery'].update(result)
    FileLedgerStore.mutate_change(root, cid, update, set_active=False)
    return dict(result, change=cid)
