import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import assert from 'node:assert/strict';
process.on('uncaughtException', error => { console.error(error.message); process.exit(1); });
process.on('unhandledRejection', error => { console.error(error.message); process.exit(1); });

const port = Number(process.argv[2]);
assert(port >= 48441 && port <= 48449);
const base = `http://127.0.0.1:${port}`;
let cookie = '';
const checks = [];
async function request(route, body, token) {
  const response = await fetch(base + route, {method: body === undefined ? 'GET' : 'POST',
    headers: {'Content-Type': 'application/json', ...(cookie ? {Cookie: cookie} : {}), ...(token ? {Authorization: `Bearer ${token}`} : {})},
    body: body === undefined ? undefined : JSON.stringify(body)});
  if (route === '/api/auth/local-session') cookie = response.headers.get('set-cookie').split(';')[0];
  const data = await response.json();
  return {status: response.status, ...data};
}
const command = (name, payload = {}) => request('/api/backend', {command: name, payload});
const check = (name, passed) => {assert(passed, name); checks.push({name, passed});};
check('local owner session', (await request('/api/auth/local-session', {})).ok);
check('outside workspace path is HTTP400', (await command('gamedev_setup_command', {engine: 'babylon', projectPath: path.resolve('..')})).status === 400);
for (const app of ['godot','playtest','asset-checks']) {
  const opened = await request('/api/ui/tools/call', {tool:'neyvia.app.open', arguments:{app}});
  check(`ready app ${app} opens through bot bus`, opened.ok && opened.data?.ok);
}
const reported = await request('/api/ui/app-state', {app:'game-dev',clientId:'follow-proof',state:{tab:'babylon',picked:{babylon:''}}});
check('screen reports accepted', reported.ok);
const state = await command('gamedev_state_command');
check('shared reported state observed', state.data.ui.tab === 'babylon' && state.data.ui.source === 'ui');
check('unknown screen state refused', (await request('/api/ui/app-state', {app:'game-dev',state:{tab:'unknown'}})).status === 400);
const htmlResponse = await fetch(base + '/api/gamedev/browser', {headers:{Cookie:cookie}});
assert.equal(htmlResponse.status, 200);
const html = await htmlResponse.text();
const config = JSON.parse(html.match(/const config\s*=\s*(\{.*?\});/s)[1]);
const bridge = (op, args) => request('/api/gamedev/bridge/' + op, args, config.token);
const registered = await bridge('register', {engine:'babylon',projectPath:config.projectPath,context:'Edit',environment:'FOLLOW-real-NullEngine',capabilities:['inspect','edit','run','stop']});
check('real runtime bridge registered', registered.ok);
const sessionId = registered.data.sessionId;
const context = {console, setTimeout, clearTimeout, setInterval, clearInterval, performance, Uint8Array, ArrayBuffer};
context.window = context;
context.navigator = { userAgent: 'FOLLOW NullEngine' };
context.addEventListener = context.removeEventListener = () => {};
vm.runInNewContext(fs.readFileSync('scripts/gamedev/vendor/babylon.js','utf8'), context);
vm.runInNewContext(fs.readFileSync('scripts/gamedev/scene-runtime.js','utf8'), context);
const engine = new context.BABYLON.NullEngine();
const scene = new context.NeyviaScene(context.BABYLON, engine);
for (const [action, args] of [['edit',{op:'create',name:'FOLLOW box',expectedRevision:0}],['run',{}],['inspect',{}],['stop',{}]]) {
  const queued = await command('gamedev_action_command', {sessionId,action,args,requestId:sessionId+'-'+action});
  check(`${action} queued`, queued.ok);
  const poll = await bridge('poll', {sessionId});
  assert.equal(poll.data.request.action, action);
  const result = await scene.dispatch(action, args);
  const complete = await bridge('complete', {sessionId,requestId:poll.data.request.requestId,status:'succeeded',result});
  check(`${action} actual runtime receipt`, complete.ok && complete.data.status === 'succeeded');
}
scene.scene.dispose(); engine.dispose();
const receipts = await request('/api/ui/tools/call', {tool:'neyvia.gamedev.receipts',arguments:{sessionId}});
check('bot and UI receive the same durable receipts', receipts.ok && receipts.data.ok && receipts.data.result.receipts.length === 4);
check('bounded list rejects malformed limits', (await command('gamedev_receipts_command',{limit:201})).status === 400);
const report = {schema:'neyvia.FOLLOW.gamedev.v1', port, passed:true, checks, limitation:'Actual application scene and bridge calls use Babylon NullEngine. Chrome/IAB unavailable; new rendered Game Dev log inspection remains blocked. Godot readiness follows the explicit handoff owner proof.'};
fs.writeFileSync('scripts/evidence/FOLLOW-gamedev.json', JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({passed:true, checks:checks.length}));
