// Keep synchronous React initializers while storing large values outside the
// small localStorage quota. Never remove the old copy before the IDB commit.
export function createNeyviaStorage(nativeStorage, indexedDB, report = console.warn) {
  const values = new Map();
  let db;
  let queue = Promise.resolve();
  const transaction = (mode, action) => new Promise((resolve, reject) => {
    const tx = db.transaction("values", mode);
    action(tx.objectStore("values"));
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error("Storage transaction aborted"));
  });
  function enqueue(action) {
    queue = queue.then(action).catch(error => report("Local save failed; keep this window open until server sync completes.", error));
  }
  return {
    async initialize() {
      let expired = false;
      let deadline;
      const loading = async () => {
        const opened = await new Promise((resolve, reject) => {
          const request = indexedDB.open("neyvia-local-state", 1);
          request.onupgradeneeded = () => request.result.createObjectStore("values");
          request.onsuccess = () => {
            if (expired) { request.result.close(); return; }
            resolve(request.result);
          };
          request.onerror = () => reject(request.error);
          request.onblocked = () => reject(new Error("Local state database is blocked"));
        });
        if (expired) { opened.close(); return; }
        db = opened;
        opened.onversionchange = () => opened.close();
        await transaction("readonly", store => {
          const cursor = store.openCursor();
          cursor.onsuccess = () => {
            if (expired) return;
            const row = cursor.result;
            if (row) { values.set(row.key, row.value); row.continue(); }
          };
        });
      };
      try {
        await Promise.race([loading(), new Promise((_, reject) => {
          deadline = setTimeout(() => reject(new Error("Local state database did not respond")), 8000);
        })]);
        return { available: true };
      } catch (error) {
        expired = true;
        db?.close(); db = undefined;
        values.clear(); // Never expose an incomplete hydration as saved state.
        report("Large local storage unavailable", error);
        return { available: false };
      } finally { clearTimeout(deadline); }
    },
    getItem(key) {
      if (values.has(key)) return values.get(key);
      try { return nativeStorage.getItem(key); } catch { return null; }
    },
    setItem(key, input) {
      const value = String(input);
      const alreadyInDatabase = values.has(key);
      values.set(key, value);
      if (!alreadyInDatabase && value.length < 262144) {
        try { nativeStorage.setItem(key, value); values.delete(key); return; } catch { /* Try the larger store. */ }
      }
      if (!db) {
        try { nativeStorage.setItem(key, value); } catch (error) { report("Local save failed; keep this window open until server sync completes.", error); }
        return;
      }
      enqueue(async () => {
        await transaction("readwrite", store => store.put(value, key));
        try { nativeStorage.removeItem(key); } catch { /* The durable copy is safe. */ }
      });
    },
    removeItem(key) {
      values.set(key, null);
      try { nativeStorage.removeItem(key); } catch { /* Keep removal in memory. */ }
      if (db) enqueue(() => transaction("readwrite", store => store.put(null, key)));
    },
    flush() { return queue; },
  };
}

export const neyviaStorage = createNeyviaStorage(
  { getItem: key => globalThis.localStorage.getItem(key), setItem: (key, value) => globalThis.localStorage.setItem(key, value), removeItem: key => globalThis.localStorage.removeItem(key) },
  globalThis.indexedDB,
);
