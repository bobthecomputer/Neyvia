/* Node-driven checks against production dashboard, real Codex RPC/OS locks and
 * a disposable conversation store. No model call or global configuration. */
const { spawn } = require('node:child_process');
const { resolve } = require('node:path');
const python = process.env.T9_PYTHON || 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const source = String.raw`
import json, time, uuid
from pathlib import Path
from types import SimpleNamespace
from grant_agent.connected_sessions.broker import ConnectedBroker
from grant_agent.connected_sessions.codex import CodexAdapter
from grant_agent.connected_sessions.neyvia import NeyviaAdapter
from grant_agent.connected_sessions.dashboard import build
from grant_agent.neyvia_conversations import NeyviaConversationStore
folder = Path('.agent_control/t9-dashboard/proof-' + uuid.uuid4().hex[:12]).resolve()
folder.mkdir(parents=True)
receipt = {'checks': {}, 'fixtureRoot': str(folder), 'boundaries': ['Production broker and dashboard on disposable persisted conversations', 'Live installed Codex RPC plus OS writer ownership inventory; no new model turn']}
started = time.monotonic()
broker, codex, live_broker = None, None, None
try:
    store = NeyviaConversationStore(folder)
    with store._connection() as connection:
        rows = [('idle-' + str(i), 'chat', 'History ' + str(i), '2026-10-02T21:00:00Z', '2026-10-02T21:00:00Z', '{}', None) for i in range(1005)]
        rows += [('waiting-' + str(i), 'chat', 'Waiting ' + str(i), '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z', json.dumps({'hasBlockingApproval': True, 'origin': 'neyvia-harness'}), '2020-02-01T00:00:00Z' if i == 32 else None) for i in range(33)]
        connection.executemany('INSERT INTO conversations (conversation_id,kind,title,created_at,updated_at,last_meaningful_activity_at,metadata_json,archived_at) VALUES (?,?,?,?,?,?,?,?)', [row[:5] + (row[4],) + row[5:] for row in rows])
        connection.commit()
    backend = SimpleNamespace(root=folder, neyvia_mcp=SimpleNamespace(conversations=store), dispatch=lambda *args: {})
    adapter = NeyviaAdapter(backend)
    ordinary = adapter.list_sessions(include_archived=True)
    active = adapter.running_sessions()
    receipt['checks']['activeBeyondHistoryCap'] = len(ordinary) == 1000 and len(active) == 33
    broker = ConnectedBroker(folder, backend=backend, adapters={'neyvia': adapter}, autostart=False)
    pages = []
    offset = 0
    while True:
        page = build(broker, limit=16, offset=offset)
        pages.append({'offset': page['offset'], 'count': len(page['sessions']), 'total': page['total'], 'nextOffset': page['nextOffset'], 'ids': [r['id'] for r in page['sessions']]})
        if page['nextOffset'] is None:
            break
        offset = page['nextOffset']
    ids = [sid for page in pages for sid in page['ids']]
    receipt['checks']['everyActiveChatReachable'] = len(ids) == len(set(ids)) == 33 and [p['count'] for p in pages] == [16, 16, 1] and all(p['total'] == 33 for p in pages)
    receipt['checks']['archivedHarnessIncluded'] = any(sid.endswith(':waiting-32') for sid in ids)
    end = build(broker, limit=200, offset=33)
    receipt['checks']['emptyAndBoundedPage'] = end['sessions'] == [] and end['nextOffset'] is None and end['limit'] == 100 and end['total'] == 33
    negative = build(broker, limit=0, offset=-4)
    receipt['checks']['lowerBounds'] = negative['limit'] == 1 and negative['offset'] == 0 and len(negative['sessions']) == 1
    class BrokenPaging:
        def list_sessions(self, **kwargs): return {'sessions': [], 'nextOffset': 0}
    try:
        build(BrokenPaging())
        receipt['checks']['nonAdvancingCursorRefused'] = False
    except ValueError as exc:
        receipt['checks']['nonAdvancingCursorRefused'] = 'did not advance' in str(exc)
    receipt['pages'] = pages
    # Production run-store ownership must outlive a native history cap or an
    # unavailable inventory. This is a persisted boundary fixture, not a model run.
    from grant_agent.connected_sessions.runs import iso
    from grant_agent.chat_run_control import process_started_at
    import os
    sid = 'external:opencode:' + broker.host['deviceId'] + ':outside-native-history'
    data = {'runId': 't9-owned-fixture', 'sessionId': sid, 'app': 'opencode', 'state': 'waiting_approval',
            'startedAt': iso(time.time()), 'updatedAt': iso(time.time()), 'model': 'fixture-only',
            'pendingRequest': None, 'error': None}
    broker.store.claim(data, 't9-fixture', process_started_at(os.getpid()), is_free=lambda other: False,
                       register=lambda: broker._live.update({data['runId']: SimpleNamespace(data=data, terminal=False)}),
                       unregister=lambda: broker._live.pop(data['runId'], None))
    broker.store.save(data)
    owned_page = build(broker, limit=100)
    receipt['checks']['persistedOwnerOutsideNativeInventory'] = owned_page['total'] == 34 and any(
        row['id'] == sid and row['status'] == 'waiting_approval' for row in owned_page['sessions'])
    receipt['boundaries'].append('Persisted active-owner fixture: authoritative run state remains visible outside native inventory; no model run claimed')
    broker._live.clear()
    broker.recover()
    codex = CodexAdapter()
    live = codex.running_sessions()
    receipt['liveCodex'] = {'count': len(live), 'ids': [row.id for row in live], 'statuses': [row.status for row in live], 'owners': [row.live_owner for row in live]}
    recent = {codex._sid(str(row['id'])) for row in codex._list_threads(archived=False, cap=30)}
    receipt['liveCodex']['outsideRecentWindow'] = [row.id for row in live if row.id not in recent]
    receipt['checks']['realCodexWriterObserved'] = bool(live) and all(row.status in ('working','waiting_approval','waiting_input') for row in live)
    receipt['checks']['realWriterBeyondOldThirtyLimit'] = bool(receipt['liveCodex']['outsideRecentWindow'])
    live_broker = ConnectedBroker(folder / 'live', adapters={'codex': codex}, autostart=False)
    live_pages = []
    offset = 0
    while True:
        page = build(live_broker, limit=16, offset=offset)
        live_pages.append({'offset': page['offset'], 'total': page['total'], 'nextOffset': page['nextOffset'],
                           'ids': [row['id'] for row in page['sessions']],
                           'readErrors': [row['error'] for row in page['sessions'] if row.get('error')]})
        if page['nextOffset'] is None:
            break
        offset = page['nextOffset']
    receipt['liveDashboardPages'] = live_pages
    reachable = [sid for page in live_pages for sid in page['ids']]
    receipt['checks']['realDashboardOverflow'] = len(live_pages) > 1 and len(set(reachable)) == len(reachable) and set(receipt['liveCodex']['ids']).issubset(reachable)
except Exception as exc:
    receipt['blocker'] = {'code': getattr(exc, 'code', type(exc).__name__), 'message': str(exc)[:600]}
finally:
    if broker: broker.close()
    if live_broker: live_broker.close()
    if codex: codex.close()
    receipt['elapsedSeconds'] = round(time.monotonic() - started, 3)
    receipt['ok'] = bool(receipt['checks']) and all(receipt['checks'].values()) and 'blocker' not in receipt
    destination = Path('scripts/evidence/T9-dashboard.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'ok': receipt['ok'], 'checks': receipt['checks'], 'blocker': receipt.get('blocker'), 'liveCodexCount': receipt.get('liveCodex', {}).get('count'), 'receipt': str(destination)}), flush=True)
raise SystemExit(0 if receipt['ok'] else 1)
`;
const child = spawn(python, ['-u', '-c', source], {
  cwd: resolve(__dirname, '..'), env: { ...process.env, PYTHONPATH: resolve(__dirname, '../src') },
  windowsHide: true, stdio: ['ignore', 'inherit', 'inherit'],
});
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
