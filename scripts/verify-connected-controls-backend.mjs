import assert from 'node:assert/strict';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const repo = path.resolve(import.meta.dirname, '..');
const { python } = resolveNeyviaPython(repo);
const temp = mkdtempSync(path.join(tmpdir(), 'neyvia-connected-controls-'));
const source = String.raw`
import json, os, sqlite3, sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'src'))
from grant_agent.connected_app_chats import ConnectedAppChats
from grant_agent.connected_codex_chats import _server_request_result

root = Path(sys.argv[1])
manager = ConnectedAppChats(root)
chat = 'external:codex:fixture-device:fixture-thread'

def make_run(run_id):
    data = {'runId': run_id, 'chatId': chat, 'app': 'codex', 'canCancel': True,
            'state': 'running', 'reply': '', 'events': [], 'error': '', 'pendingRequest': None}
    with manager.connect() as db:
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',
                   (run_id, chat, 'fixture-fingerprint-' + run_id, 'running', os.getpid(), time.time(), json.dumps(data)))
    return data

def wait_pending(run_id):
    for _ in range(100):
        current = manager.latest(chat)
        pending = current.get('pendingRequest') if current and current.get('runId') == run_id else None
        if pending:
            return pending
        time.sleep(0.02)
    raise AssertionError('pending request was not exposed for refresh')

approval_id = 'approval-run-0001'
approval_data = make_run(approval_id)
command_event = {'method': 'item/commandExecution/requestApproval', 'serverRequestId': 71,
    'params': {'threadId': 'fixture-thread', 'itemId': 'item-1', 'command': 'echo safe',
               'cwd': 'C:/fixture', 'availableDecisions': ['accept', 'decline']}}
approval_result = []
worker = threading.Thread(name=manager._thread_name(approval_id),
    target=lambda: approval_result.append(manager._await_request(approval_id, approval_data, command_event)))
worker.start()
pending = wait_pending(approval_id)
assert pending['kind'] == 'approval' and pending['choices'] == ['approve', 'deny']
assert pending['command'] == 'echo safe' and pending['expiresAt'] > time.time()
assert manager.latest(chat)['pendingRequest']['id'] == pending['id']
manager.answer(approval_id, pending['id'], {'decision': 'approve'})
worker.join(3)
assert not worker.is_alive() and approval_result[0]['decision'] == 'approve'
assert manager.get(approval_id)['pendingRequest'] is None
try:
    manager.answer(approval_id, pending['id'], {'decision': 'deny'})
except ValueError:
    pass
else:
    raise AssertionError('stale request response was accepted')

assert manager.latest('external:codex:missing:chat') is None
assert _server_request_result('item/commandExecution/requestApproval', {}, {'decision':'approve'}) == {'decision':'accept'}
assert _server_request_result('item/fileChange/requestApproval', {}, {'decision':'deny'}) == {'decision':'decline'}
permission = {'fileSystem': {'write': ['C:/fixture']}, 'network': None}
assert manager._public_request('item/permissions/requestApproval', {'permissions': permission})['choices'] == ['approve','deny']
assert _server_request_result('item/permissions/requestApproval', {'permissions':permission}, {'decision':'approve'}) == {
    'permissions': permission, 'scope':'turn', 'strictAutoReview':None}
assert _server_request_result('item/permissions/requestApproval', {'permissions':permission}, {'decision':'deny'}) == {
    'permissions': {'fileSystem':None,'network':None}, 'scope':'turn', 'strictAutoReview':None}
assert _server_request_result('item/tool/requestUserInput', {'questions':[{'id':'q1'}]},
    {'decision':'approve','answers':{'q1':'hello'}}) == {'answers':{'q1':{'answers':['hello']}}}
assert _server_request_result('mcpServer/elicitation/request', {}, {'decision':'approve','answers':{'name':'Ada'}}) == {
    'action':'accept','content':{'name':'Ada'}}

cancel_id = 'cancel-run-0002'
cancel_data = make_run(cancel_id)
input_event = {'method':'item/tool/requestUserInput','serverRequestId':'server-q2',
    'params':{'threadId':'fixture-thread','itemId':'item-2','isBlocking':True,'questions':[{'id':'q2','header':'Next','question':'Continue?'}]}}
cancel_result = []
cancel_worker = threading.Thread(name=manager._thread_name(cancel_id),
    target=lambda: cancel_result.append(manager._await_request(cancel_id, cancel_data, input_event)))
cancel_worker.start()
cancel_pending = wait_pending(cancel_id)
manager.cancel(cancel_id)
cancel_worker.join(3)
assert not cancel_worker.is_alive() and cancel_result[0]['decision'] == 'cancel'
print(json.dumps({'status':'passed','latestRecovery':True,'approvalRoundTrip':True,
    'staleDecisionRejected':True,'permissionScope':'turn','cancelWokePendingRun':True}))
`;
try {
  const result = spawnSync(python, ['-c', source, temp], {
    cwd: repo,
    env: { ...process.env, PYTHONPATH: path.join(repo, 'src') },
    encoding: 'utf8',
    timeout: 20_000,
  });
  assert.equal(result.status, 0, result.stderr || 'connected controls backend verification failed');
  const report = JSON.parse(result.stdout.trim());
  assert.equal(report.status, 'passed');
  console.log(JSON.stringify(report));
} finally {
  rmSync(temp, { recursive: true, force: true });
}
