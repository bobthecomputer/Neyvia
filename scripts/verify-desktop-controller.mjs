import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const root = mkdtempSync(join(tmpdir(), 'neyvia-desktop-controller-'));
const python = process.env.PYTHON || 'python';
const program = String.raw`import hashlib, json, os, pathlib, sys, threading, time
from grant_agent import desktop_controller as dc
root = pathlib.Path(sys.argv[1])
assert dc._request_wait_timeout_seconds('send_agent_chat_command', {}) is None
assert dc._request_wait_timeout_seconds('send_agent_chat_command', {'runtimeTimeoutSeconds': 15}) == 135
assert dc._request_wait_timeout_seconds('send_agent_chat_command', {'runtime_timeout_seconds': 7200}) == 7320
assert dc._request_wait_timeout_seconds('get_agent_prompt_library_command', {}) == 3600
identity = dc._identity_for_test(root, 4321, 'creation-1')
out = {'initialOffline': dc._controller_status_for_test(root)['online'] is False}
def desktop_once(expected_count=1):
    found = []
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline and len(found) < expected_count:
        answer = dc._poll_with_identity(root, {}, identity, poll_seconds=0.02)
        for request in answer['requests']:
            found.append(request)
            dc._complete_with_identity(root, {
                'sessionId': answer['sessionId'], 'requestId': request['requestId'],
                'ok': True, 'data': {'handledBy':'running-desktop', 'echo':request['payload']}
            }, identity)
    return found
runner = threading.Thread(target=desktop_once, daemon=True)
runner.start()
for _ in range(80):
    if dc._controller_status_for_test(root)['online']:
        break
    time.sleep(0.01)
out['online'] = dc._controller_status_for_test(root)['online']
root_alias = pathlib.Path('\\\\?\\' + str(root)) if os.name == 'nt' else root
out['rootAliasesMatch'] = dc._canonical_root(root_alias) == dc._canonical_root(root)
out['deadProcessOffline'] = dc._controller_status(root, lambda _pid, _created: False)['online'] is False
try:
    dc._submit_controller_request(root, 'send_agent_chat_command', {}, 'verify-dead-host-01', lambda _pid, _created: False)
    out['deadProcessAdmissionError'] = None
except Exception as exc:
    out['deadProcessAdmissionError'] = type(exc).__name__
payload = {'text':'hello', 'summary':{'tokenBudget':256, 'maxTokens':1000, 'providerSecretPresence':{'openai':True, 'other':False}}}
out['result'] = dc._submit_for_test(root, 'send_agent_chat_command', payload, 'verify-req-0001')
out['replay'] = dc._submit_for_test(root, 'send_agent_chat_command', payload, 'verify-req-0001')
try:
    dc._submit_for_test(root, 'send_agent_chat_command', {'text':'different'}, 'verify-req-0001')
    out['changedReplayError'] = None
except Exception as exc:
    out['changedReplayError'] = type(exc).__name__
try:
    dc._submit_for_test(root, 'start_provider_auth_queue_command', {}, 'verify-req-0002')
    out['providerAuthError'] = None
except Exception as exc:
    out['providerAuthError'] = type(exc).__name__
try:
    dc._submit_for_test(root, 'send_agent_chat_command', {'access_token':'hidden'}, 'verify-req-0004')
    out['credentialPayloadError'] = None
except Exception as exc:
    out['credentialPayloadError'] = type(exc).__name__
out['sensitivePresenceKeys'] = dc._contains_sensitive_keys({'providerSecretPresence':{'openai':True}, 'tokenBudget':100, 'maxTokens':10})
out['actualSecretKey'] = dc._contains_sensitive_keys({'provider':{'access_token':'hidden'}})

# Seed completed history as a disposable state fixture: completed requests must
# not consume the 128 slots reserved for queued and claimed work.
db = dc._connect(root)
now = time.time()
for i in range(140):
    seeded_payload = {'text':'seed-%04d' % i}
    seeded_json = dc._json(seeded_payload, dc.MAX_REQUEST_BYTES, 'fixture')
    seeded_hash = hashlib.sha256(('send_agent_chat_command\n' + seeded_json).encode('utf-8')).hexdigest()
    db.execute('INSERT INTO controller_requests(root,request_id,content_hash,command,payload_json,session_id,state,created_at,updated_at,result_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
               (str(dc._canonical_root(root)), 'old-%04d' % i, seeded_hash, 'send_agent_chat_command', seeded_json, 'fixture-session', 'done', now-i, now-i, '{}'))
db.commit()
db.close()
out['historyFixtureCount'] = 140
runner2 = threading.Thread(target=desktop_once, daemon=True)
runner2.start()
out['afterHistory'] = dc._submit_for_test(root, 'send_agent_chat_command', {'text':'after history'}, 'verify-req-0005')

db = dc._connect(root)
out['terminalResultCount'] = db.execute("SELECT COUNT(*) FROM controller_requests WHERE root=? AND state IN ('done','failed') AND result_json IS NOT NULL", (str(dc._canonical_root(root)),)).fetchone()[0]
out['expiredPayloadResidueCount'] = db.execute("SELECT COUNT(*) FROM controller_requests WHERE root=? AND state='expired' AND (payload_json!='' OR result_json IS NOT NULL)", (str(dc._canonical_root(root)),)).fetchone()[0]
out['activeQueueCount'] = db.execute("SELECT COUNT(*) FROM controller_requests WHERE root=? AND state IN ('queued','claimed')", (str(dc._canonical_root(root)),)).fetchone()[0]
for state in ('queued', 'claimed'):
    db.execute('INSERT INTO controller_requests(root,request_id,content_hash,command,payload_json,session_id,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
               (str(dc._canonical_root(root)), 'duration-'+state, 'duration-hash', 'send_agent_chat_command', '{}', 'fixture-session', state, time.time()-12000, time.time()-12000))
db.execute('INSERT INTO controller_requests(root,request_id,content_hash,command,payload_json,session_id,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
           (str(dc._canonical_root(root)), 'duration-explicit', 'duration-hash', 'send_agent_chat_command', json.dumps({'runtimeTimeoutSeconds': 15}), 'fixture-session', 'claimed', time.time()-140, time.time()-140))
dc._compact_terminal_rows(db, str(dc._canonical_root(root)), time.time())
out['longRunningState'] = db.execute("SELECT state FROM controller_requests WHERE request_id='duration-claimed'").fetchone()[0]
out['abandonedQueueState'] = db.execute("SELECT state FROM controller_requests WHERE request_id='duration-queued'").fetchone()[0]
out['explicitBudgetExpiryState'] = db.execute("SELECT state FROM controller_requests WHERE request_id='duration-explicit'").fetchone()[0]
db.commit()
db.close()
try:
    dc._submit_for_test(root, 'send_agent_chat_command', {'text':'seed-0139'}, 'old-0139')
    out['expiredRetryError'] = None
except Exception as exc:
    out['expiredRetryError'] = type(exc).__name__

db = dc._connect(root)
db.execute('UPDATE controller_sessions SET updated_at=?', (time.time()-dc.DESKTOP_STALE_SECONDS-1,))
db.commit()
db.close()
out['offlineAfterExpiry'] = dc._controller_status_for_test(root)['online'] is False
try:
    dc._submit_for_test(root, 'send_agent_chat_command', {}, 'verify-req-0003')
    out['staleSubmitError'] = None
except Exception as exc:
    out['staleSubmitError'] = type(exc).__name__

# A cancellation request gets its reserved lane even when all four regular
# requests have already been claimed, and duplicate cancels remain bounded.
priority_root = root / 'priority-lane'
priority_identity = dc._identity_for_test(priority_root, 7654, 'creation-priority')
priority_session = dc._session(priority_root, priority_identity, time.time())
priority_db = dc._connect(priority_root)
priority_root_key = str(dc._canonical_root(priority_root))
priority_now = time.time()
for i in range(dc.MAX_INFLIGHT):
    priority_db.execute('INSERT INTO controller_requests(root,request_id,content_hash,command,payload_json,session_id,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
        (priority_root_key, 'busy-%02d' % i, 'busy-hash', 'send_agent_chat_command', '{}', priority_session, 'claimed', priority_now-20+i, priority_now-20+i))
priority_db.execute('INSERT INTO controller_requests(root,request_id,content_hash,command,payload_json,session_id,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
    (priority_root_key, 'queued-regular-01', 'regular-hash', 'get_agent_prompt_library_command', '{}', priority_session, 'queued', priority_now-2, priority_now-2))
for suffix, created in [('01', priority_now-1), ('02', priority_now)]:
    priority_db.execute('INSERT INTO controller_requests(root,request_id,content_hash,command,payload_json,session_id,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
        (priority_root_key, 'queued-cancel-'+suffix, 'cancel-hash-'+suffix, 'cancel_agent_chat_command', '{}', priority_session, 'queued', created, created))
priority_db.commit()
priority_db.close()
first_cancel = dc._poll_with_identity(priority_root, {}, priority_identity, poll_seconds=0.05)['requests']
out['priorityLaneFirstClaim'] = first_cancel[0]['command'] if first_cancel else None
priority_db = dc._connect(priority_root)
out['ordinaryClaimedWithReservedControl'] = priority_db.execute(
    "SELECT COUNT(*) FROM controller_requests WHERE state='claimed' AND command='send_agent_chat_command'").fetchone()[0]
priority_db.close()
blocked_second_cancel = dc._poll_with_identity(priority_root, {}, priority_identity, poll_seconds=0.02)['requests']
out['singleControlSlotHeld'] = not blocked_second_cancel
dc._complete_with_identity(priority_root, {
    'sessionId': priority_session, 'requestId': first_cancel[0]['requestId'], 'ok': True, 'data': {'cancelled': True}
}, priority_identity)
second_cancel = dc._poll_with_identity(priority_root, {}, priority_identity, poll_seconds=0.05)['requests']
out['secondCancelAfterCompletion'] = second_cancel[0]['command'] if second_cancel else None
dc._complete_with_identity(priority_root, {
    'sessionId': priority_session, 'requestId': second_cancel[0]['requestId'], 'ok': True, 'data': {'cancelled': True}
}, priority_identity)
priority_db = dc._connect(priority_root)
for i in range(dc.QUEUE_LIMIT-dc.MAX_INFLIGHT-1):
    created = time.time()
    priority_db.execute('INSERT INTO controller_requests(root,request_id,content_hash,command,payload_json,session_id,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
        (priority_root_key, 'backlog-%03d' % i, 'backlog-hash', 'get_agent_prompt_library_command', '{}', priority_session, 'queued', created, created))
priority_db.commit()
out['ordinaryQueueAtLimit'] = priority_db.execute(
    "SELECT COUNT(*) FROM controller_requests WHERE root=? AND state IN ('queued','claimed') AND command<>?",
    (priority_root_key, dc._PRIORITY_CONTROL_COMMAND)).fetchone()[0]
priority_db.close()
def priority_desktop_once():
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        answer = dc._poll_with_identity(priority_root, {}, priority_identity, poll_seconds=0.02)
        for request in answer['requests']:
            if request['command'] == dc._PRIORITY_CONTROL_COMMAND:
                dc._complete_with_identity(priority_root, {
                    'sessionId': answer['sessionId'], 'requestId': request['requestId'],
                    'ok': True, 'data': {'cancelled': True}
                }, priority_identity)
                return
priority_runner = threading.Thread(target=priority_desktop_once, daemon=True)
priority_runner.start()
out['cancelAtOrdinaryQueueLimit'] = dc._submit_for_test(
    priority_root, 'cancel_agent_chat_command', {'conversationId':'stop-at-capacity'}, 'cancel-at-capacity-001')
priority_runner.join(timeout=1)
print(json.dumps(out, separators=(',',':')))
`;

