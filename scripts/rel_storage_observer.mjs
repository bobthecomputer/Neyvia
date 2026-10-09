// Finite facts for the authored CL checks; never read the user's browser data.
import { createNeyviaStorage } from '../web/src/neyvia/neyviaStorage.js';
import { normalizeProject } from '../web/src/neyvia/imagePlaygroundState.js';
const legacy = new Map([['large', 'L'.repeat(270000)]]);
const native = map => ({ getItem: key => map.get(key) ?? null,
  setItem: (key, value) => map.set(key, value), removeItem: key => map.delete(key) });
const durable = new Map([['hydrated', 'saved-db-value']]);
const db = {
  closed: false, close() { this.closed = true; },
  transaction(name, mode) {
    const tx = { objectStore() { return {
      openCursor() {
        const request = {}, rows = [...durable]; let at = 0;
        const next = () => queueMicrotask(() => {
          request.result = at < rows.length ? { key: rows[at][0], value: rows[at++][1], continue: next } : null;
          request.onsuccess?.();
          if (!request.result) queueMicrotask(() => tx.oncomplete?.());
        });
        next(); return request;
      },
      put(value, key) { setTimeout(() => { durable.set(key, value); tx.oncomplete?.(); }, 20); },
    }; } };
    return tx;
  },
};
const available = { open() { const request = {};
  queueMicrotask(() => { request.result = db; request.onsuccess?.(); }); return request; } };
const storage = createNeyviaStorage(native(legacy), available, () => {});
const initialized = await storage.initialize();
const facts = { successfulInitialization: initialized.available, hydratedValue: storage.getItem('hydrated') };
const fresh = normalizeProject();
facts.imageFreshEmpty = fresh.layers.length === 0 && fresh.history.length === 0 && fresh.designReferences.length === 0 && fresh.prompt.text === '';
const existing = { title: 'keeper', layers: [{id:'owned-layer',src:'owned-source'}],
  designReferences: [{id:'owned-reference'}], history: [{ id:'owned-receipt', requestId:'owned-request',
    provider:'local file', status:'imported',outputArtifactPath:'fixture.png',receipt:{sourceSha256:'a'.repeat(64)}}] };
const saved = normalizeProject(existing);
facts.imageSavedPreserved = saved.title === 'keeper' && saved.layers[0].id === 'owned-layer' &&
  saved.designReferences.length === 1 && saved.designReferences[0].id === 'owned-reference' && saved.history[0].id === 'owned-receipt';
facts.imageEmptyStaysEmpty = normalizeProject({layers:[],history:[],designReferences:[]}).layers.length === 0;
const replacement = 'N'.repeat(270000);
storage.setItem('large', replacement);
facts.legacyBeforeCommit = legacy.get('large') === 'L'.repeat(270000);
await storage.flush();
facts.committedValue = durable.get('large') === replacement;
facts.legacyRemovedAfterCommit = !legacy.has('large');
const retained = new Map([['original', 'keeper']]); let request, warned = false;
const hanging = { open() { request = {}; return request; } };
const blocked = createNeyviaStorage(native(retained), hanging, () => { warned = true; });
const began = performance.now();
facts.timeoutUnavailable = !(await blocked.initialize()).available;
facts.durationMs = Math.round(performance.now() - began);
facts.legacyRetained = retained.get('original') === 'keeper';
facts.warningReported = warned;
const late = { close() { this.closed = true; } };
request.result = late; request.onsuccess();
facts.lateDatabaseClosed = late.closed === true;
facts.lateHydrationIgnored = blocked.getItem('hydrated') === null;
console.log(JSON.stringify(facts));
