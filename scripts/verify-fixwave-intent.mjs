// Actual SDK FunctionTool + plugin stdio -> local HTTP + transcript adapters.
// The current Codex agent authors the intent transformation. No fake provider
// generates it, and no live-model adherence is claimed by this acceptance call.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python313\\python.exe';
const root = path.join(repo, '.agent_control', `fixwave-intent-${Date.now()}`);
fs.mkdirSync(path.join(root, 'config'), { recursive: true });
fs.copyFileSync(path.join(repo, 'config', 'capability_packs.json'), path.join(root, 'config', 'capability_packs.json'));
const fixture = path.join(root, 'settings.json');
fs.writeFileSync(fixture, JSON.stringify({ theme: 'Morning', packs: ['notes', 'files'], enabled: true }));
const message = `Please read the disposable settings.json and tell me which theme it selects. Also list the selected packs and count them. Check whether enabled is really a boolean, not a truthy string. Compute the source file SHA-256 and include it in the receipt. Delete the settings file afterwards—no actually, forget deleting it, retain it unchanged and prove the hash stays the same. Keep these as separate asks and show progress as each finishes. Finally give a short account of what was checked and save the receipt locally. Don't call another model, change any global settings or touch other projects.`;
const authored = {
  items: [
    { ask: 'Read the disposable settings file', doneWhen: 'The actual settings file is read', status: 'in_progress' },
    { ask: 'Report the selected theme', doneWhen: 'The theme value is reported from the file', status: 'pending' },
    { ask: 'List selected packs and count them', doneWhen: 'Actual pack names and count are reported', status: 'pending' },
    { ask: 'Check enabled is a boolean', doneWhen: 'The actual value type is checked', status: 'pending' },
    { ask: 'Hash the source file', doneWhen: 'A real SHA-256 is retained', status: 'pending' },
    { ask: 'Retain settings unchanged', doneWhen: 'The source still exists with the same hash', status: 'pending' },
    { ask: 'Report checks briefly and save the receipt locally', doneWhen: 'The actual checked values appear in the saved receipt', status: 'pending' },
  ],
  dropped: [{ quote: 'Delete the settings file afterwards', why: 'Later correction requests retaining it unchanged' }],
  questions: [],
};
const steps = authored.items.map(row => ({ step: row.ask, status: row.status }));
const fixtureInput = path.join(root, 'authored-plan.json');
fs.writeFileSync(fixtureInput, JSON.stringify({ message, authored, steps }));
const env = { ...process.env, PYTHONPATH: path.join(repo, 'src'), NEYVIA_UI_STATE_ROOT: root, NEYVIA_UI_BACKEND_URL: 'http://127.0.0.1:47967' };
const children = [];
const checks = [];
const check = (name, value) => { assert(value, name); checks.push(name); };

function child(args) {
  const proc = spawn(python, args, { cwd: repo, env, windowsHide: true });
  children.push(proc);
  return proc;
}
async function execute(code) {
  const proc = child(['-c', code, root, fixtureInput]);
  let output = '', error = '';
  proc.stdout.on('data', chunk => output += chunk);
  proc.stderr.on('data', chunk => error += chunk);
  const timer = setTimeout(() => proc.kill(), 45000);
  const exit = await new Promise(resolve => proc.on('exit', resolve));
  clearTimeout(timer);
  assert.equal(exit, 0, error.slice(-1500));
  return JSON.parse(output.trim().split(/\r?\n/).at(-1));
}
function rpcProcess(proc) {
  let sequence = 0, tail = '';
  const waiting = new Map();
  proc.stdout.on('data', chunk => {
    tail += chunk;
    while (tail.includes('\n')) {
      const end = tail.indexOf('\n');
      const line = tail.slice(0, end); tail = tail.slice(end + 1);
      if (!line.trim()) continue;
      const row = JSON.parse(line); waiting.get(row.id)?.(row); waiting.delete(row.id);
    }
  });
  return async (method, params = {}) => {
    const id = ++sequence;
    const response = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { waiting.delete(id); reject(new Error(`RPC deadline: ${method}`)); }, 40000);
      waiting.set(id, value => { clearTimeout(timer); resolve(value); });
    });
    proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    const answer = await response;
    assert(!answer.error, JSON.stringify(answer.error));
    return answer.result;
  };
}
function payload(result) {
  assert(!result.isError, JSON.stringify(result));
  return JSON.parse(result.content.find(row => row.type === 'text').text);
}

