// Production HTTP/native/manual/desktop calls in disposable state; no provider, global install or network downloads.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';

const repo = resolve(import.meta.dirname, '..');
const port = Number(process.argv[2]);
if (![48667, 48668].includes(port)) throw Error('Supply explicit owned port 48667 or 48668');
const python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const root = resolve(repo, '.agent_control/proofs', `FIX-followups-${Date.now()}`);
mkdirSync(root, { recursive: true });
writeFileSync(resolve(root, 'evidence.txt'), 'Real task completion evidence.\n');
const bootstrap = String.raw`
import json,sys,threading,os
from pathlib import Path
from http.server import ThreadingHTTPServer
root=Path(sys.argv[1]);port=int(sys.argv[2])
from grant_agent.proof_credential_guard import install,prepare_broker_fixture
install(root)
if not (root/'config/neyvia_secret_broker.json').exists():prepare_broker_fixture(root)
from grant_agent.web_backend import FluxioWebBackend,make_handler,SESSION_COOKIE_NAME,_json_response
from grant_agent.runtime_auto_update import update_user_global_clis
from grant_agent.ui_command_bus import bus_for
from grant_agent.nightshift import nightshift_for
backend=FluxioWebBackend(root,root)
session=backend.web_auth_sessions.issue({'username':backend.username,'role':'admin'})
counts={'socket.connect':0,'subprocess.Popen':0};active=False
def audit(event,args):
    if active and event in counts:counts[event]+=1
sys.addaudithook(audit)
Base=make_handler(backend)
class Handler(Base):
    def do_POST(self):
        global active
        if self.path=='/fixture/update':
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            active=True
            try:result=update_user_global_clis(root)
            finally:active=False
            _json_response(self,200,{'ok':True,'data':{'receipt':result,'attempts':dict(counts),'activity':bus_for(root).get('tool.update.last')}});return
        if self.path=='/fixture/attempt':
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            service=nightshift_for(root,backend)
            with service.connect() as db:
                db.execute("INSERT INTO attempts(run_id,task) VALUES(?,?)",('controlled-attempt',body['id']))
            _json_response(self,200,{'ok':True});return
        if self.path=='/fixture/desktop':
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            from grant_agent.desktop_bridge import dispatch_desktop_command
            result=dispatch_desktop_command(root,body['command'],body['payload'])
            _json_response(self,200,{'ok':True,'data':result});return
        if self.path=='/fixture/stop':
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            _json_response(self,200,{'ok':True})
            threading.Thread(target=server.shutdown,daemon=True).start();return
        super().do_POST()
server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
print('READY '+SESSION_COOKIE_NAME+'='+session,flush=True)
try:server.serve_forever(poll_interval=.1)
finally:
    server.server_close()
    from grant_agent.nightshift import _services
    for service in list(_services.values()):service.close()
    from grant_agent.connected_sessions.broker import _BROKERS
    for broker in list(_BROKERS.values()):broker.close()
`;
const host = resolve(root, 'host.py'); writeFileSync(host, bootstrap);
const env = { ...process.env, PYTHONPATH: resolve(repo, 'src'), NEYVIA_COORDINATOR_AUTOSTART: '0',
  FLUXIO_WATCHDOG_AUTOSTART: '0', NEYVIA_TOOL_AUTO_UPDATE: '0', FLUXIO_LOCAL_SESSION_BOOTSTRAP: '1',
  NEYVIA_CONNECTED_SERVICE_PORT: String(port), NEYVIA_WEB_PORT: String(port), NEYVIA_UI_STATE_ROOT: root,
  NEYVIA_UI_BACKEND_URL: `http://127.0.0.1:${port}` };
const receipt = { schema: 'neyvia.FIX.followups.v1', startedAt: new Date().toISOString(), root, port, checks: [],
  boundary: 'Real production commands, tools, independent observers, SQLite durability, owner Settings and updater refusal; no global installation or real provider execution.',
  limitations: ['No board edit controls or Settings update-policy dropdown are claimed.', 'Recorded-attempt guard uses a controlled durable attempt entry, not a claimed live provider run.'] };
