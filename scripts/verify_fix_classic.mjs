// Real desktop -> authenticated persistent HTTP owner -> shared durable state.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';

const repo = resolve(import.meta.dirname, '..');
const port = Number(process.argv[2]);
if (![48661, 48666].includes(port)) throw Error('Supply owned explicit port48661 or48666');
const root = resolve(repo, '.agent_control/proofs', `FIX-classic-${Date.now()}`);
mkdirSync(root, { recursive: true });
const python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const hostPath = resolve(root, 'host.py');
writeFileSync(hostPath, String.raw`
import sys,json,threading,os
from pathlib import Path
from http.server import ThreadingHTTPServer
root=Path(sys.argv[1]);port=int(sys.argv[2])
from grant_agent.proof_credential_guard import install,prepare_broker_fixture
install(root);prepare_broker_fixture(root)
from grant_agent.web_backend import FluxioWebBackend,make_handler,SESSION_COOKIE_NAME,_json_response
from grant_agent.desktop_bridge import dispatch_desktop_command,DesktopBridgeError,CLASSIC_SERVICE_COMMANDS
backend=FluxioWebBackend(root,root)
session=backend.web_auth_sessions.issue({'username':backend.username,'role':'admin'})
Base=make_handler(backend)
class Handler(Base):
    def do_POST(self):
        if self.path=='/fixture/desktop':
            data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            try:
                result=dispatch_desktop_command(Path(data.get('root') or root),data['command'],data.get('payload') or {})
                _json_response(self,200,{'ok':True,'data':result})
            except Exception as exc:_json_response(self,200,{'ok':False,'error':str(exc)})
            return
        if self.path=='/fixture/no-service':
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            names=['NEYVIA_CONNECTED_SERVICE_PORT','NEYVIA_WEB_PORT','FLUXIO_WEB_PORT']
            saved={name:os.environ.pop(name,None) for name in names}
            try:
                try:dispatch_desktop_command(root,'get_nearby_transfer_history_command',{})
                except DesktopBridgeError as exc:result={'refused':True,'error':str(exc)}
                else:result={'refused':False}
            finally:
                for name,value in saved.items():
                    if value is not None:os.environ[name]=value
            _json_response(self,200,{'ok':True,'data':result});return
        if self.path=='/fixture/stop':
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            _json_response(self,200,{'ok':True});threading.Thread(target=server.shutdown,daemon=True).start();return
        super().do_POST()
server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
print('READY '+SESSION_COOKIE_NAME+'='+session,flush=True)
try:server.serve_forever(poll_interval=.1)
finally:server.server_close()
`);
const env = { ...process.env, PYTHONPATH: resolve(repo, 'src'), PYTHONUTF8: '1',
  NEYVIA_COORDINATOR_AUTOSTART: '0', FLUXIO_WATCHDOG_AUTOSTART: '0', NEYVIA_TOOL_AUTO_UPDATE: '0',
  NEYVIA_CONNECTED_SERVICE_PORT: String(port), NEYVIA_WEB_PORT: String(port),
  NEYVIA_UI_STATE_ROOT: root, NEYVIA_UI_BACKEND_URL: `http://127.0.0.1:${port}` };
const receipt = { schema: 'neyvia.FIX.classic.v1', root, port, startedAt: new Date().toISOString(), checks: [],
  boundary: 'Real Python desktop bridge and authenticated HTTP commands plus shared UI bus and durable files; no rendered classic-shell claim.',
  limitations: ['No receiver sidecar exists; status says implemented=false.', 'Native prompt-file import already uses Tauri file picker; no Python arbitrary-path import was added.', 'iOS signing/build and external classic providers require their real dependencies.'] };
