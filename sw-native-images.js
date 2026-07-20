// Image-only service worker for the NATIVE (Capacitor) app.
//
// This is a deliberate, scoped exception to the "no service worker in native"
// rule (which exists to avoid app-SHELL staleness). This SW never touches the
// shell: it only calls respondWith() for card-image requests, letting every
// other request (the bundled shell, Supabase API, plugins) pass through to the
// browser untouched. Its sole job is to SERVE images the app pre-downloaded
// into `packsink-img-v1` so the full catalog renders offline — the WebView's
// own HTTP cache can't be relied on (LRU-evicts under storage pressure) and
// CacheStorage needs a fetch handler to be read back.
//
// Populated by startOfflineImagePack() in Index.html (same cache name, same
// URL keys). Cache-first with network fallback that also warms the cache for
// images the user browses before the bulk download reaches them.

const IMG_CACHE = "packsink-img-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

function isImageRequest(req){
  const u = req.url;
  if(u.includes("/img-proxy/") || u.includes("/tcg-img-proxy/")) return true;
  if(u.includes("cards.lorcast.io") || u.includes("tcgplayer-cdn.tcgplayer.com")) return true;
  if(req.destination === "image") return true;
  return /\.(png|jpe?g|webp|avif|gif)(\?|$)/i.test(u);
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if(req.method !== "GET" || !isImageRequest(req)) return; // untouched — browser handles it

  event.respondWith((async () => {
    const cache = await caches.open(IMG_CACHE);
    const cached = await cache.match(req) || await cache.match(req.url);
    if(cached) return cached;
    try {
      const res = await fetch(req);
      // ok OR opaque (cross-origin no-cors <img> loads are opaque, res.ok===false)
      if(res && (res.ok || res.type === "opaque")){
        cache.put(req, res.clone()).catch(() => {});
      }
      return res;
    } catch(e){
      const any = await cache.match(req.url);
      return any || Response.error();
    }
  })());
});
