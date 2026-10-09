// Actual compiled Settings/Night Shift components in an owned WebView2 host.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync, openSync, closeSync } from 'node:fs';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright';
const repo = resolve(import.meta.dirname, '..');
const [port, cdp] = process.argv.slice(2).map(Number);
assert.equal(port, 48667); assert.equal(cdp, 48663);
const base = `http://127.0.0.1:${port}`;
const root = resolve(repo, '.agent_control/proofs', `FIX-followups-ui-${Date.now()}`);
const staticRoot = resolve(root, 'build'); mkdirSync(root, { recursive: true });
const entry = `import React,{useState} from 'react';import{createRoot}from'react-dom/client';
import{NxNightShift}from'../../../web/src/neyvia/next/NxNightShift.jsx';
import{NxSettings}from'../../../web/src/neyvia/next/NxSettings.jsx';
import{startBus}from'../../../web/src/neyvia/next/nxBus.js';
import'../../../web/src/neyvia/next/nxTokens.css';import'../../../web/src/neyvia/next/nxThemes.css';import'../../../web/src/neyvia/next/nxShell.css';import'../../../web/src/neyvia/next/nxOs.css';
function App(){const[view,setView]=useState('night');return <div className="nx" data-nx-theme="dark" style={{height:'100vh',background:'var(--nx-bg)',color:'var(--nx-text)',display:'flex',flexDirection:'column'}}><nav><button onClick={()=>setView('night')}>Night Shift fixture</button><button onClick={()=>setView('settings')}>Settings fixture</button></nav><main style={{flex:1,minHeight:0}}>{view==='night'?<NxNightShift folders={[{path:${JSON.stringify(root)},name:'Owned proof workspace'}]}/>:<NxSettings/>}</main></div>};startBus();createRoot(document.getElementById('root')).render(<App/>);`;
writeFileSync(resolve(root, 'entry.jsx'), entry);
writeFileSync(resolve(root, 'index.html'), '<!doctype html><html><head><title>FIX actual followup UI components</title></head><body style="margin:0"><div id="root"></div><script type="module" src="./entry.jsx"></script></body></html>');
writeFileSync(resolve(root, 'evidence.txt'), 'Actual local completion evidence\n');
const receipt = { schema: 'neyvia.FIX.followups-ui.v1', startedAt: new Date().toISOString(), ports: [port, cdp], root,
  boundary: 'Actual production components/CSS built with Vite, real authenticated backend and WebView2 host forwarding desktop calls. Isolated component stage; no installed full shell/public deployment claim.', checks: [] };