let child, cookie, logs = '';
const wait = ms => new Promise(r => setTimeout(r, ms));
async function req(path, body) {
  const response = await fetch(`http://127.0.0.1:${port}${path}`, { method: 'POST',
    headers: { 'Content-Type': 'application/json', Cookie: cookie }, body: JSON.stringify(body),
    signal: AbortSignal.timeout(90000) });
  return { status: response.status, ...await response.json() };
}
async function desktop(command, payload = {}) {
  const r = await req('/fixture/desktop', { command, payload }); assert.equal(r.ok, true, JSON.stringify(r));
  assert.notEqual(r.data?.ok, false, JSON.stringify(r)); return r.data;
}
async function tool(name, args = {}) {
  const r = await req('/api/ui/tools/call', { tool: `neyvia.${name}`, arguments: args });
  assert.equal(r.ok, true, JSON.stringify(r)); const value = r.data.result ?? r.data;
  assert.notEqual(value.ok, false, JSON.stringify(value)); return value;
}
function check(name, observed) { receipt.checks.push({ name, passed: true, observed }); console.log('PASS', name); }
try {
  child = spawn(python, ['-u', hostPath, root, String(port)], { cwd: repo, env, windowsHide: true });
  let stdout = ''; child.stdout.on('data', x => { stdout += x; logs += x; }); child.stderr.on('data', x => { logs += x; });
  for (let i = 0; i < 150; i++) {
    const ready = stdout.match(/READY ([^\r\n]+)/); if (ready) { cookie = ready[1]; break; }
    if (child.exitCode !== null) throw Error(logs); await wait(200);
  }
  assert.ok(cookie, logs);
  for (const [kind, target] of [['outputs', 'all'], ['perception', 'file:report.txt']]) {
    const result = await tool('manual.run', { id: kind === 'outputs' ? 'outputs' : 'perception', chapter: 'navigation', procedure: 'request-pane', inputs: { target } });
    assert.equal(result.status, 'completed', JSON.stringify(result));
    const state = await tool('state'); assert.deepEqual(state.pane, { kind, target });
    check(`CL ${kind} procedure and independent shared-state observer`, { status: result.status, pane: state.pane });
  }
  for (const app of ['marketplace', 'office-suite', 'personal-mesh', 'security', 'mcp-broker']) {
    const opened = await tool('app.open', { app }); assert.equal(opened.ok, true);
    check('Registered classic app request ' + app, opened);
  }
  const history = await desktop('get_nearby_transfer_history_command', { limit: 5 });
  const active = await desktop('get_nearby_active_transfer_command');
  const receiver = await desktop('get_nearby_receiver_sidecar_status_command'); assert.equal(receiver.implemented, false);
  check('Desktop transfer state reaches persistent service', { history, active, receiver });
  for (const command of ['get_mesh_enrollment_trust_command', 'get_nearby_send_compatibility_command', 'get_folder_sync_compatibility_command']) {
    check('Mesh refresh companion reaches owner: ' + command, await desktop(command));
  }
  const catalog = await desktop('get_app_factory_catalog_command'); assert.ok(catalog);
  check('Desktop App Factory catalogue reaches production owner', catalog);
  const ios = await desktop('create_ios_app_command', { name: 'FIX Classic', directory: 'classic-ios', bundleIdentifier: 'dev.neyvia.fixclassic', installDependencies: false });
  assert.ok(ios); assert.ok(readFileSync(resolve(root, 'classic-ios/package.json'), 'utf8'));
  check('Desktop iOS scaffold persists actual project without install', ios);
  const wrongRoot = await req('/fixture/desktop', { command: 'get_nearby_transfer_history_command', root: resolve(root, 'another-root') });
  assert.equal(wrongRoot.data?.ok, false, JSON.stringify(wrongRoot)); check('Persistent state-root mismatch refused', wrongRoot);
  const declared = readFileSync(resolve(repo, 'src/grant_agent/desktop_bridge.py'), 'utf8')
    .match(/CLASSIC_SERVICE_COMMANDS = frozenset\(\{([\s\S]*?)\}\)/)[1];
  receipt.commandWiring = [];
  for (const match of declared.matchAll(/"([a-z_]+_command)"/g)) {
    const command = match[1];
    const owner = readFileSync(resolve(repo, 'src/grant_agent/web_backend.py'), 'utf8');
    assert.ok(owner.includes(`"${command}"`), 'Missing production owner: ' + command);
    const refusal = await req('/fixture/desktop', { command, root: resolve(root, 'another-root') });
    assert.equal(refusal.data?.ok, false, JSON.stringify(refusal));
    receipt.commandWiring.push({ command, realStateRootRefusal: refusal.data.code,
      desktop: 'grant_agent.desktop_bridge.CLASSIC_SERVICE_COMMANDS',
      owner: 'grant_agent.web_backend.FluxioWebBackend.dispatch',
      frontend: 'NxClassicScreens -> callNeyvia/callNx -> authenticated backend',
      tauri: 'call_desktop_backend_command generic IPC',
      boundary: 'Registration and real authority refusal; provider/build success is separately bounded.' });
  }
  check('Every added classic command reaches the real persistent authority fence', receipt.commandWiring.length);
  const unknown = await req('/fixture/desktop', { command: 'unregistered_classic_command' }); assert.equal(unknown.ok, false); check('Unknown desktop command refused', unknown);
  const noService = await req('/fixture/no-service', {}); assert.equal(noService.data.refused, true); check('Absent explicit service port refuses before forwarding', noService.data);
  receipt.passed = true;
} catch (error) { receipt.passed = false; receipt.error = String(error.stack ?? error); throw error; }
finally {
  try {
    if (cookie && child.exitCode === null) await req('/fixture/stop', {});
    for (let i = 0; i < 100 && child?.exitCode === null; i++) await wait(100);
    receipt.cleanup = { stopped: child?.exitCode === 0, exitCode: child?.exitCode };
    if (child?.exitCode === null) child.kill();
  } catch (error) { child?.kill(); receipt.cleanup = { stopped: false, error: String(error) }; }
  if (!receipt.cleanup.stopped) receipt.passed = false;
  receipt.sources = ['src/grant_agent/desktop_bridge.py', 'src/grant_agent/neyvia_workspace_tools.py', 'src/grant_agent/neyvia_voice.py', 'src/grant_agent/web_backend.py', 'manuals/cl/outputs.cl', 'manuals/cl/perception.cl', 'manuals/cl/neyvia.cl', 'scripts/verify_fix_classic.mjs']
    .map(path => ({ path, sha256: createHash('sha256').update(readFileSync(resolve(repo, path))).digest('hex') }));
  receipt.finishedAt = new Date().toISOString();
  writeFileSync(resolve(repo, 'scripts/evidence/FIX-classic.json'), JSON.stringify(receipt, null, 2) + '\n');
}
