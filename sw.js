// packs.ink - service worker
// Bump CACHE_VERSION whenever Index.html or core assets change to force clients to update.
const CACHE_VERSION = 'packsink-v321';
// Card art + other images live in their own cache that is NOT wiped on
// deploys. Before this existed, every CACHE_VERSION bump threw away every
// runtime-cached card image, so devices never accumulated art for offline
// use. Image bytes at a given URL are immutable (Lorcast/TCGplayer art URLs
// never change content), so keeping them across app versions is safe. The
// in-app "offline images" downloader writes into this same cache.
const IMG_CACHE = 'packsink-img-v1';
const CORE_ASSETS = [
  '/',
  '/Index.html',
  // Vendored core libs (formerly unpkg). Precached so the app boots offline and
  // can never be left half-loaded by a CDN outage. ?v= busts on a re-vendor.
  '/vendor/react.production.min.js?v=254',
  '/vendor/react-dom.production.min.js?v=254',
  '/vendor/htm.js?v=254',
  '/vendor/supabase.js?v=254',
  '/styles.css?v=320',
  '/logo.js?v=253',
  // scanner*.js intentionally NOT precached (2026-07-14): the scanner is
  // admin-gated to ~2 users — they runtime-cache on first use instead of
  // costing every visitor ~58KB at SW install.
  '/manifest.json',
  '/icon-192.png?v=5',
  '/icon-512.png?v=5',
  '/apple-touch-icon.png?v=5',
  '/Logos/packs-ink-logo.png?v=5'
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
      Promise.all(keys.filter((k) => k !== CACHE_VERSION && k !== IMG_CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Cache a response if it's usable. Cross-origin <img> loads are no-cors →
// the response is "opaque" (status 0, res.ok === false) but still perfectly
// renderable and cacheable. The old `if (res.ok)` guard silently rejected
// every opaque response, which meant NO card art was ever cached — the image
// branch below was dead code. Network errors still reject the fetch promise,
// so a true failure is never cached; the residual risk is caching an opaque
// 404, which the next online revalidation overwrites.
const cacheable = (res) => res && (res.ok || res.type === 'opaque');

// Fetch strategy:
//   - Navigation requests (HTML): network-first, fall back to cached Index.html offline.
//   - Images (card art on lorcast.io / tcgplayer-cdn / etc + same-origin art):
//     stale-while-revalidate into the deploy-surviving IMG_CACHE.
//   - Same-origin static assets: cache-first.
//   - Supabase API + TCGCSV + Lorcast API + QR service: always network (no caching of dynamic data).
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;

  // Images — card art (same-origin /img-proxy/ + /tcg-img-proxy/, Logos,
  // ink/rarity icons, direct tcgplayer-cdn art, Supabase-storage prestaged
  // art, lorcast.io). Stale-while-revalidate into IMG_CACHE so art
  // accumulates on the device and survives deploys. This branch runs BEFORE
  // the data-API skip on purpose: prestaged card art is served from Supabase
  // storage, and PostgREST/data responses are never destination:"image" so
  // they still fall through to the skip below.
  if (req.destination === 'image' || url.hostname.endsWith('lorcast.io')) {
    event.respondWith(
      caches.open(IMG_CACHE).then((cache) =>
        // Global match (not cache.match) so precached entries in the
        // versioned cache (icons, wordmark) also satisfy image requests.
        caches.match(req).then((cached) => {
          const fetchPromise = fetch(req)
            .then((res) => {
              if (cacheable(res)) cache.put(req, res.clone());
              return res;
            })
            .catch(() => cached);
          return cached || fetchPromise;
        })
      )
    );
    return;
  }

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
        // Fall back to '/' when the '/Index.html' key is absent. On Cloudflare
        // the asset layer 307s /Index.html -> /, so the CORE_ASSETS precache of
        // it fails (cache.add rejects redirected responses) and this key only
        // exists once an intercepted navigation has populated it above. '/' is
        // precached successfully either way, so this closes the window between
        // SW install and the first intercepted navigation, where an offline
        // visitor would otherwise get nothing.
        .catch(() => caches.match('/Index.html').then((r) => r || caches.match('/')))
    );
    return;
  }

  // App-shell styles/scripts (styles.css, logo.js): network-first, same as the
  // HTML — so a freshly-served (network-first) Index.html is NEVER paired with
  // a STALE cache-first stylesheet. That skew is what rendered the home page's
  // mover tiles at giant natural-image size after a deploy until the visitor
  // hard-refreshed. Falls back to cache only when the network is unreachable.
  if (url.origin === self.location.origin && /\/(styles\.css|logo\.js|scanner\.js|scanner-cv\.js|scanner-worker\.js|scanner-ocr-worker\.js)$/.test(url.pathname)) {
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

  // Cross-origin non-image (Google Fonts CSS, etc.): stale-while-revalidate.
  event.respondWith(
    caches.match(req).then((cached) => {
      const fetchPromise = fetch(req)
        .then((res) => {
          if (cacheable(res)) {
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