let backend, native, browser, cookie = '', page;
const env = { ...process.env, PYTHONPATH: resolve(repo, 'src'), NEYVIA_UI_BACKEND_URL: base,
  NEYVIA_BROWSER_PROOF_SCOPE: 'FIX', NEYVIA_BROWSER_PROOF_PORTS: `${port},${cdp}`, NEYVIA_PROOF_ALLOWED_PORTS: JSON.stringify([port, cdp]),
  NEYVIA_PROOF_CREDENTIAL_GUARD: '1', NEYVIA_TOOL_AUTO_UPDATE: '0', NEYVIA_COORDINATOR_AUTOSTART: '0', FLUXIO_WATCHDOG_AUTOSTART: '0', NEYVIA_CONNECTED_SERVICE_PORT: String(port), FLUXIO_LOCAL_SESSION_BOOTSTRAP: '1' };
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function eventual(fn, timeout = 180000) { const end = Date.now() + timeout; while (Date.now() < end) { const value = await fn(); if (value) return value; await pause(200); } throw Error('Owned UI transition deadline exceeded'); }
async function request(command, payload = {}) {
  const response = await fetch(base + '/api/backend', { method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: cookie }, body: JSON.stringify({ command, payload }), signal: AbortSignal.timeout(30000) });
  const answer = await response.json(); assert.equal(answer.ok, true, JSON.stringify(answer)); return answer.data;
}
function check(name, observed) { receipt.checks.push({ name, passed: true, observed }); console.log('PASS', name); }
async function stop(child) { if (child?.exitCode === null) { child.kill(); await eventual(() => child.exitCode !== null || child.signalCode !== null, 10000); } }
try {
  await build({ configFile: false, root, plugins: [react()], cacheDir: resolve(root, 'vite-cache'), build: { outDir: staticRoot, emptyOutDir: true } });
  const log = openSync(resolve(root, 'backend.log'), 'a');
  backend = spawn('C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe', ['scripts/run_web_backend.py', '--host', '127.0.0.1', '--port', String(port), '--root', root, '--static-root', staticRoot, '--skip-runtime-auto-update', '--skip-proof-self-check'], { cwd: repo, env, windowsHide: true, stdio: ['ignore', log, log] }); closeSync(log);
  await eventual(async () => { if (backend.exitCode !== null) throw Error(readFileSync(resolve(root, 'backend.log'), 'utf8')); try { return (await fetch(base + '/api/health', { signal: AbortSignal.timeout(500) })).ok; } catch { return false; } });
  const login = await fetch(base + '/api/auth/local-session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); assert.equal(login.status, 200); cookie = login.headers.get('set-cookie').split(';')[0];
  for (const task of [{ id: 'upstream', prompt: 'First prerequisite' }, { id: 'child', prompt: 'Original UI prompt', needs: ['upstream'] }, { id: 'dependent', prompt: 'Waits for child', needs: ['child'] }]) await request('nightshift_create_command', { ...task, owner: 'Paul' });
  const connectedResponse = await fetch(base + '/api/ui/browser', { method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: cookie }, body: JSON.stringify({ op: 'runtime.connect', args: {} }) }); const connected = await connectedResponse.json(); assert.equal(connected.ok, true);
  const nativeLog = openSync(resolve(root, 'native.log'), 'a');
  native = spawn(resolve(repo, 'scripts/browser-probe/target/debug/browser-proof.exe'), [], { cwd: repo, env: { ...env, NEYVIA_BROWSER_BASE: base, NEYVIA_BROWSER_TOKEN: connected.token, NEYVIA_BROWSER_PROOF_UI_URL: base + '/index.html', NEYVIA_BROWSER_PROOF_UI_PROFILE: resolve(root, 'ui-profile'), NEYVIA_BROWSER_PROOF_OWNER_COOKIE: cookie, NEYVIA_BROWSER_PROOF_COMMANDS: 'nightshift_summary_command,nightshift_resources_command,nightshift_edit_command,nightshift_tasks_command,settings_get_command,settings_update_command,connected_events_poll_command', WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${cdp}` }, windowsHide: true, stdio: ['ignore', nativeLog, nativeLog] }); closeSync(nativeLog);
  await eventual(async () => { if (native.exitCode !== null) throw Error(readFileSync(resolve(root, 'native.log'), 'utf8')); try { return (await fetch(`http://127.0.0.1:${cdp}/json/version`, { signal: AbortSignal.timeout(500) })).ok; } catch { return false; } });
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdp}`);
  page = await eventual(() => browser.contexts().flatMap(context => context.pages()).find(tab => tab.url() === base + '/index.html'));
  const [name, ...value] = cookie.split('='); await page.context().addCookies([{ name, value: value.join('='), url: base }]); await page.reload();
  await page.locator('[data-ns-task="child"]').waitFor({ timeout: 30000 });
  await page.locator('[data-ns-task="child"]').click(); await page.getByRole('button', { name: 'Edit task…', exact: true }).click();
  await page.getByLabel('Short title', { exact: true }).fill('Saved from actual UI'); await page.getByLabel(/^Task prompt/).fill('Actual rendered edited prompt');
  const prerequisites = page.getByRole('group', { name: 'Prerequisites' }); await prerequisites.getByLabel('dependent', { exact: true }).check(); await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: /Cyclic/ }).waitFor(); const unchanged = await request('nightshift_task_command', { id: 'child' }); assert.deepEqual(unchanged.needs, ['upstream']); check('Actual edit form refuses a dependency cycle without writing', { error: await page.getByRole('alert').innerText(), needs: unchanged.needs });
  await prerequisites.getByLabel('dependent', { exact: true }).uncheck(); await prerequisites.getByLabel('upstream', { exact: true }).uncheck(); await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByRole('form', { name: 'Edit task' }).waitFor({ state: 'hidden' }); const saved = await request('nightshift_task_command', { id: 'child' }); assert.equal(saved.title, 'Saved from actual UI'); assert.equal(saved.prompt, 'Actual rendered edited prompt'); assert.deepEqual(saved.needs, []); assert.equal(saved.armed, false); check('Rendered edit/reparent saves exact durable prompt/title/graph and disarms', saved);
  await page.getByRole('button', { name: 'Edit task…', exact: true }).click(); await page.getByLabel('Short title', { exact: true }).fill('Must not overwrite a concurrent edit'); await request('nightshift_edit_command', { id: 'child', expectedUpdatedAt: saved.updatedAt, patch: { title: 'Concurrent owner title' } }); await page.getByRole('button', { name: 'Save changes', exact: true }).click(); await page.getByRole('alert').filter({ hasText: /Cancel and reopen/ }).waitFor(); assert.equal((await request('nightshift_task_command', { id: 'child' })).title, 'Concurrent owner title'); check('Actual UI CAS conflict preserves the newer task and gives a recovery step', await page.getByRole('alert').innerText());
  await page.getByRole('button', { name: 'Cancel', exact: true }).click(); await request('nightshift_tick_command', { id: 'child', evidence: { type: 'file', path: 'evidence.txt' } }); await page.reload(); await page.locator('[data-ns-task="child"]').click(); assert.equal(await page.getByRole('button', { name: 'Edit task…', exact: true }).count(), 0); check('Completed task has no edit control after real evidence tick', 'done task immutable');
  await page.getByRole('button', { name: 'Settings fixture', exact: true }).click(); const policy = page.getByRole('combobox', { name: 'Global CLI updates', exact: true }); await policy.waitFor(); assert.equal(await policy.inputValue(), 'ask'); await policy.selectOption('off'); await eventual(async () => (await request('settings_get_command')).settings.toolAutoUpdate === 'off', 15000); await policy.selectOption('allow'); await eventual(async () => (await request('settings_get_command')).settings.toolAutoUpdate === 'allow', 15000); check('Rendered updater dropdown saves owner policy via canonical revisions', (await request('settings_get_command')).settings.toolAutoUpdate);
  await page.reload(); await page.getByRole('button', { name: 'Settings fixture', exact: true }).click(); await page.getByRole('combobox', { name: 'Global CLI updates', exact: true }).waitFor(); await eventual(async () => (await page.getByRole('combobox', { name: 'Global CLI updates', exact: true }).inputValue()) === 'allow', 15000); check('Actual reload restores persisted owner policy', 'allow');
  const image = resolve(repo, 'scripts/evidence/fix/followups-ui.png'); mkdirSync(resolve(repo, 'scripts/evidence/fix'), { recursive: true }); await page.getByRole('heading', { name: 'Tool updates', exact: true }).scrollIntoViewIfNeeded(); await page.screenshot({ path: image }); receipt.capture = { path: image, sha256: createHash('sha256').update(readFileSync(image)).digest('hex') }; receipt.passed = true;
} catch (error) { receipt.passed = false; receipt.error = String(error.stack ?? error); if (page && !page.isClosed()) { receipt.failureUi = { text: await page.locator('body').innerText().catch(() => ''), fields: await page.locator('label').allTextContents().catch(() => []) }; const image = resolve(repo, 'scripts/evidence/fix/followups-ui-failure.png'); mkdirSync(resolve(repo, 'scripts/evidence/fix'), { recursive: true }); await page.screenshot({ path: image }).catch(() => {}); } throw error; }
finally {
  await browser?.close(); await stop(native); await stop(backend); receipt.cleanup = { nativeStopped: !native || native.exitCode !== null || native.signalCode !== null, backendStopped: !backend || backend.exitCode !== null || backend.signalCode !== null };
  receipt.sources = ['web/src/neyvia/next/NxNightShift.jsx', 'web/src/neyvia/next/NxSettings.jsx', 'src/grant_agent/nightshift.py', 'src/grant_agent/neyvia_settings.py', 'scripts/verify_fix_followups_ui.mjs'].map(path => ({ path, sha256: createHash('sha256').update(readFileSync(resolve(repo, path))).digest('hex') })); receipt.finishedAt = new Date().toISOString(); writeFileSync(resolve(repo, 'scripts/evidence/FIX-followups-ui.json'), JSON.stringify(receipt, null, 2) + '\n');
}
