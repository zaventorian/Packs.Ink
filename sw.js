// packs.ink - service worker
// Bump CACHE_VERSION whenever Index.html or core assets change to force clients to update.
const CACHE_VERSION = 'packsink-v20';
const CORE_ASSETS = [
  '/',
  '/Index.html',
  '/styles.css',
  '/logo.js',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  '/apple-touch-icon.png',
  '/Logos/packs-ink-logo.png',
  '/Logos/logo transparent.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) =>
      Promise.all(CORE_ASSETS.map((a) => cache.add(a).catch(() => null)))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch strategy:
//   - Navigation requests (HTML): network-first, fall back to cached Index.html offline.
//   - Same-origin static assets: cache-first.
//   - Supabase API + TCGCSV + Lorcast + QR service: always network (no caching of dynamic data).
//   - Lorcast card images: stale-while-revalidate (cheap to revalidate, big offline win).
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;

  // Skip data APIs entirely — they should always hit the network.
  if (
    url.hostname.endsWith('supabase.co') ||
    url.hostname.endsWith('tcgcsv.com') ||
    url.hostname.endsWith('lorcast.com') ||
    url.hostname.endsWith('qrserver.com')
  ) return;

  // Navigation / HTML requests: network-first.
  if (req.mode === 'navigate' || (req.headers.get('accept') || '').includes('text/html')) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((c) => c.put('/Index.html', copy));
          return res;
        })
        .catch(() => caches.match('/Index.html'))
    );
    return;
  }

  // Lorcast card images: stale-while-revalidate.
  if (url.hostname.endsWith('lorcast.io')) {
    event.respondWith(
      caches.match(req).then((cached) => {
        const fetchPromise = fetch(req)
          .then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(CACHE_VERSION).then((c) => c.put(req, copy));
            }
            return res;
          })
          .catch(() => cached);
        return cached || fetchPromise;
      })
    );
    return;
  }

  // Same-origin assets: cache-first.
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(req).then((cached) => {
        return (
          cached ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(CACHE_VERSION).then((c) => c.put(req, copy));
            }
            return res;
          })
        );
      })
    );
    return;
  }

  // Cross-origin (Google Fonts, html2canvas CDN, etc.): stale-while-revalidate.
  event.respondWith(
    caches.match(req).then((cached) => {
      const fetchPromise = fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE_VERSION).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
