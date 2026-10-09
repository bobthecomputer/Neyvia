// Offline assets only; network-first prevents an old build masking a repair.
const CACHE='neyvia-app-__BUILD__';
const ASSETS=['./','./index.html','./app.bundle.js','./app.js','./model.js','./sdk.js','./identity.json','./manifest.webmanifest',__DETAILS_ASSETS__];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('neyvia-app-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{if(e.request.method==='GET'&&new URL(e.request.url).origin===location.origin)e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});
