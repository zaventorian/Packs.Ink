// Routing for the Cloudflare deployment. Replaces Netlify's _redirects.
//
// Cloudflare's own _redirects file only does real redirects (301/302/…) — it
// supports neither the external proxy (`/img-proxy/* https://… 200`) nor the
// local rewrites (`/* /Index.html 200`) the site relies on, so all four rules
// live here as explicit code instead.
//
// Static assets that exist are served by the ASSETS binding before this worker
// is consulted, so /Logos/* and every hashed file need no rule. The pretty-URL
// handling of that layer also answers /privacy, /swiss and /ticker directly
// (it serves the matching .html), so the branches below for those paths are
// only reached if `run_worker_first` is ever enabled. What is left:
//   1. the two image proxies      (external origin — impossible in _redirects)
//   2. /lab/swiss → /swiss        (legacy path, redirect keeps the query)
//   3. SPA fallback → /Index.html (local rewrite, keeps the path in the URL)
//
// The old `404!` deny-list rules are gone on purpose: scripts/, supabase/ and
// the rest are no longer in the deployed bundle at all (scripts/build_dist.mjs
// is an include-list), so there is nothing to block. Route-shaped paths fall
// through to the SPA shell; file-shaped paths (a dot in the last segment) get
// a real 404 instead — see the fallback below for why.

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
  // A network-level fetch failure (CDN outage, DNS) rejects — without the
  // catch it propagates out of the worker as a Cloudflare 1101 exception
  // page instead of a clean upstream error.
  let res;
  try {
    res = await fetch(upstream, {
      method: request.method,
      cf: { cacheEverything: true, cacheTtl: IMG_CACHE_SECONDS },
    });
  } catch {
    return new Response("Upstream unreachable", { status: 502 });
  }

  if (!res.ok) return new Response("Upstream error", { status: res.status });

  // This is an IMAGE proxy. Whatever the upstream path resolves to is served
  // under the packs.ink origin, so anything that is not an image (an HTML
  // page, say) must never come back through here — with a text/html type it
  // would render as first-party content. Upstream art is image/* (a few CDNs
  // say octet-stream for AVIF, which is why that one is tolerated).
  const type = res.headers.get("Content-Type") || "";
  if (type && !/^(image\/|application\/octet-stream)/i.test(type)) {
    return new Response("Upstream error", { status: 502 });
  }

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
  if (type) headers.set("Content-Type", type);

  return new Response(res.body, { status: res.status, headers });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // A static site has nothing to POST to. Answering early also keeps the
    // request body untouched: the fallback below re-uses `request` as the init
    // for a second fetch, and a body that was already consumed by the first
    // ASSETS.fetch throws ("ReadableStream is disturbed") — a 500 for every
    // scanner POST or cross-origin preflight that lands on a route path.
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", {
        status: 405,
        headers: { Allow: "GET, HEAD" },
      });
    }

    for (const [prefix, origin] of PROXIES) {
      if (url.pathname.startsWith(prefix)) return proxyImage(request, prefix, origin);
    }

    // Pretty URL for the standalone policy. Google's OAuth verification crawler
    // reads this without running JavaScript, so it must serve the real static
    // file rather than the SPA shell. Fetch the PRETTY path, never
    // "/privacy.html": the asset layer 307s an explicit .html filename back to
    // the pretty URL, and returning that here would loop.
    if (url.pathname === "/privacy") {
      return env.ASSETS.fetch(new Request(new URL("/privacy", url.origin), request));
    }

    // Legacy path for the Swiss simulator (now /swiss, an asset the layer
    // serves directly). A redirect that keeps the query is what the old
    // "fetch /swiss.html" rewrite could not do: the asset layer 307'd it to
    // /swiss and the worker had already dropped ?embed=1 in building the URL.
    if (url.pathname === "/lab/swiss") {
      return Response.redirect(new URL("/swiss" + url.search, url.origin).toString(), 301);
    }

    // The stream ticker lives at /ticker with NO explicit route: Workers
    // Assets' pretty-URL handling serves ticker.html for it via the asset
    // fall-through below, with the query intact. Do not add a route that
    // fetches "/ticker.html" — the assets layer 307s that to /ticker.

    const asset = await env.ASSETS.fetch(request);
    if (asset.status !== 404) return asset;

    // A missing FILE gets a real 404. Serving the SPA shell for
    // /Logos/typo.png or /scanner/old.onnx returns 200 text/html under an
    // asset URL: the service worker's image branch would store that HTML in
    // the deploy-surviving image cache, a JSON fetch would throw on it, and
    // crawlers would index a duplicate page. SPA routes never carry a dot in
    // the path (deck/set/collection ids travel in the query), so "last
    // segment contains a dot" separates the two cleanly. /Index.html is kept
    // as a route on purpose: sw.js precaches that key as the offline shell.
    const last = url.pathname.slice(url.pathname.lastIndexOf("/") + 1);
    if (last.includes(".") && url.pathname !== "/Index.html") {
      return new Response("Not found", {
        status: 404,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    }

    // SPA fallback. 200, not a redirect, so the original path survives in
    // window.location.pathname for the client router to parse (/decks,
    // /screener, ?deck=…&token=… and friends).
    //
    // Fetches "/" rather than "/index.html": the asset layer canonicalises an
    // explicit index filename by 307-redirecting it to the directory, and a
    // redirect's (empty) body served as a 200 is a blank page.
    //
    // `request` is passed as the init so the client's conditional headers
    // (If-None-Match) travel with it. When the asset layer answers 304 the
    // 304 must be returned AS IS: re-wrapping it as a 200 hands the browser an
    // empty body for a reloaded /decks or /screener — a blank page — and the
    // service worker would then cache that empty document as the offline
    // shell. Anything else that is not a 200 (a 5xx from the asset layer) is
    // passed through too, rather than dressed up as success.
    const shell = await env.ASSETS.fetch(new Request(new URL("/", url.origin), request));
    if (shell.status === 304 || !shell.ok) return shell;
    return new Response(shell.body, { status: 200, headers: shell.headers });
  },
};
