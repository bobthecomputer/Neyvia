"""Fresh, integrity-checked terminal completion; task effects still require G."""
from __future__ import annotations

import json
from pathlib import Path

from ..action_receipts import _digest

SUPPORTED = {'terminal.exec'}


def snapshot_for(protocol, name, args):
    arguments = protocol.gateway.native.prepare_arguments(name, args)
    base = protocol.gateway.actions.base
    paths = list(base.glob('*.json'))
    if len(paths) > 2000:
        raise ValueError('Terminal action inventory exceeds 2000 records')
    request_hash = _digest({'tool':name,'arguments':{'workspace':str(protocol.gateway.root),'arguments':arguments}})
    snapshot = {'existing': [path.name for path in paths], 'requestHash': request_hash}
    for path in sorted(paths, key=lambda item: item.stat().st_mtime_ns, reverse=True):
        if path.is_symlink() or path.stat().st_size > 4*1024*1024:
            raise ValueError('Terminal action record exceeds its owning bound')
        row = json.loads(path.read_bytes())
        if row.get('requestHash') != request_hash or row.get('toolId') != name or row.get('status') != 'completed':
            continue
        saved_path = path.with_suffix('.result')
        if saved_path.is_symlink() or saved_path.stat().st_size > 4*1024*1024:
            raise ValueError('Terminal result exceeds its owning bound')
        saved = json.loads(saved_path.read_bytes())
        if _digest(saved) == row.get('resultHash'):
            snapshot['execution'] = saved.get('toolResult', {})
        break
    return snapshot


def _observe(protocol, arguments, value, previous):
    base = protocol.gateway.actions.base.resolve()
    action_id = value.get('terminalActionId')
    paths = [protocol.gateway.actions._path(action_id)] if action_id else [
        path for path in base.glob('*.json') if path.name not in previous['existing']]
    if len(paths) > 2000:
        raise ValueError('Terminal completion inventory exceeds 2000 records')
    found = []
    for path in paths:
        if path.parent.resolve() != base or path.is_symlink() or path.stat().st_size > 4*1024*1024:
            raise ValueError('Terminal action record is outside its owning bound')
        row = json.loads(path.read_bytes())
        if row.get('toolId') != 'terminal.exec' or row.get('requestHash') != previous['requestHash']:
            continue
        if row.get('schema') != 'neyvia.native_action.v1' or row.get('status') != 'completed':
            return None
        result_path = path.with_suffix('.result')
        if result_path.is_symlink() or result_path.stat().st_size > 4*1024*1024:
            raise ValueError('Terminal saved result exceeds its owning bound')
        saved = json.loads(result_path.read_bytes())
        if _digest(saved) != row.get('resultHash') or saved.get('ok') is not True:
            return None
        command = saved.get('toolResult', {})
        if (command.get('command') != arguments['command'] or command.get('status') != 'completed'
                or command.get('exitCode') != 0 or command.get('timedOut') is not False
                or command.get('captureIncomplete') is not False):
            return None
        cwd = Path(arguments.get('cwd') or protocol.gateway.root)
        if not cwd.is_absolute():
            cwd = protocol.gateway.root/cwd
        if Path(command['cwd']).resolve() != cwd.resolve():
            return None
        if any(value.get(key) != command.get(key) for key in ('command','cwd','shell','exitCode','stdout','stderr','status')):
            return None
        found.append((row, command))
    if len(found) != 1:
        return None
    value['terminalActionId'] = found[0][0]['actionId']
    return found[0]


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    return [{'name':'effect-terminal-completion','observer':True,'effect':True,
             'subjectKey':'terminal:pending',
             'bindSubject':lambda arguments,value,previous:'terminal:'+value['terminalActionId'],
             'observerTool':'durable-terminal-action-store','subject':{'command':args['command']},
             'expectation':'Fresh exact command/cwd record and hash-checked saved output prove exit zero and complete capture; observer G proves the requested task effect',
             'check':lambda arguments,value,previous:_observe(protocol,arguments,value,previous) is not None}]