let server, cookie, logs = '';
const output = resolve(repo, 'scripts/evidence/FIX-followups.json');
const wait = ms => new Promise(r => setTimeout(r, ms));
async function request(route, body, auth = true) {
  const response = await fetch(`http://127.0.0.1:${port}${route}`, { method: body === undefined ? 'GET' : 'POST',
    headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(auth ? { Cookie: cookie } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(60000) });
  return { status: response.status, ...(await response.json()) };
}
async function cmd(command, payload = {}) {
  const response = await request('/api/backend', { command, payload });
  assert.equal(response.ok, true, JSON.stringify(response)); return response.data;
}
async function tool(name, args) {
  const response = await request('/api/ui/tools/call', { tool: `neyvia.${name}`, arguments: args });
  assert.equal(response.ok, true, JSON.stringify(response)); const result = response.data.result ?? response.data;
  assert.notEqual(result.ok, false, JSON.stringify(result)); return result;
}
function check(name, observed) { receipt.checks.push({ name, passed: true, observed }); console.log('PASS', name); }
async function start() {
  server = spawn(python, ['-u', host, root, String(port)], { cwd: repo, env, windowsHide: true });
  let stdout = ''; server.stdout.on('data', chunk => { stdout += chunk; logs += chunk; }); server.stderr.on('data', chunk => { logs += chunk; });
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw Error(`Backend exited ${server.exitCode}: ${logs}`);
    const found = stdout.match(/READY ([^\r\n]+)/); if (found) { cookie = found[1]; return; } await wait(200);
  }
  throw Error('Owned backend startup timed out: ' + logs);
}
async function stop() {
  if (!server || server.exitCode !== null) return;
  await request('/fixture/stop', {});
  for (let i = 0; i < 100 && server.exitCode === null; i++) await wait(100);
  if (server.exitCode === null) throw Error('Owned backend graceful cleanup deadline exceeded');
  assert.equal(server.exitCode, 0, logs);
}
try {
  await start();
  const initial = await cmd('settings_get_command'); assert.equal(initial.settings.toolAutoUpdate, 'ask'); check('Default owner update policy asks', initial.settings.toolAutoUpdate);
  const denied = await request('/fixture/update', {}); assert.equal(denied.data.receipt.status, 'blocked'); assert.equal(denied.data.attempts['socket.connect'], 0); assert.equal(denied.data.attempts['subprocess.Popen'], 0); check('Real updater refused before network or children', denied.data);
  const enabled = await cmd('settings_update_command', { expectedRevision: initial.revision, patch: { toolAutoUpdate: 'allow' } }); assert.equal(enabled.settings.toolAutoUpdate, 'allow');
  const scratch = await request('/fixture/update', {}); assert.equal(scratch.data.receipt.reason, 'development_or_scratch_root'); assert.deepEqual(scratch.data.attempts, denied.data.attempts); check('Owner allow cannot update from scratch', scratch.data);
  const invalid = await request('/api/backend', { command: 'settings_update_command', payload: { expectedRevision: enabled.revision, patch: { toolAutoUpdate: 'always' } } }); assert.equal(invalid.ok, false); assert.equal((await cmd('settings_get_command')).revision, enabled.revision); check('Invalid update policy leaves revision intact', invalid);
  const a = await cmd('nightshift_create_command', { id: 'parent', prompt: 'Review local task evidence', owner: 'Paul' });
  const b = await tool('nightshift.create', { id: 'child', prompt: 'Original dormant prompt', owner: 'Paul', needs: ['parent'] });
  let child = await tool('nightshift.edit', { id: 'child', patch: { title: 'Edited task', prompt: 'Edited dormant prompt' }, expectedUpdatedAt: b.updatedAt }); assert.equal(child.title, 'Edited task'); assert.equal(child.armed, false); check('Native task edit writes real durable state', child);
  const stale = await request('/api/backend', { command: 'nightshift_edit_command', payload: { id: 'child', patch: { title: 'Wrong stale title' }, expectedUpdatedAt: b.updatedAt } }); assert.equal(stale.ok, false); assert.match(stale.error, /Task changed/); check('Stale task edit refused', stale);
  for (const [id, needs, at, match] of [['parent', ['child'], a.updatedAt, /Cyclic/], ['child', ['absent'], child.updatedAt, /Missing prerequisite/]]) {
    const result = await request('/api/backend', { command: 'nightshift_reparent_command', payload: { id, needs, expectedUpdatedAt: at } }); assert.equal(result.ok, false); assert.match(result.error, match); check('Invalid dependency graph refused: ' + id, result);
  }
  const manual = await tool('manual.run', { id: 'nightshift', chapter: 'board', procedure: 'reparent-task', inputs: { id: 'child', needs: [] } }); assert.equal(manual.status, 'completed'); check('CL reparent procedure independently observes saved dependencies', manual);
  const title = await tool('manual.run', { id: 'nightshift', chapter: 'board', procedure: 'edit-task-title', inputs: { id: 'child', title: 'Verified by manual' } }); assert.equal(title.status, 'completed'); check('CL edit procedure independently observes title and disarmed state', title);
  child = await cmd('nightshift_task_command', { id: 'child' });
  const desktop = await request('/fixture/desktop', { command: 'nightshift_reparent_command', payload: { id: 'child', needs: ['parent'], expectedUpdatedAt: child.updatedAt } }); assert.equal(desktop.data.needs[0], 'parent'); check('Desktop bridge forwards new command on explicit owned port', desktop.data);
  const complete = await cmd('nightshift_tick_command', { id: 'parent', evidence: { type: 'file', path: 'evidence.txt' } }); assert.equal(complete.status, 'done');
  const immutable = await request('/api/backend', { command: 'nightshift_edit_command', payload: { id: 'parent', patch: { title: 'Rewrite done task' }, expectedUpdatedAt: complete.updatedAt } }); assert.equal(immutable.ok, false); assert.match(immutable.error, /Only dormant/); check('Completed task and real file evidence immutable', immutable);
  const attempted = await cmd('nightshift_create_command', { id: 'attempted', prompt: 'Controlled attempt boundary', owner: 'Paul' }); await request('/fixture/attempt', { id: 'attempted' });
  const attempt = await request('/api/backend', { command: 'nightshift_edit_command', payload: { id: 'attempted', patch: { title: 'Rewrite historical attempt' }, expectedUpdatedAt: attempted.updatedAt } }); assert.equal(attempt.ok, false); assert.match(attempt.error, /recorded attempt/); check('Historical attempt cannot be rewritten', attempt);
  const expected = await cmd('nightshift_task_command', { id: 'child' }); await stop(); await start();
  const restored = await cmd('nightshift_task_command', { id: 'child' }); assert.deepEqual(restored, expected); assert.equal((await cmd('settings_get_command')).settings.toolAutoUpdate, 'allow'); check('Restart preserves exact edited graph and owner policy', restored);
  receipt.passed = true;
} catch (error) { receipt.passed = false; receipt.error = String(error.stack ?? error); throw error; }
finally {
  try { await stop(); receipt.cleanup = { ownedBackendStopped: true, exitCode: server?.exitCode }; }
  catch (error) { server?.kill(); receipt.cleanup = { ownedBackendStopped: false, error: String(error) }; receipt.passed = false; }
  const files = ['src/grant_agent/nightshift.py', 'src/grant_agent/neyvia_nightshift.py', 'src/grant_agent/neyvia_settings.py', 'src/grant_agent/runtime_auto_update.py', 'manuals/cl/nightshift.cl', 'manuals/cl/settings.cl', 'scripts/verify_fix_followups.mjs'];
  receipt.sources = files.map(path => ({ path, sha256: createHash('sha256').update(readFileSync(resolve(repo, path))).digest('hex') }));
  receipt.finishedAt = new Date().toISOString(); mkdirSync(resolve(repo, 'scripts/evidence'), { recursive: true }); writeFileSync(output, JSON.stringify(receipt, null, 2) + '\n');
}
