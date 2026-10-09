"""Exact service observations and durable setup/native-check effects.

Provider completion is deliberately not inferred from admission or a queued job.
"""
from __future__ import annotations

from copy import deepcopy
import json
import hashlib
from pathlib import Path
import time
from datetime import datetime

from .effects import _bus, _measure_file, _call

SUPPORTED = {'neyvia.settings.setup', 'neyvia.native.runtime.self-check',
             'neyvia.autopilot.start', 'neyvia.autopilot.resume',
             'neyvia.conductor.plan', 'neyvia.conductor.control'}
READS = {'neyvia.onboarding.runtimes', 'neyvia.gamedev.sessions',
         'neyvia.gamedev.asset_validate', 'neyvia.settings.network_check'}


def readonly(name, args):
    return True if name in READS else None


def _setup_events(protocol):
    with _bus(protocol).connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM events WHERE action='setup.open' ORDER BY id")]


def snapshot_for(protocol, name, args):
    if name in {'neyvia.conductor.plan', 'neyvia.conductor.control'}:
        from ..harness_jobs import HarnessJobStore
        store = HarnessJobStore(protocol.gateway.root)
        identity = 'harness-job-conductor-' + hashlib.sha256(args['requestId'].encode()).hexdigest()[:32] if name.endswith('.plan') else args['id']
        prior = store.load(identity, reconcile=False) if store.job_path(identity).exists() else None
        return {'identity': identity, 'prior': prior,
                'routes': deepcopy(prior['request']['routes'] if prior else {
                    key: row for key, row in _bus(protocol).get('runtime.profiles', {}).items()
                    if key in {'planner', 'executor', 'verifier', 'classifier'}})}
    if name in {'neyvia.autopilot.start', 'neyvia.autopilot.resume'}:
        from ..neyvia_autopilot import load, state_path
        from ..neyvia_workspace_tools import workspace_for
        service = workspace_for(protocol.gateway.root)
        identity = hashlib.sha256(args['requestId'].encode()).hexdigest()[:32] if name.endswith('.start') else args['runId']
        return {'identity': identity, 'prior': load(service, identity) if state_path(service, identity).exists() else None}
    if name == 'neyvia.settings.setup':
        from ..neyvia_settings import get
        from ..neyvia_workspace_tools import workspace_for
        observed = get(workspace_for(protocol.gateway.root))
        return {'state': deepcopy(observed), 'events': _setup_events(protocol), 'started': time.time()}
    if name == 'neyvia.native.runtime.self-check':
        return {'root': str(Path(protocol.gateway.root).resolve() / '.agent_control/proofs/native-self-check'),
                'started': time.time()}
    return None


