// packs.ink - service worker
// Bump CACHE_VERSION whenever Index.html or core assets change to force clients to update.
const CACHE_VERSION = 'packsink-v167';
const CORE_ASSETS = [
  '/',
  '/Index.html',
  '/styles.css?v=167',
  '/logo.js?v=167',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  '/apple-touch-icon.png',
  '/Logos/packs-ink-logo.png?v=5',
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
          // Only overwrite the offline app shell with a successful response for
          // the SPA itself — NOT a real non-SPA document (/privacy serves the
          // standalone privacy.html) and NOT a 404/5xx error page. Otherwise
          // visiting /privacy or hitting a mid-deploy hiccup would make that the
          // permanent offline shell.
          if (res.ok && url.pathname !== '/privacy' && url.pathname !== '/privacy.html') {
            const copy = res.clone();
            caches.open(CACHE_VERSION).then((c) => c.put('/Index.html', copy));
          }
          return res;
        })
        .catch(() => caches.match('/Index.html'))
    );
    return;
  }

  // App-shell styles/scripts (styles.css, logo.js): network-first, same as the
  // HTML — so a freshly-served (network-first) Index.html is NEVER paired with
  // a STALE cache-first stylesheet. That skew is what rendered the home page's
  // mover tiles at giant natural-image size after a deploy until the visitor
  // hard-refreshed. Falls back to cache only when the network is unreachable.
  if (url.origin === self.location.origin && /\/(styles\.css|logo\.js)$/.test(url.pathname)) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) { const copy = res.clone(); caches.open(CACHE_VERSION).then((c) => c.put(req, copy)); }
          return res;
        })
        // ignoreSearch so a fresh Index.html asking for styles.css?v=156 can
        // still fall back to a cached ?v=155 when offline mid-version-bump.
        .catch(() => caches.match(req, { ignoreSearch: true }))
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
