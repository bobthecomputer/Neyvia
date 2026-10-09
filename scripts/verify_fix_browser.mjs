// Real pinned Obscura CDP and production HTTP calls; fixture shares the owned backend port.
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
const repo = resolve(import.meta.dirname, '..');
const [port, enginePort] = process.argv.slice(2).map(Number);
if (port !== 48667 || enginePort !== 48663) throw Error('Explicit backend48667 and CDP48663 required');
const python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe';
const root = resolve(repo, '.agent_control/proofs', `FIX-browser-${Date.now()}`); mkdirSync(root, { recursive: true });
const original = spawnSync('git', ['show', '19a0810b:src/grant_agent/perception_browser.py'], { cwd: repo, encoding: 'utf8' }); assert.equal(original.status, 0); writeFileSync(resolve(root, 'original-perception.py.txt'), original.stdout);
const bootstrap = String.raw`
import ast,json,os,sys,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
root=Path(sys.argv[1]);port=int(sys.argv[2])
from grant_agent.proof_credential_guard import install,prepare_broker_fixture
install(root);prepare_broker_fixture(root)
from grant_agent.web_backend import FluxioWebBackend,make_handler,SESSION_COOKIE_NAME,_json_response
from grant_agent.neyvia_browser import service_for
from grant_agent.browser_laya import configured_provider
assert configured_provider() is None
os.environ['NEYVIA_BROWSER_LAYA_URL']='http://127.0.0.1:'+str(port)+'/fixture/laya'
backend=FluxioWebBackend(root,root);session=backend.web_auth_sessions.issue({'username':backend.username,'role':'admin'})
source=ast.parse((root/'original-perception.py.txt').read_text())
original_dom=next(ast.literal_eval(node.value) for node in source.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='DOM' for target in node.targets))
HTML="""<!doctype html><html><head><title>Actual Obscura table/navigation fixture</title></head><body><h1>Before navigation</h1><table><tr><th>Region</th><th>Count</th></tr><tr><td>Paris</td><td>42</td></tr></table><button id='go' onclick=\"location.href='/fixture/done'\">Navigate to saved confirmation</button><button onclick=\"throw Error('Actual unrelated page error')\">Page error</button></body></html>"""
DONE="""<!doctype html><html><head><title>Navigation confirmed</title></head><body><h1>Saved after real navigation</h1><table><tr><td>Complete</td><td>43</td></tr></table></body></html>"""
Base=make_handler(backend)
class Handler(Base):
    def do_GET(self):
        if self.path in ('/fixture/browser','/fixture/done'):
            body=(HTML if self.path=='/fixture/browser' else DONE).encode()
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        super().do_GET()
    def do_POST(self):
        if self.path=='/fixture/laya':
            args=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            assert args['mode']=='advisory' and args['trust']=='untrusted-data'
            if args['question']=='invalid provider response':
                result={'ok':True,'executed':True}
            else:
                result={'ok':True,'decision':{'advice':'Review the saved table','observedUrl':args['observation']['url'],'observedText':args['observation']['text'],'question':args['question'],'effectsExecuted':False}}
            _json_response(self,200,result);return
        if self.path=='/fixture/baseline':
            args=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            service=service_for(root);tab=service.tab(args);worker=service.headless.profiles[tab['profileId']]
            try:
                value=worker.executor.submit(lambda:worker.pages[tab['id']]['page'].evaluate(original_dom)).result(timeout=20)
                result={'ok':True,'projection':value}
            except Exception as exc:result={'ok':False,'error':str(exc)}
            _json_response(self,200,{'ok':True,'data':result});return
        if self.path=='/fixture/engine-stop':
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            engine=service_for(root).headless;engine.process.terminate();engine.process.wait(timeout=10)
            _json_response(self,200,{'ok':True,'data':{'exitCode':engine.process.returncode}});return
        if self.path=='/fixture/stop':
            self.rfile.read(int(self.headers.get('Content-Length','0')));_json_response(self,200,{'ok':True});threading.Thread(target=server.shutdown,daemon=True).start();return
        super().do_POST()
server=ThreadingHTTPServer(('127.0.0.1',port),Handler);print('READY '+SESSION_COOKIE_NAME+'='+session,flush=True)
try:server.serve_forever(poll_interval=.1)
finally:
    engine=service_for(root).headless
    if engine:engine.close()
    server.server_close()
`;
const host = resolve(root, 'host.py'); writeFileSync(host, bootstrap);
const env = { ...process.env, PYTHONPATH: resolve(repo, 'src'), NEYVIA_UI_STATE_ROOT: root, NEYVIA_UI_BACKEND_URL: `http://127.0.0.1:${port}`,
  NEYVIA_TOOL_AUTO_UPDATE: '0', NEYVIA_COORDINATOR_AUTOSTART: '0', FLUXIO_WATCHDOG_AUTOSTART: '0', FLUXIO_LOCAL_SESSION_BOOTSTRAP: '1',
  NEYVIA_CONNECTED_SERVICE_PORT: String(port), NEYVIA_WEB_PORT: String(port), NEYVIA_OBSCURA_EXE: resolve(repo, '.agent_control/T20/obscura-v0.2.3/bin/obscura.exe'),
  NEYVIA_BROWSER_PROOF_PORTS: [port, enginePort].join(','), NEYVIA_PROOF_ALLOWED_PORTS: JSON.stringify([port, enginePort]) };
