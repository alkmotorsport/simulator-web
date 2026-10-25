/*
 * App instalable: guarda la web para abrirla sin red. Siempre intenta la red
 * primero (para no quedarse con una version vieja) y solo cachea lo propio:
 * nada del repo de datos ni de la raspi.
 */
const CACHE = 'telemetria-v1';
const BASE = ['./', 'index.html', 'style.css', 'plot.js', 'sensors.js', 'app.js', 'config.js',
  'cripto.js', 'repo.js', 'cuenta.js', 'logo.jpg', 'icon-192.png', 'icon-512.png', 'manifest.webmanifest'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(BASE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copia = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copia)); }
    return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true })));
});
