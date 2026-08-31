// Minimal offline-capable service worker (app shell cache).
const CACHE = 'whimo-web-v1';
const ASSETS = [
  './',
  './index.html',
  './styles.css',
  './manifest.webmanifest',
  './icons/icon.svg',
  './js/app.js',
  './js/config.js',
  './js/store.js',
  './js/geo.js',
  './js/share.js',
  './js/map.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const { request } = e;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  // Never cache map tiles or geocoding calls — always go to network.
  if (url.hostname.includes('tile.openstreetmap.org') ||
      url.hostname.includes('nominatim.openstreetmap.org')) {
    return;
  }
  // Cache-first for same-origin app shell, network fallback.
  if (url.origin === location.origin) {
    e.respondWith(
      caches.match(request).then((cached) =>
        cached || fetch(request).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy)).catch(() => {});
          return res;
        }).catch(() => cached)
      )
    );
  }
});
