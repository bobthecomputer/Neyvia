// Independent production model/manual calls against the native UI owner's live runtime.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
const repo = resolve(import.meta.dirname, '..');
const args = process.argv.slice(2);
assert.equal(args.length, 4); assert.equal(args[0], '--base'); assert.equal(args[2], '--root');
const base = args[1], root = resolve(args[3]), url = new URL(base);
assert.equal(url.origin, 'http://127.0.0.1:48668'); assert.equal(base, url.origin);
assert.ok(root.startsWith(resolve(repo, '.agent_control/proofs') + '\\'));
const output = resolve(repo, 'scripts/evidence/FIX-reader.json');
const receipt = { schema: 'neyvia.FIX.reader.v1', base, root, startedAt: new Date().toISOString(), checks: [],
  boundary: 'Actual native WebView2 extraction, authenticated production tools/CL/owner routes and independent revision observers; lifecycle hosted by verify_fix_reader_ui.cjs. No third server or fabricated article.' };
const ownedTabs = []; let cookie = '', previous;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = path => createHash('sha256').update(readFileSync(path)).digest('hex');
async function request(path, body, auth = true) {
  const response = await fetch(base + path, { method: body === undefined ? 'GET' : 'POST',
    headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(auth && cookie ? { Cookie: cookie } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(30000) });
  return { status: response.status, ...(await response.json()) };
}
async function browser(op, args = {}) { const answer = await request('/api/ui/browser', { op, args }); assert.equal(answer.ok, true, JSON.stringify(answer)); return answer; }
async function tool(name, arguments_ = {}) { const answer = await request('/api/ui/tools/call', { tool: 'neyvia.' + name, arguments: arguments_ }); assert.equal(answer.ok, true, JSON.stringify(answer)); return answer.data.result ?? answer.data; }
async function complete(row) {
  if (!row.actionId) return row;
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) { const current = await browser('action.get', { actionId: row.actionId }); if (current.status === 'failed') throw Error(JSON.stringify(current)); if (current.status === 'done') return current; await delay(80); }
  throw Error('Actual native operation exceeded its bounded completion deadline');
}
async function open(path, privateTab = false) {
  const queued = await browser('tab.open', { url: base + path, private: privateTab }); ownedTabs.push(queued.tabId); await complete(queued);
  await complete(await browser('layout', { tabs: [{ tabId: queued.tabId, x: 0, y: 0, width: 1000, height: 650, visible: true }] }));
  await tool('browser.observe', { tabId: queued.tabId }); return queued.tabId;
}
function check(name, observed) { receipt.checks.push({ name, ok: true, observed }); console.log('PASS', name); }
try {
  const login = await fetch(base + '/api/auth/local-session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); assert.equal(login.status, 200); cookie = login.headers.get('set-cookie').split(';')[0];
  const state = await browser('state'); assert.equal(state.runtime.connected, true); previous = state.activeTabId;
  const catalog = await request('/api/ui/tools'); const definition = catalog.data.tools.find(row => row.name === 'neyvia.browser.reader'); assert.equal(definition.mutability, 'read'); assert.equal(definition.inputSchema.properties.cached.type, 'boolean'); check('Actual discovered model Reader tool is read-only with typed arguments', definition);
  const denied = await request('/api/ui/browser', { op: 'reader', args: { tabId: previous } }, false); assert.equal(denied.status, 401);
  const forged = await request('/api/ui/browser/runtime', { token: 'invalid-reader-runtime', op: 'report', event: { type: 'reader', tabId: previous } }, false); assert.equal(forged.status, 403); check('Anonymous owner extraction and unauthenticated native Reader report refused', { anonymous: denied.status, forgedRuntime: forged.status });
  const tabId = await open('/reader-article.html'); assert.equal((await browser('state')).tabs.find(tab => tab.id === tabId).agentGranted, false);
  const article = await tool('browser.reader', { tabId }); assert.equal(article.available, true); assert.equal(article.trust, 'untrusted-data'); assert.equal(article.title, 'Reader field notes'); assert.ok(article.paragraphs.includes('The native article contains a real paragraph for the reader to display exactly.')); assert.equal(article.text, article.blocks.map(block => block.text).join('\n'));
  const page = await tool('browser.observe', { tabId, cached: true }); assert.equal(article.revision, page.revision); assert.equal(article.url, page.url); assert.equal((await browser('state')).tabs.find(tab => tab.id === tabId).agentGranted, false); check('Fresh model call reads actual native article at the independently observed page revision without granting effects', article);
  for (const secret of ['PASSWORD_CANARY_FIX', 'TOKEN_CANARY_FIX', 'NAV_CANARY_FIX', 'SCRIPT_CANARY_FIX', 'STYLE_CANARY_FIX', 'FORM_CANARY_FIX', 'FORM_VALUE_CANARY_FIX', 'HIDDEN_CANARY_FIX', 'ASIDE_CANARY_FIX']) assert.ok(!JSON.stringify(article).includes(secret), secret);
  assert.match(article.text, /Mirrored secrets: \[redacted\] and \[redacted\]/); assert.match(article.text, /<img src=x/); check('Model Reader omits native secret/private/control content and returns literal HTML as plain text', { canariesOmitted: true, knownMirrorsRedacted: true, literalHtmlPreservedAsText: true });
  const cached = await tool('browser.reader', { tabId, cached: true }); assert.deepEqual(cached, article); check('Independent cached Reader observer returns the same current live projection', { revision: cached.revision, paragraphs: cached.paragraphs });
  const manual = await tool('manual.run', { id: 'browser', chapter: 'backend', procedure: 'read-article', inputs: { tabId } }); assert.equal(manual.status, 'completed'); check('Authored CL read-article procedure executes fresh extraction and independent matching-revision checks', manual);
  const malformed = await request('/api/ui/tools/call', { tool: 'neyvia.browser.reader', arguments: { tabId, cached: 'yes' } }); assert.equal(malformed.ok, false); check('Model Reader rejects a mistyped cache argument before native execution', malformed.data?.failure ?? malformed.error);
  const next = await browser('tab.navigate', { tabId, url: base + '/reader-next.html' });
  const stale = await request('/api/ui/browser', { op: 'reader', args: { tabId, cached: true } }); assert.equal(stale.ok, false); assert.match(JSON.stringify(stale.error), /fresh|stale|missing/i); await complete(next); await tool('browser.observe', { tabId });
  const replacement = await tool('browser.reader', { tabId }); assert.equal(replacement.title, 'The second article'); assert.notEqual(replacement.revision, article.revision); assert.ok(!replacement.text.includes('Reader field notes')); check('Real navigation clears old Reader and fresh native extraction binds the new article', { staleRefusal: stale.error, replacement });
  const emptyId = await open('/reader-empty.html'); const empty = await request('/api/ui/tools/call', { tool: 'neyvia.browser.reader', arguments: { tabId: emptyId } }); assert.equal(empty.ok, false); assert.match(JSON.stringify(empty), /no readable article text/i); const emptyTab = (await browser('state')).tabs.find(tab => tab.id === emptyId); assert.equal(emptyTab.status, 'live'); assert.equal(emptyTab.reader, undefined); check('Actual empty native page refuses Reader actionably while preserving the loaded page', { refusal: empty.data?.error ?? empty.error, nativePageStatus: emptyTab.status });
  const privateId = await open('/reader-article.html', true); const privateArticle = await tool('browser.reader', { tabId: privateId }); assert.equal(privateArticle.available, true);
  const persisted = JSON.parse(readFileSync(resolve(root, '.neyvia/browser/state.json'), 'utf8')); assert.ok(!persisted.tabs.some(tab => tab.id === privateId)); assert.ok(persisted.tabs.every(tab => !Object.hasOwn(tab, 'reader'))); await complete(await browser('tab.close', { tabId: privateId })); ownedTabs.splice(ownedTabs.indexOf(privateId), 1);
  const closed = await request('/api/ui/browser', { op: 'reader', args: { tabId: privateId, cached: true } }); assert.equal(closed.ok, false); assert.equal(closed.error.code, 'unknown_tab'); check('Private Reader cache is absent from canonical saved tabs/state and cleared after actual close', { persistedPrivateTab: false, persistedReaderContent: false, closedRefusal: closed.error });
  receipt.ok = true;
} catch (error) { receipt.ok = false; receipt.error = String(error.stack ?? error); throw error; }
finally {
  let restored = false;
  try { for (const tabId of ownedTabs.reverse()) await complete(await browser('tab.close', { tabId })); if (previous) { await browser('tab.activate', { tabId: previous }); restored = true; } receipt.cleanup = { ownTabsClosed: true, previousActiveRestored: restored, sharedRuntimeLeftForOwner: true }; }
  catch (error) { receipt.ok = false; receipt.cleanup = { error: String(error), sharedRuntimeLeftForOwner: true }; }
  receipt.sources = ['src/grant_agent/neyvia_browser.py', 'src/grant_agent/neyvia_workspace_tools.py', 'src-tauri/src/browser_projection.js', 'src-tauri/src/browser_runtime.rs', 'manuals/cl/browser.cl', 'scripts/verify_fix_reader.mjs'].map(path => ({ path, sha256: sha(resolve(repo, path)) }));
  receipt.finishedAt = new Date().toISOString(); writeFileSync(output, JSON.stringify(receipt, null, 2) + '\n');
}
