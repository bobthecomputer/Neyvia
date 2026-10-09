import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

// Disposable protocol fixtures exercise real owned process lifecycles, never a
// signed-in harness or the host speech service. All HTTP calls use owned ports.
const repo = process.cwd();
const root = path.join(repo, '.agent_control/FOLLOW/local-only');
mkdirSync(root, { recursive: true });
const python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
writeFileSync(path.join(root, 'codex-fixture.py'), String.raw`
import json,sys,time
from pathlib import Path
root=Path(sys.argv[1])
for line in sys.stdin:
    request=json.loads(line)
    if 'id' not in request:continue
    method=request.get('method')
    if method=='proof/hold':
        (root/'rpc-working').write_text('working')
        while not (root/'rpc-release').exists():time.sleep(.03)
    answer={'data':[]} if method in ('thread/list','thread/loaded/list') else {}
    print(json.dumps({'id':request['id'],'result':answer}),flush=True)
`);
writeFileSync(path.join(root, 'phonon2_engine.py'), String.raw`
import json,os,time,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
root=Path(__file__).parent
class H(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):self.answer({'state':'ready','pid':os.getpid()})
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length','0')))
        (root/'audio-working').write_text('working')
        while not (root/'audio-release').exists():time.sleep(.03)
        self.answer({'ok':True,'text':'hello fixture','engine':'phonon2'})
    def answer(self,value):
        body=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
port=int(sys.argv[sys.argv.index('--port')+1]);ThreadingHTTPServer(('127.0.0.1',port),H).serve_forever()
`);
const bootstrap = String.raw`
import json,os,sys,time,threading,subprocess
from pathlib import Path
from http.server import ThreadingHTTPServer
from grant_agent.web_backend import FluxioWebBackend,make_handler,SESSION_COOKIE_NAME
from grant_agent.connected_sessions.codex import CodexAdapter
from grant_agent.connected_sessions.broker import ConnectedBroker,_BROKERS
from grant_agent.local_network_policy import install,stop_child
from grant_agent import neyvia_dictation as d
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
for name in ['rpc-working','rpc-release','audio-working','audio-release']:(root/name).unlink(missing_ok=True)
backend=FluxioWebBackend(root,root);backend.sessions['follow-proof']={'username':backend.username,'role':'admin'}
session=backend.web_auth_sessions.issue({'username':backend.username,'role':'admin'})
install(root)
observed=backend.dispatch('settings_get_command',{})
if observed['settings']['localOnly']:
    backend.dispatch('settings_update_command',{'expectedRevision':observed['revision'],'patch':{'localOnly':False}})
adapter=CodexAdapter(state_root=root,command=[sys.executable,'-u',str(root/'codex-fixture.py'),str(root)])
broker=ConnectedBroker(root,backend=backend,adapters={'codex':adapter},load_defaults=False,live_poll_seconds=.1)
_BROKERS[os.path.normcase(str(root.resolve()))]=broker
adapter._conn.ensure_started()
d.write_settings(root,{'engineDir':str(root),'python':sys.executable,'port':48442,'qwenFallback':False})
d._spawn(root,root,Path(sys.executable),d.read_settings(root))
deadline=time.monotonic()+10
while not d._get('http://127.0.0.1:48442/v1/health'):
    if time.monotonic()>deadline:raise RuntimeError('fixture engine did not start')
broker._subscribers.add('proof-listener');broker._ensure_thread();unknown=None
Base=make_handler(backend)
class Handler(Base):
    def do_POST(self):
        global unknown
        if self.path!='/fixture':return super().do_POST()
        value=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));op=value['op']
        if op=='rpc_hold':threading.Thread(target=lambda:adapter._conn.request('proof/hold',timeout=15),daemon=True).start()
        elif op=='rpc_release':(root/'rpc-release').write_text('release')
        elif op=='audio_release':(root/'audio-release').write_text('release')
        elif op=='unknown_start':unknown=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])
        elif op=='unknown_stop':stop_child(unknown)
        elif op=='restart':adapter._conn.ensure_started()
        elif op=='poll':
            for i in range(100):broker.poll_live_status()
        elif op=='rpc_refusal':
            try:adapter._conn.ensure_started();answer={'unexpectedStart':True}
            except Exception as exc:answer={'code':getattr(exc,'code',None),'message':str(exc)}
        if op!='rpc_refusal':answer={'generation':adapter._conn.generation,'pid':adapter._conn._process.pid if adapter._conn._process else None,
           'rpcWorking':(root/'rpc-working').exists(),'rpcPending':bool(adapter._conn._pending),
           'audioWorking':(root/'audio-working').exists(),'unknownAlive':unknown is not None and unknown.poll() is None}
        body=json.dumps(answer).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',48446),Handler)
print('READY '+SESSION_COOKIE_NAME+'='+session,flush=True)
try:server.serve_forever()
finally:
    broker.close()
    if unknown is not None:stop_child(unknown)
`;
const child = spawn(python, ['-u', '-c', bootstrap, root], {
  cwd: repo, env: { ...process.env, PYTHONPATH: path.join(repo, 'src'), CODEX_HOME: path.join(root, 'codex-home'), NEYVIA_UI_STATE_ROOT: root,
    NEYVIA_TOOL_AUTO_UPDATE: '0', NEYVIA_COORDINATOR_AUTOSTART: '0', FLUXIO_WATCHDOG_AUTOSTART: '0' },
  stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
});
let errors = ''; child.stderr.on('data', data => { errors += data; });
let cookie = '';
const closed = new Promise(resolve => child.once('exit', resolve));
const receipt = { scope: 'T11 owned backend on 48446, disposable Codex protocol child and speech child on 48442; no host services', checks: {} };
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function post(route, body) {
  const response = await fetch(`http://127.0.0.1:48446${route}`, { method: 'POST',
    headers: { 'Content-Type': 'application/json', Cookie: cookie }, body: JSON.stringify(body) });
  return { status: response.status, body: await response.json() };
}
const invoke = (command, payload = {}) => post('/api/backend', { command, payload });
const fixture = async op => (await post('/fixture', { op })).body;
async function until(field) { for (let i = 0; i < 150; i++) { if ((await fixture('inspect'))[field]) return; await wait(30); } throw Error(field); }
try {
  await new Promise((resolve, reject) => {
    let output = ''; child.stdout.on('data', data => { output += data; const ready = output.match(/READY ([^\r\n]+)/); if (ready) { cookie = ready[1]; resolve(); } });
    child.once('exit', () => reject(Error(errors))); setTimeout(() => reject(Error('Backend readiness timeout '+errors)), 30000).unref();
  });
  const initialCall = await invoke('settings_get_command');
  assert.equal(initialCall.body.ok, true, JSON.stringify(initialCall));
  const initial = initialCall.body.data;
  assert.equal(initial.network.activeChildren, 2, JSON.stringify(initial));
  await fixture('rpc_hold'); await until('rpcPending');
  const active = await invoke('settings_update_command', { expectedRevision: initial.revision, patch: { localOnly: true } });
  assert.equal(active.status, 409, JSON.stringify(active));
  assert.match(active.body.error, /working/);
  receipt.checks.activeRpcRetained = active;
  await fixture('rpc_release');
  while ((await fixture('inspect')).rpcPending) await wait(30);
  const audioCall = invoke('dictation_transcribe_command', { pcm: 'AAA=', history: [] });
  await until('audioWorking');
  const audioBusy = await invoke('settings_update_command', { expectedRevision: initial.revision, patch: { localOnly: true } });
  assert.equal(audioBusy.status, 409, JSON.stringify(audioBusy)); receipt.checks.activeDictationRetained = audioBusy;
  await fixture('audio_release'); assert.equal((await audioCall).body.ok, true);
  await fixture('unknown_start');
  const unknown = await invoke('settings_update_command', { expectedRevision: initial.revision, patch: { localOnly: true } });
  assert.equal(unknown.status, 409); assert.equal((await fixture('inspect')).unknownAlive, true);
  receipt.checks.unknownJobRetained = unknown; await fixture('unknown_stop');
  const enabled = await invoke('settings_update_command', { expectedRevision: initial.revision, patch: { localOnly: true } });
  assert.equal(enabled.body.ok, true, JSON.stringify(enabled)); assert.equal(enabled.body.data.network.activeChildren, 0);
  receipt.checks.idleOwnedChildrenStopped = enabled;
  const baseline = enabled.body.data.network.blockedAttempts;
  const generation = (await fixture('poll')).generation; await wait(3200); await fixture('poll');
  const later = (await invoke('settings_get_command')).body.data;
  assert.equal(later.network.blockedAttempts, baseline); assert.equal((await fixture('inspect')).generation, generation);
  receipt.checks.noBackgroundRetries = { polls: 200, watchedMs: 3200, blockedBefore: baseline, blockedAfter: later.network.blockedAttempts, generation };
  const refused = await fixture('rpc_refusal'); assert.equal(refused.code, 'local_only'); assert.match(refused.message, /Local-only is on/);
  receipt.checks.exactPolicyMessage = refused;
  const network = await invoke('settings_network_check_command'); assert.equal(network.body.data.ok, true, JSON.stringify(network));
  receipt.checks.realEgressRefusals = network;
  const disabled = await invoke('settings_update_command', { expectedRevision: enabled.body.data.revision, patch: { localOnly: false } });
  assert.equal(disabled.body.ok, true); assert.ok((await fixture('restart')).generation > generation);
  receipt.checks.restartAfterDisable = true;
  const final = await invoke('settings_update_command', { expectedRevision: disabled.body.data.revision, patch: { localOnly: true } });
  assert.equal(final.body.ok, true); assert.equal(final.body.data.network.activeChildren, 0);
  receipt.ok = true;
  mkdirSync(path.join(repo, 'scripts/evidence'), { recursive: true });
  writeFileSync(path.join(repo, 'scripts/evidence/FOLLOW-local-only.json'), JSON.stringify(receipt, null, 2)+'\n');
  console.log(JSON.stringify({ ok: true, checks: Object.keys(receipt.checks) }));
} finally {
  // Terminate only descendants of the backend PID we just spawned, before the
  // parent exits; no name-based or global process cleanup.
  spawnSync(python, ['-c', 'import psutil,sys\ntry:\n p=psutil.Process(int(sys.argv[1]))\n for c in reversed(p.children(recursive=True)):\n  try:c.kill()\n  except psutil.NoSuchProcess:pass\nexcept psutil.NoSuchProcess:pass', String(child.pid)], { windowsHide: true });
  child.kill(); await closed;
  if (!receipt.ok) console.error(errors.slice(-3000));
}

