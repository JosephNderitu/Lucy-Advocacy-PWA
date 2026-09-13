// Copy to static/sw.js — served at the site root via the /sw.js route added
// to core/urls.py, so its scope covers the whole site, not just /static/.

const CACHE_NAME = 'nwc-advocates-v1';
const PRECACHE_URLS = [
  '/',
  '/static/images/static_images/logo-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

// Network-first: always try the live site first (so admin-panel changes,
// new case documents, etc. show up immediately), fall back to whatever's
// cached only if the network request fails (offline, or the free-tier host
// is asleep/cold-starting).
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy)).catch(() => {});
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});