import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = mkdtempSync(path.join(tmpdir(), 'neyvia-chat-stop-'));
const code = String.raw`
import json, os, subprocess, sys, threading, time
from pathlib import Path
from unittest.mock import patch
root=Path(sys.argv[1])
os.environ['FLUXIO_AGENT_CHAT_RUNTIME_TIMEOUT_SECONDS']='15'
os.environ['FLUXIO_AGENT_CHAT_RUNTIME_TIMEOUT_MAX_SECONDS']='30'
from grant_agent.web_backend import _agent_chat_runtime_timeout_seconds, _run_process_capture
from grant_agent.chat_run_control import active_chat_run, request_chat_cancellation
assert _agent_chat_runtime_timeout_seconds({}) is None
assert _agent_chat_runtime_timeout_seconds({'runtimeTimeoutSeconds': 4000000})==4000000
ordinary, *_ = _run_process_capture([sys.executable, '-c', "import json;print(json.dumps({'output':'complete'}))"], cwd=root, timeout=None)
assert ordinary['output']=='complete'
turn='stop_fixture_turn'
outcome={}
def run():
    try:
        with active_chat_run(root, turn):
            _run_process_capture([sys.executable, '-c', 'import time;time.sleep(30)'], cwd=root, timeout=None)
    except Exception as exc:
        outcome['type']=type(exc).__name__
        outcome['message']=str(exc)
        outcome['recovery']=getattr(exc,'recovery',{})
thread=threading.Thread(target=run,daemon=True)
thread.start()
state=root/'.agent_control'/'chat_runs'/(turn+'.json')
until=time.monotonic()+5
while time.monotonic()<until:
    try:
        current=json.loads(state.read_text(encoding='utf8'))
        if current.get('state')=='running': break
    except FileNotFoundError: pass
    time.sleep(.025)
else: raise AssertionError('active chat registration did not appear')
requested=request_chat_cancellation(root,turn)
assert requested['status']=='stop_requested', requested
thread.join(timeout=12)
assert not thread.is_alive(), 'cancel did not end the owned process wait'
assert outcome.get('type')=='ChatRunCancelled', outcome
assert outcome.get('message')=='Stopped by you.', outcome
assert outcome['recovery'].get('processTreeStopped') is True, outcome
assert outcome['recovery'].get('processReaped') is True, outcome
final=json.loads(state.read_text(encoding='utf8'))
assert final['state']=='cancelled', final
from grant_agent.web_backend import FluxioWebBackend
from grant_agent.chat_run_control import ChatRunCancelled
backend_root=root/'persisted-cancel';backend_root.mkdir()
backend=FluxioWebBackend(backend_root,backend_root)
failure=ChatRunCancelled();failure.process_tree_stopped=True;failure.process_reaped=True;failure.process_id=123;failure.elapsed_ms=7
backend._run_openclaw_chat=lambda _payload: (_ for _ in ()).throw(failure)
backend._run_codex_chat=lambda _payload: (_ for _ in ()).throw(AssertionError('cancel attempted provider fallback'))
payload={'runtime':'openclaw','runtimeId':'openclaw','_allowMutation':True,'message':'cancel fixture','workspacePath':str(backend_root),'route':{'provider':'openai-codex','model':'gpt-fixture'},'allowRuntimeFallback':True,'conversationId':'cancel_fixture_conversation','userTurnId':'cancel_fixture_user','assistantTurnId':'cancel_fixture_assistant'}
with patch('grant_agent.web_backend._codex_cli_login_status',return_value={'authenticated':True}) as login:
    try: backend._run_agent_chat(payload,allow_mutation=True)
    except ChatRunCancelled as exc:
        saved=exc.cancelled_result
    else: raise AssertionError('cancel did not escape provider dispatch')
    assert not login.called, 'cancel attempted provider fallback discovery'
assert saved['status']=='cancelled'
replay=backend._agent_chat_replay(('cancel_fixture_conversation','cancel_fixture_user','cancel_fixture_assistant'))
assert replay['status']=='cancelled' and replay['reply']=='Stopped by you.', replay
print(json.dumps({'ok':True,'checks':['legacy_env_does_not_impose_total_deadline','ordinary_unlimited_process_completes','cancel_signal_stops_owned_process_tree','owner_process_reaped','active_run_records_cancelled','cancelled_reply_persisted_and_replayable','cancellation_never_falls_back_to_another_provider']}))
`;
try {
  const result = spawnSync(resolveNeyviaPython(repo).python, ['-c', code, fixture], {
    cwd: repo,
    env: { ...process.env, PYTHONPATH: path.join(repo, 'src') },
    encoding: 'utf8',
    timeout: 20000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  console.log(result.stdout.trim());
} finally {
  rmSync(fixture, { recursive: true, force: true });
}
