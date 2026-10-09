"""Real disposable SQLite/broker recovery and fresh archive observations, no test framework."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, required=True)
args = parser.parse_args()
assert args.port == 48668
root = REPO / '.agent_control/proofs' / ('FIX-sidebar-runs-' + str(time.time_ns()))
root.mkdir(parents=True)
from grant_agent.proof_credential_guard import install
install(root)
from grant_agent.connected_sessions.broker import ConnectedBroker, _LiveRun
from grant_agent.connected_sessions.model import SessionSummary
from grant_agent.connected_sessions.sidebar_cleanup import SidebarSafetyObserver
broker = ConnectedBroker(root, adapters={}, load_defaults=False, autostart=False)
receipt = {'schema': 'neyvia.FIX.sidebar-runs.v1', 'root': str(root), 'port': args.port,
           'boundary': 'Actual production ConnectedBroker/RunStore calls on disposable SQLite rows and a real dirty Git folder; no adapter or provider results substituted.', 'checks': []}
def check(name, condition, detail=None):
    receipt['checks'].append({'name': name, 'ok': bool(condition), 'detail': detail})
    assert condition, name
def record(rid, sid, state='completed'):
    return {'runId': rid, 'sessionId': sid, 'app': 'neyvia', 'state': state,
            'startedAt': '2026-10-04T13:00:00Z', 'updatedAt': '2026-10-04T13:00:00Z',
            'pendingRequest': None, 'canStop': state == 'running', 'canSteer': state == 'running'}
def insert(data, updated, token='old-broker'):
    with broker.store.connect() as db:
        db.execute('INSERT INTO connected_session_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (data['runId'], data['sessionId'], 'neyvia', 'fixture', data['state'], os.getpid(),
                    token, 0, updated, updated, json.dumps(data)))
try:
    insert(record('older', 'ties'), 1)
    insert(record('newer-time', 'ties'), 2)
    insert(record('newer-rowid', 'ties'), 2)
    insert(record('dead-owner', 'dead', 'running'), 3)
    insert(record('foreign-dead', 'foreign', 'running'), 3)
    insert(record('persisted-live', 'live', 'running'), 5, broker.token)
    first = _LiveRun(record('first-live', 'live', 'running'), None, 'existing')
    second = _LiveRun(record('second-live', 'live', 'running'), None, 'existing')
    broker._live['first-live'] = first
    broker._live['second-live'] = second
    events = []
    broker.add_event_listener(events.append)
    result = broker._latest_runs(['ties', 'dead', 'live', 'missing', 'ties'])
    check('Same updated timestamp uses latest inserted rowid, matching individual latest()', result['ties']['runId'] == 'newer-rowid' and broker.store.latest('ties')['runId'] == 'newer-rowid')
    check('First live owner keeps existing iteration precedence over newer durable row', result['live']['runId'] == 'first-live' and result['live']['canStop'])
    check('Selected dead owner is interrupted, controls cleared and persisted', result['dead']['state'] == 'interrupted' and not result['dead']['canStop'] and broker.store.load('dead-owner')['state'] == 'interrupted')
    recovery_events = [e for e in events if e.get('type') == 'run.state' and e.get('runId') == 'dead-owner']
    check('Dead owner recovery emits one actual run.state event and repeat does not resend', len(recovery_events) == 1 and not broker.recover(session_keys=['dead']))
    check('Page recovery leaves unrelated dead owner untouched', broker.store.load('foreign-dead')['state'] == 'running')
    check('Missing and empty keys preserve no-record result and no recovery side effects', result['missing'] is None and broker._latest_runs([]) == {} and broker.store.latest_many([]) == {} and broker.store.recover(session_keys=[]) == [])
    insert(record('later', 'ties'), 10)
    check('Next page read sees actual newly committed durable state without cache', broker._latest_runs(['ties'])['ties']['runId'] == 'later')
    folder = root / 'dirty-git'
    folder.mkdir()
    subprocess.run(['git', 'init', '--quiet', str(folder)], check=True, capture_output=True)
    (folder / 'untracked.txt').write_text('Actual fresh dirty archive observation')
    summary = SessionSummary(id='live', app='neyvia', title='Live archive guard', cwd=str(folder))
    count = [0]
    original = broker.latest_run
    def measured(sid):
        count[0] += 1
        return original(sid)
    broker.latest_run = measured
    safety = broker.sidebar_observation(summary, observer=SidebarSafetyObserver(allowed_roots=[str(root)]), cached=False, runs={'live': None})
    check('Fresh archive observation ignores display map, rechecks live run and actual dirty Git', count[0] == 1 and safety['has_running_jobs'] is True and safety['has_uncommitted'] is True, safety)
    check('Batch and existing individual run projection agree on durable terminal record', broker._latest_runs(['ties'])['ties'] == broker.latest_run('ties'))
    receipt['ok'] = True
except Exception as exc:
    receipt['ok'] = False
    receipt['error'] = repr(exc)
    raise
finally:
    receipt['cleanup'] = True
    receipt['sources'] = [{'path': p, 'sha256': hashlib.sha256((REPO/p).read_bytes()).hexdigest()} for p in ['scripts/verify_fix_sidebar_runs.py','src/grant_agent/connected_sessions/broker.py','src/grant_agent/connected_sessions/runs.py','src/grant_agent/connected_sessions/sidebar_cleanup.py']]
    (REPO/'scripts/evidence/FIX-sidebar-runs.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({'ok': receipt['ok'], 'checks': receipt['checks']}))