delete env.NEYVIA_BROWSER_LAYA_URL;
const receipt = { schema: 'neyvia.FIX.browser.v1', startedAt: new Date().toISOString(), root, ports: [port, enginePort], checks: [],
  engine: JSON.parse(readFileSync(resolve(repo, '.agent_control/T20/obscura-v0.2.3/receipt.json'), 'utf8')),
  boundary: 'Actual pinned non-stealth Obscura engine, production owner HTTP/CL routes and persisted browser user view. Native WebView2 filter/private/favicon/history journeys have a separate receipt.' };
const output = resolve(repo, 'scripts/evidence/FIX-browser.json'); let server, cookie = '', logs = '';
const wait = ms => new Promise(r => setTimeout(r, ms));
function check(name, observed) { receipt.checks.push({ name, passed: true, observed }); console.log('PASS', name); }
async function request(path, body, auth = true) {
  const response = await fetch(`http://127.0.0.1:${port}${path}`, { method: body === undefined ? 'GET' : 'POST',
    headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(auth ? { Cookie: cookie } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(60000) });
  return { status: response.status, ...(await response.json()) };
}
async function browser(op, args = {}) { const answer = await request('/api/ui/browser', { op, args }); assert.equal(answer.ok, true, JSON.stringify(answer)); return answer; }
async function tool(name, arguments_ = {}) { const answer = await request('/api/ui/tools/call', { tool: `neyvia.${name}`, arguments: arguments_ }); assert.equal(answer.ok, true, JSON.stringify(answer)); return answer.data.result ?? answer.data; }
try {
  server = spawn(python, ['-u', host, root, String(port)], { cwd: repo, env, windowsHide: true }); let stdout = '';
  server.stdout.on('data', chunk => { stdout += chunk; logs += chunk; }); server.stderr.on('data', chunk => { logs += chunk; });
  for (let i = 0; i < 200; i++) { if (server.exitCode !== null) throw Error(logs); const found = stdout.match(/READY ([^\r\n]+)/); if (found) { cookie = found[1]; break; } await wait(200); }
  assert.ok(cookie, 'Owned backend startup');
  const runtime = await browser('runtime.connect'); assert.equal(runtime.baseUrl, `http://127.0.0.1:${port}`); check('Native grant returns actual explicit loopback transport', { baseUrl: runtime.baseUrl, runtimeTokenPresent: Boolean(runtime.token) }); await browser('runtime.disconnect');
  const engine = await browser('headless.start', { port: enginePort, allowLocalFixtures: true }); assert.equal(engine.engine, 'obscura'); check('Actual pinned non-stealth engine started on configured assigned port', engine);
  const opened = await browser('tab.open', { url: `http://127.0.0.1:${port}/fixture/browser`, engine: 'obscura' }); const tabId = opened.tab.id;
  const baseline = await request('/fixture/baseline', { tabId }); check('Original DOM projection independently measured on same real engine', baseline.data);
  let observation = await tool('browser.observe', { tabId }); assert.ok(observation.tables.some(rows => rows.some(row => row.includes('Paris') && row.includes('42'))), JSON.stringify(observation)); check('Actual table retains text without iterable API failure', { tables: observation.tables, revision: observation.revision, elements: observation.elements });
  await browser('tab.grant', { tabId, enabled: true });
  const link = observation.elements.find(row => row.name.includes('Navigate to saved')); assert.ok(link);
  const action = await tool('browser.action', { tabId, revision: observation.revision, element: link.id, action: 'click' });
  assert.equal(action.status, 'done'); assert.match(action.observation.url, /\/fixture\/done$/); assert.match(action.observation.text, /Saved after real navigation/); check('Real navigating click completes with fresh new-document observation', action);
  const forbidden = await request('/api/ui/app-state', { app: 'browser', clientId: 'FIX-browser', state: { activeTabId: tabId, token: 'must-not-be-stored' } }); assert.equal(forbidden.ok, false); check('Browser view cannot inject authority fields', forbidden);
  const view = { space: 'default', activeTabId: tabId, reader: true, split: null, peek: null, tabsPlacement: 'top', pip: null };
  const reported = await request('/api/ui/app-state', { app: 'browser', clientId: 'FIX-browser', state: view }); assert.equal(reported.ok, true);
  const state = await tool('browser.state'); assert.equal(state.ui.tabsPlacement, 'top'); assert.equal(state.ui.activeTabId, tabId); assert.equal(state.tabs.find(row => row.id === tabId).agentGranted, true); check('Owner view state is observed by model without changing native grants', state.ui);
  const denied = await request('/api/ui/app-state', { app: 'browser', state: view }, false); assert.equal(denied.status, 401); check('Unauthenticated view-state write refused', denied);
  const advised = await tool('browser.decide', { tabId, question: 'Review the current real table' }); assert.equal(advised.available, true); assert.match(advised.decision.observedUrl, /fixture\/done$/); assert.match(advised.decision.observedText, /Saved after real navigation/); assert.equal(advised.decision.effectsExecuted, false); check('Explicit advisory HTTP hook routes real browser projection to owned adapter', { defaultUnavailableCheckedAtStartup: true, ...advised, boundary: 'Routing only; actual LAYA model quality remains unproved' });
  const malformed = await request('/api/ui/browser', { op: 'decide', args: { tabId, question: 'invalid provider response' } }); assert.equal(malformed.ok, false); check('Malformed provider response explicitly refused without effects', malformed);
  observation = await tool('browser.observe', { tabId }); const stopped = await request('/fixture/engine-stop', {});
  const cached = await tool('browser.observe', { tabId, cached: true }); assert.equal(cached.revision, observation.revision); assert.deepEqual(cached.tables, observation.tables); check('Cached projection survives actual stopped engine without another CDP read', { engineExitCode: stopped.data.exitCode, revision: cached.revision, tables: cached.tables });
  const fresh = await request('/api/ui/browser', { op: 'observe', args: { tabId } }); assert.equal(fresh.ok, false); check('Fresh observation refuses genuinely unavailable engine', fresh);
  receipt.passed = true;
} catch (error) { receipt.passed = false; receipt.error = String(error.stack ?? error); throw error; }
finally {
  if (server?.exitCode === null) { try { await request('/fixture/stop', {}); } catch {} for (let i = 0; i < 200 && server.exitCode === null; i++) await wait(100); if (server.exitCode === null) server.kill(); }
  receipt.cleanup = { backendExitCode: server?.exitCode, ownedBackendStopped: server?.exitCode !== null };
  receipt.sources = ['src/grant_agent/perception_browser.py', 'src/grant_agent/browser_obscura.py', 'src/grant_agent/browser_laya.py', 'src/grant_agent/neyvia_browser.py', 'src/grant_agent/neyvia_ui_api.py', 'manuals/cl/browser.cl', 'scripts/verify_fix_browser.mjs'].map(path => ({ path, sha256: createHash('sha256').update(readFileSync(resolve(repo, path))).digest('hex') }));
  receipt.finishedAt = new Date().toISOString(); mkdirSync(resolve(repo, 'scripts/evidence/fix'), { recursive: true }); writeFileSync(resolve(repo, 'scripts/evidence/fix', `FIX-browser-run-${receipt.startedAt.replace(/[^\d]/g, '')}.json`), JSON.stringify(receipt, null, 2) + '\n'); writeFileSync(output, JSON.stringify(receipt, null, 2) + '\n');
}