def _verify(protocol, name, args, value, before):
    if name in {'neyvia.conductor.plan', 'neyvia.conductor.control'}:
        from ..harness_jobs import HarnessJobStore
        from ..neyvia_conductor import _task_tree, _json_reply
        import sqlite3
        job = HarnessJobStore(protocol.gateway.root).load(before['identity'])
        if value.get('job', {}).get('id') != job['id'] or job['request']['routes'] != before['routes']:
            return False
        state = job.get('conductor', {})
        if name.endswith('.plan'):
            intent = {'goal': args['goal'].strip(), 'folder': str(Path(args['folder']).resolve()),
                      'acceptanceChecks': args['acceptanceChecks'], 'maxRuntimeSeconds': args.get('maxRuntimeSeconds', 1800)}
            if job['request']['intent'] != intent:
                return False
            receipt = next((row for row in state.get('receipts', []) if row['runId'] == job['id'] + '-plan'), None)
            if not receipt or not receipt.get('reply'):
                return None if job['status'] in {'queued', 'running'} else False
            database = Path(protocol.gateway.root) / '.agent_control/connected_chats.sqlite3'
            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
                row = db.execute('SELECT data FROM connected_session_runs WHERE run_id=?', (receipt['runId'],)).fetchone()
            run = json.loads(row[0]) if row else {}
            route = before['routes']['planner']
            if (receipt['state'] != 'completed' or run.get('state') != 'completed' or not receipt.get('sessionId') or
                    run.get('sessionId') != receipt['sessionId'] or receipt['route'] != route or
                    any(run.get(key) != route.get(key) for key in ('model', 'effort', 'permissionMode')) or run.get('app') != route['app']):
                return False
            expected = _task_tree(_json_reply(receipt['reply']), before['routes'], intent['acceptanceChecks'])
            fields = ('id', 'parentId', 'title', 'prompt', 'routingProfile', 'route', 'needs')
            return [{key: item.get(key) for key in fields} for item in state.get('tasks', [])] == [{key: item.get(key) for key in fields} for item in expected]
        prior = before['prior']
        if prior is None or job['request'] != prior['request']:
            return False
        control = job.get('conductorControl', {})
        action = args['action']
        if action == 'stop':
            return job['status'] == 'cancelled' and not job.get('pid')
        expected = {'approved': action in {'start', 'resume'} or prior.get('conductorControl', {}).get('approved', False),
                    'paused': action == 'pause'}
        if control != expected:
            return False
        fields = ('id', 'parentId', 'title', 'prompt', 'routingProfile', 'route', 'needs')
        if [{key: item.get(key) for key in fields} for item in state.get('tasks', [])] != [{key: item.get(key) for key in fields} for item in prior.get('conductor', {}).get('tasks', [])]:
            return False
        if action == 'pause':
            return True if state.get('phase') == 'paused' else None if job['status'] == 'running' else False
        # Start/resume must reach the real worker's execution checkpoint.
        execution_ids = [row.get('runId') for row in state.get('receipts', [])
                         if row.get('runId') and row['runId'] != job['id'] + '-plan']
        active_id = state.get('activeRun', {}).get('runId')
        if active_id and active_id != job['id'] + '-plan':
            execution_ids.append(active_id)
        if state.get('phase') in {'running', 'completed', 'failed'} and execution_ids:
            database = Path(protocol.gateway.root) / '.agent_control/connected_chats.sqlite3'
            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
                return any(db.execute('SELECT 1 FROM connected_session_runs WHERE run_id=?', (identity,)).fetchone()
                           for identity in execution_ids)
        return None if job['status'] == 'running' else False
    if name in {'neyvia.autopilot.start', 'neyvia.autopilot.resume'}:
        from ..neyvia_autopilot import load
        from ..neyvia_workspace_tools import workspace_for
        from ..neyvia_manuals import expect
        from ..action_receipts import _safe_tool_result
        run = load(workspace_for(protocol.gateway.root), before['identity'])
        if run.get('status') != 'completed' or _safe_tool_result(run) != value.get('run') or _bus(protocol).get('autopilot:'+before['identity']) != run:
            return False
        if name.endswith('.start'):
            if run['text'] != args['text'] or run['scopeTools'] != args['scopeTools'] or run['requestId'] != args['requestId']:
                return False
        elif before['prior'] is None or any(run.get(key) != before['prior'].get(key) for key in ('text','scopeTools','fingerprint','requestId')):
            return False
        if not run.get('items') or any(row.get('status') != 'completed' or row.get('verification',{}).get('passed') is not True or row.get('receipt',{}).get('status') != 'completed' for row in run['items']):
            return False
        for item in run['items']:
            verification = item['selection']['verify']
            if verification['tool'] not in run['scopeTools']:
                return False
            observed = _call(protocol, verification['tool'], verification['args'])
            if not expect(observed, verification['expect'], {}, {}, protocol.gateway.root):
                return False
        for row in run.get('models', []):
            model = json.loads(Path(row['receiptPath']).read_bytes())
            if row.get('status') != 'completed' or row.get('usageKnown') is not True or model.get('status') != 'completed' or model.get('model') != row['model'] or model.get('tokens') != row['tokens']:
                return False
        return bool(run.get('models') or run.get('cascade'))
    if name == 'neyvia.settings.setup':
        from ..neyvia_settings import get
        from ..neyvia_workspace_tools import workspace_for
        observed = get(workspace_for(protocol.gateway.root))
        if any(observed.get(key) != row for key, row in before['state'].items() if key != 'setup'):
            return False
        events = _setup_events(protocol)
        if len(events) != len(before['events']) + 1 or events[:-1] != before['events']:
            return False
        last = events[-1]
        return (json.loads(last['payload']) == {'resume': True} and
                observed['setup'] == value.get('setup') and
                before['started'] <= datetime.fromisoformat(observed['setup']['requestedAt']).timestamp() <= datetime.fromisoformat(last['ts']).timestamp() and
                value.get('events', [{}])[0].get('ts') == last['ts'] and
                value.get('events', [{}])[0].get('id') == str(last['id']))
    if name == 'neyvia.native.runtime.self-check':
        path = Path(value.get('receiptPath', '')).resolve()
        scratch = Path(value.get('scratchRoot', '')).resolve()
        if not scratch.is_relative_to(Path(before['root'])) or path != scratch / 'self-check-receipt.json':
            return False
        receipt = json.loads(path.read_bytes())
        from ..action_receipts import _safe_tool_result
        if _safe_tool_result(receipt) != {key: row for key, row in value.items() if key != 'receiptPath'}:
            return False
        cases = receipt.get('cases', [])
        if not cases or not receipt.get('ok') or any(row.get('ok') is not True for row in cases) or receipt.get('failures'):
            return False
        manifest = receipt.get('fileHashes', {})
        return bool(manifest) and all(
            (scratch / relative).resolve().is_relative_to(scratch) and
            _measure_file(scratch / relative).get('sha256') == expected
            for relative, expected in manifest.items())
    return False


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    observer = ('neyvia.settings.get' if name == 'neyvia.settings.setup' else
                'neyvia.conductor.get' if '.conductor.' in name else
                'neyvia.autopilot.get' if '.autopilot.' in name else 'native-check-retained-files')
    if protocol.scope is not None and observer.startswith('neyvia.') and observer not in protocol.scope:
        return []
    def verify(arguments, value, previous):
        try:
            return _verify(protocol, name, arguments, value, previous)
        except (OSError, KeyError, ValueError, TypeError):
            return False
    return [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'),
             'effect': True, 'observer': True, 'observerTool': observer, 'deferred': '.conductor.' in name,
             'subjectKey': name + ':' + str(protocol.gateway.root) + (':' + str(args.get('id', args.get('requestId'))) if '.conductor.' in name else ''), 'subject': deepcopy(args),
             'expectation': 'Fresh setup event and unchanged settings, or full passed native contract receipt with unchanged retained evidence',
             'check': verify}]