try {
  const native = await execute(`import asyncio,json,sys
from pathlib import Path
from agents.tool_context import ToolContext
from grant_agent.neyvia_agent import NeyviaAgentConfig,build_neyvia_agent
from grant_agent.connected_sessions.neyvia_items import tool_item
from grant_agent.connected_sessions.codex_items import map_thread_item
from grant_agent.connected_sessions.plan import latest_plan,plan_op
from grant_agent.neyvia_intent_plan import validate_plan
from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
root=Path(sys.argv[1]); data=json.loads(Path(sys.argv[2]).read_text())
config=NeyviaAgentConfig(root=root,session_id='intent-native',enable_specialists=False,situation_interface=False)
agent,run_config,gateway=build_neyvia_agent(config,provider=None,instructions='Inspect only the authorized disposable fixture.')
tool=next(tool for tool in agent.tools if tool.name=='update_plan')
args={'plan_json':json.dumps(data['steps']),'explanation':'Codex authored the corrected intent; no simulated provider'}
result=asyncio.run(tool.on_invoke_tool(ToolContext(context=None,tool_name='update_plan',tool_call_id='intent-native-call',tool_arguments=json.dumps(args)),json.dumps(args)))
receipt=json.loads(result)
item=tool_item({'tool':'update_plan','input':json.dumps(args),'output':result,'status':'completed','error':''},'native-call',1,None,finished=True)
fold=latest_plan([item])
assert len(fold['items'])==len(data['steps'])
assert 'multi' in agent.instructions and 'intent.checklist' in agent.instructions
for invalid in ([{'step':'x','status':'imagined'}],[{'step':'x','status':'in_progress'},{'step':'y','status':'in_progress'}], [{'step':'','status':'pending'}]):
 try: validate_plan(invalid)
 except ValueError: pass
 else: raise AssertionError('invalid plan accepted')
assert plan_op('update_plan',{'plan_json':'invalid'}) is None
codex=map_thread_item({'id':'mcp-call','type':'mcpToolCall','server':'neyvia','tool':'plan_update','arguments':{'plan':data['steps']},'status':'completed','result':{'content':[{'type':'text','text':'real plan accepted'}]}},seq=2,at=None)
assert len(latest_plan(codex)['items'])==len(data['steps'])
failed=map_thread_item({'id':'mcp-failed','type':'mcpToolCall','server':'neyvia','tool':'plan_update','arguments':{'plan':data['steps']},'status':'completed','result':{'isError':True}},seq=3,at=None)
assert latest_plan(failed) is None
compact=CompactNeyviaMCPServer(root,read_only=True,session_id='intent-mcp')
init=compact.handle({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}})
assert 'intent.checklist' in init['result']['instructions']
catalog=compact.handle({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
assert 'neyvia.plan.update' not in [row['name'] for row in catalog['result']['tools']]
print(json.dumps({'tool':tool.name,'providerCalls':receipt['providerCalls'],'fold':fold,'nativeToolCount':len(agent.tools),'compactToolCount':len(catalog['result']['tools']),'instructionPresent':True,'validationChecks':5}))`);
  check('Actual built Native SDK FunctionTool publishes the corrected plan', native.providerCalls === 0 && native.fold.items.length === 7);
  check('Native and compact MCP startup carry intent procedure', native.instructionPresent);
  check('Silent adapter/validation invariants and failed-call exclusion', native.validationChecks === 5);

  const backend = child(['-c', `import sys
from pathlib import Path
from http.server import ThreadingHTTPServer
from grant_agent.web_backend import FluxioWebBackend,make_handler
backend=FluxioWebBackend(Path(sys.argv[1]),Path('web'))
ThreadingHTTPServer(('127.0.0.1',47967),make_handler(backend)).serve_forever()`, root]);
  backend.stderr.on('data', () => {});
  const deadline = Date.now() + 30000;
  while (true) {
    try { const response = await fetch(env.NEYVIA_UI_BACKEND_URL + '/api/auth/local-session', { method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' } }); if (response.ok) break; } catch {}
    assert(Date.now() < deadline, 'local backend startup deadline');
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  const rpc = rpcProcess(child([path.join(repo, 'plugins/neyvia/mcp/neyvia_mcp.py')]));
  const init = await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'fixwave-proof', version: '1' } });
  check('Real plugin MCP initialization requires intent first', init.instructions.includes('intent_checklist') && init.instructions.includes('plan_update'));
  const catalog = await rpc('tools/list');
  check('Actual backend registry exposes plan_update through plugin MCP', catalog.tools.some(row => row.name === 'plan_update'));
  const template = payload(await rpc('tools/call', { name: 'intent_checklist', arguments: { text: message } }));
  check('Real long-message extraction template makes no hidden provider call', template.providerCalls === 0 && template.prompt.includes(message));
  const first = payload(await rpc('tools/call', { name: 'plan_update', arguments: { plan: steps, sessionId: 'intent-plugin' } }));
  check('Model-authored corrected asks persist through actual MCP -> HTTP call', first.providerCalls === 0 && first.plan.items.length === authored.items.length);
  const settings = JSON.parse(fs.readFileSync(fixture, 'utf8'));
  const { createHash } = await import('node:crypto');
  const hash = () => createHash('sha256').update(fs.readFileSync(fixture)).digest('hex');
  const originalHash = hash();
  assert.equal(settings.theme, 'Morning'); assert.deepEqual(settings.packs, ['notes', 'files']); assert.equal(typeof settings.enabled, 'boolean');
  const progressed = steps.map((row, index) => ({ ...row, status: index < 6 ? 'completed' : 'in_progress' }));
  const second = payload(await rpc('tools/call', { name: 'plan_update', arguments: { plan: progressed, explanation: 'Actual fixture read/type/hash checks passed; receipt is being saved', sessionId: 'intent-plugin' } }));
  check('Real second plan call preserves asks and updates progress', second.plan.items.filter(row => row.status === 'completed').length === 6);
  check('Later correction retains the source unchanged', fs.existsSync(fixture) && hash() === originalHash);

  // Execute the actual observational mod (transpiled, without inventing a
  // provider turn) against this same HTTP service and check its real receipt.
  const source = fs.readFileSync(path.join(repo, 'plugins/neyvia/hooks/register.ts'), 'utf8');
  const transpiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 }, reportDiagnostics: true });
  assert(!transpiled.diagnostics?.length);
  const hookPath = path.join(root, 'hook.mjs'); fs.writeFileSync(hookPath, transpiled.outputText);
  const { register } = await import(pathToFileURL(hookPath).href);
  const callbacks = new Map(), store = new Map();
  register((event, callback) => callbacks.set(event, callback), {});
  const observerErrors = [];
  const engine = { env: { get: async key => env[key] || '' }, session: { id: async () => 'intent-observer', version: async () => ({ version: 'acceptance-adapter' }) }, store: { get: async key => store.get(key), set: async (key, value) => store.set(key, value) }, ui: { status: () => {}, log: line => observerErrors.push(line) }, http: { fetch: async (url, options) => { const response = await fetch(url, options); return { status: response.status, ok: response.ok, headers: Object.fromEntries(response.headers), text: await response.text() }; } } };
  await callbacks.get('session.start')(engine, { cwd: root }, async event => event);
  await callbacks.get('tool.call')(engine, { tool: 'mcp__plugin_neyvia_neyvia__plan_update', plan: progressed }, async () => ({ result: second }));
  const runs = payload(await rpc('tools/call', { name: 'claude_runs', arguments: {} }));
  assert(!observerErrors.length, JSON.stringify(observerErrors));
  check('Actual plugin observer reports the MCP checklist to backend', JSON.stringify(runs).includes('Read the disposable settings file'));

  const receipt = { item: 7, checks, input: message, extractionAuthor: 'Current Codex agent; no simulated provider', authored, native, initialPlan: first.plan, updatedPlan: second.plan, actualFixture: { theme: settings.theme, packs: settings.packs, count: settings.packs.length, enabledType: typeof settings.enabled, sha256: originalHash }, missing: ['Live provider compliance with startup instructions remains unproven; no provider response was synthesized', 'Actual pinned checklist browser render not repeated', 'Plugin full typecheck blocked by pre-existing missing .claude-plugin/types/tsconfig.json and claude-code module types; actual TypeScript observer transpile + HTTP reporting passed'] };
  const target = path.join(repo, 'scripts/evidence/fixwave-item7.json');
  fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({ checks: checks.length, receipt: target, providerCalls: 0, missing: receipt.missing }, null, 2));
} finally {
  for (const proc of children) if (proc.exitCode === null) proc.kill();
  await Promise.all(children.map(proc => proc.exitCode !== null ? Promise.resolve() : new Promise(resolve => proc.once('exit', resolve))));
}
