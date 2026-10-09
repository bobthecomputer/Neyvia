import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright';

const source = await readFile(new URL('../web/src/neyvia/neyviaStorage.js', import.meta.url));
const server = createServer((req, res) => {
  res.setHeader('Content-Type', req.url === '/storage.js' ? 'text/javascript' : 'text/html');
  res.end(req.url === '/storage.js' ? source : '<!doctype html><title>Storage recovery test</title>');
}).listen(0, '127.0.0.1');
await new Promise(resolve => server.once('listening', resolve));
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const first = await page.evaluate(async () => {
    const { createNeyviaStorage } = await import('/storage.js');
    const store = createNeyviaStorage(localStorage, indexedDB);
    localStorage.setItem('fluxio.chat.session_transcripts', '{"legacy":[]}');
    await store.initialize();
    let filled = false;
    try { localStorage.setItem('quota-fixture', 'x'.repeat(6 * 1024 * 1024)); } catch { filled = true; }
    const payload = JSON.stringify({ chat: [{ text: 'full response '.repeat(500000) }] });
    store.setItem('fluxio.chat.session_transcripts', payload);
    const oldCopyPresentBeforeCommit = localStorage.getItem('fluxio.chat.session_transcripts') !== null;
    await store.flush();
    return { filled, oldCopyPresentBeforeCommit, length: payload.length, intact: store.getItem('fluxio.chat.session_transcripts') === payload };
  });
  assert.equal(first.filled, true);
  assert.equal(first.oldCopyPresentBeforeCommit, true);
  assert.equal(first.intact, true);
  await page.reload();
  const second = await page.evaluate(async () => {
    const { createNeyviaStorage } = await import('/storage.js');
    const store = createNeyviaStorage(localStorage, indexedDB);
    await store.initialize();
    const length = store.getItem('fluxio.chat.session_transcripts').length;
    store.setItem('fluxio.chat.session_transcripts', '{}');
    await store.flush();
    store.removeItem('deleted-key');
    await store.flush();
    let errors = 0;
    const unavailable = createNeyviaStorage({ getItem: () => 'old', setItem() { throw new Error('quota'); } }, undefined, () => errors++);
    await unavailable.initialize();
    unavailable.setItem('key', 'unsaved');
    return { length, errors, memoryRetained: unavailable.getItem('key') === 'unsaved' };
  });
  assert.equal(second.length, first.length);
  assert.equal(second.memoryRetained, true);
  assert.equal(second.errors, 2);
  await page.reload();
  assert.equal(await page.evaluate(async () => {
    const { neyviaStorage } = await import('/storage.js');
    await neyviaStorage.initialize();
    return neyviaStorage.getItem('fluxio.chat.session_transcripts');
  }), '{}');
  console.log(JSON.stringify({ passed: true, bytesRecovered: first.length, checks: ['quota exceeded', 'old copy preserved until commit', 'full transcript survives reload', 'replacement survives reload', 'unavailable stores do not throw'] }));
} finally { await browser.close(); server.close(); }
