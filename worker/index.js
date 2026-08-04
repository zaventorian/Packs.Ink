// Routing for the Cloudflare deployment. Replaces Netlify's _redirects.
//
// Cloudflare's own _redirects file only does real redirects (301/302/…) — it
// supports neither the external proxy (`/img-proxy/* https://… 200`) nor the
// local rewrites (`/* /Index.html 200`) the site relies on, so all four rules
// live here as explicit code instead.
//
// Static assets that exist are served by the ASSETS binding before this worker
// is consulted, so /Logos/* and every hashed file need no rule. What is left:
//   1. the two image proxies      (external origin — impossible in _redirects)
//   2. /privacy → /privacy.html   (local rewrite)
//   3. SPA fallback → /Index.html (local rewrite, keeps the path in the URL)
//
// The old `404!` deny-list rules are gone on purpose: scripts/, supabase/ and
// the rest are no longer in the deployed bundle at all (scripts/build_dist.mjs
// is an include-list), so there is nothing to block. They fall through to the
// SPA shell like any other unknown path.

// Prefix → upstream origin. The prefixes are load-bearing: the service worker
// caches image responses under these exact URLs and the Capacitor app rewrites
// them onto https://packs.ink, so renaming one invalidates every user's offline
// card art and breaks installed native builds. scripts/build_dist.mjs asserts
// Index.html still references both.
const PROXIES = [
  ["/img-proxy/", "https://cards.lorcast.io/"],
  ["/tcg-img-proxy/", "https://tcgplayer-cdn.tcgplayer.com/"],
];

// Lorcast content-addresses its art (a hash query param changes when a card is
// re-published), so a long immutable cache can't serve stale images.
const IMG_CACHE_SECONDS = 2592000; // 30 days

async function proxyImage(request, prefix, origin) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method not allowed", { status: 405 });
  }

  const url = new URL(request.url);
  const splat = url.pathname.slice(prefix.length);

  // `new URL("//evil.com/x", origin)` resolves to evil.com — a protocol-relative
  // splat would turn this into an open proxy. Resolve, then verify we are still
  // on the intended host before fetching anything.
  const upstream = new URL(splat + url.search, origin);
  if (upstream.origin !== new URL(origin).origin) {
    return new Response("Bad request", { status: 400 });
  }

  // Deliberately NOT forwarding the client's headers. These are third-party
  // CDNs; passing cookies or auth along would leak them, and varying on Accept
  // would fragment the edge cache for no benefit on static art.
  const res = await fetch(upstream, {
    method: request.method,
    cf: { cacheEverything: true, cacheTtl: IMG_CACHE_SECONDS },
  });

  if (!res.ok) return new Response("Upstream error", { status: res.status });

  // Build a clean response rather than passing upstream headers through, so a
  // Set-Cookie or a restrictive CORS header from the CDN can't reach the page.
  // ACAO:* is what keeps canvas exports untainted (deck/card posters, mover
  // tiles) and is required by the native builds, which load these cross-origin
  // from https://localhost with crossOrigin="anonymous".
  const headers = new Headers({
    "Cache-Control": `public, max-age=${IMG_CACHE_SECONDS}, immutable`,
    "Access-Control-Allow-Origin": "*",
    "X-Content-Type-Options": "nosniff",
  });
  const type = res.headers.get("Content-Type");
  if (type) headers.set("Content-Type", type);

  return new Response(res.body, { status: res.status, headers });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    for (const [prefix, origin] of PROXIES) {
      if (url.pathname.startsWith(prefix)) return proxyImage(request, prefix, origin);
    }

    // Pretty URL for the standalone policy. Google's OAuth verification crawler
    // reads this without running JavaScript, so it must serve the real static
    // file rather than the SPA shell.
    if (url.pathname === "/privacy") {
      return env.ASSETS.fetch(new Request(new URL("/privacy.html", url.origin), request));
    }

    const asset = await env.ASSETS.fetch(request);
    if (asset.status !== 404) return asset;

    // SPA fallback. 200, not a redirect, so the original path survives in
    // window.location.pathname for the client router to parse (/decks,
    // /screener, ?deck=…&token=… and friends).
    //
    // Fetches "/" rather than "/index.html": the asset layer canonicalises an
    // explicit index filename by 307-redirecting it to the directory, and a
    // redirect's (empty) body served as a 200 is a blank page.
    const shell = await env.ASSETS.fetch(new Request(new URL("/", url.origin), request));
    return new Response(shell.body, { status: 200, headers: shell.headers });
  },
};