try {
  const result = spawnSync(python, ['-c', program, root], {
    encoding: 'utf8',
    env: { ...process.env, PYTHONPATH: ['src', process.env.PYTHONPATH].filter(Boolean).join(';') },
    timeout: 30000,
  });
  assert.equal(result.status, 0, `Queue probe failed (${result.status})\n${result.stdout}\n${result.stderr}`);
  const probe = JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1));
  assert.equal(probe.initialOffline, true);
  assert.equal(probe.online, true);
  assert.equal(probe.rootAliasesMatch, true);
  assert.equal(probe.deadProcessOffline, true);
  assert.equal(probe.deadProcessAdmissionError, 'RuntimeError');
  assert.deepEqual(probe.result, { handledBy: 'running-desktop', echo: {
    text: 'hello', summary: { tokenBudget: 256, maxTokens: 1000, providerSecretPresence: { openai: true, other: false } },
  } });
  assert.deepEqual(probe.replay, probe.result);
  assert.equal(probe.changedReplayError, 'ValueError');
  assert.equal(probe.providerAuthError, 'ValueError');
  assert.equal(probe.credentialPayloadError, 'ValueError');
  assert.equal(probe.sensitivePresenceKeys, false);
  assert.equal(probe.actualSecretKey, true);
  assert.equal(probe.historyFixtureCount, 140);
  assert.deepEqual(probe.afterHistory, { handledBy: 'running-desktop', echo: { text: 'after history' } });
  assert.ok(probe.terminalResultCount <= 64);
  assert.equal(probe.expiredPayloadResidueCount, 0);
  assert.equal(probe.activeQueueCount, 0);
  assert.equal(probe.longRunningState,'claimed');
  assert.equal(probe.abandonedQueueState,'expired');
  assert.equal(probe.explicitBudgetExpiryState,'expired');
  assert.equal(probe.expiredRetryError, 'RuntimeError');
  assert.equal(probe.offlineAfterExpiry, true);
  assert.equal(probe.staleSubmitError, 'RuntimeError');
  assert.equal(probe.priorityLaneFirstClaim, 'cancel_agent_chat_command');
  assert.equal(probe.ordinaryClaimedWithReservedControl, 4);
  assert.equal(probe.singleControlSlotHeld, true);
  assert.equal(probe.secondCancelAfterCompletion, 'cancel_agent_chat_command');
  assert.equal(probe.ordinaryQueueAtLimit, 128);
  assert.deepEqual(probe.cancelAtOrdinaryQueueLimit, { cancelled: true });
  process.stdout.write('desktop controller queue verification passed\n');
} finally {
  rmSync(root, { recursive: true, force: true });
}
