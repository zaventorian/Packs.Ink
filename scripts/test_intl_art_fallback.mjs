// test_intl_art_fallback.mjs — a refused card image must not stay a broken tile.
//
//     node scripts/test_intl_art_fallback.mjs
//
// 2026-10-07: browsing the Japanese card grid asked Supabase storage for ~270
// images in a minute and it answered the rest with 429. The service worker
// handed that straight to the <img>, the tile had no fallback, and four cards
// showed their names instead of a picture until a reload. Two fixes, both
// pinned here by running the real code:
//
//   sw.js       versioned storage art (?v=) is final once cached (no re-ask on
//               every view), and a 429/5xx from storage is retried twice.
//   Index.html  a localized image that still fails is swapped for the English
//               art of the same printing, by one capturing error listener.
import { readFileSync } from "node:fs";
import vm from "node:vm";

let failed = 0;
const check = (name, ok, extra) => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}${!ok && extra !== undefined ? "  -> " + JSON.stringify(extra) : ""}`); };

// ── sw.js, run in a sandbox with fake caches / fetch / timers ──────────────
const swSrc = readFileSync(new URL("../sw.js", import.meta.url), "utf8");
const STORAGE = "https://umwqowkiatjjltologrd.supabase.co/storage/v1/object/public/card-art/";

function runSw({ url, statuses, hit = null, retryAfter = null }) {
  const handlers = {};
  const calls = [], delays = [], puts = [];
  let i = 0;
  const ctx = {
    self: { addEventListener: (t, f) => { handlers[t] = f; }, location: { origin: "https://packs.ink" }, skipWaiting() {}, clients: { claim() {} } },
    caches: {
      open: async () => ({ put: (req, res) => { puts.push(res.status); } }),
      match: async () => hit,
      keys: async () => [], delete: async () => true,
    },
    fetch: async (r) => {
      calls.push(r.mode);
      const s = statuses[Math.min(i++, statuses.length - 1)];
      const headers = retryAfter != null && s === 429 ? { "retry-after": String(retryAfter) } : {};
      return new Response("x", { status: s, headers });
    },
    setTimeout: (fn, ms) => { delays.push(ms); fn(); return 0; },
    Request, Response, URL, Math, Number, Set, Promise, console,
  };
  vm.createContext(ctx);
  vm.runInContext(swSrc, ctx);
  let responded = null;
  const event = {
    request: { url, method: "GET", mode: "no-cors", destination: "image" },
    respondWith: (p) => { responded = p; },
  };
  handlers.fetch(event);
  return { responded, calls, delays, puts };
}

const jaArt = STORAGE + "intl/ja/094_DLCS13_TodCopper_BestofFriends_JA.webp?v=5d0536167c";

{
  const r = runSw({ url: jaArt, statuses: [429, 429, 200] });
  const res = await r.responded;
  check("storage 429, 429, 200 -> the page gets the 200", res && res.status === 200, res && res.status);
  check("  ... after exactly three requests", r.calls.length === 3, r.calls.length);
  check("  ... all in CORS mode (the poster needs a CORS copy)", r.calls.every(m => m === "cors"), r.calls);
  check("  ... waiting ~2s, then ~6s", r.delays.length === 2 && r.delays[0] >= 2000 && r.delays[0] < 3500 && r.delays[1] >= 6000 && r.delays[1] < 7500, r.delays);
  check("  ... and only the good response is cached", r.puts.length === 1 && r.puts[0] === 200, r.puts);
}
{
  const r = runSw({ url: jaArt, statuses: [429] });
  const res = await r.responded;
  check("storage 429 three times -> the page sees the 429 (the client falls back)", res && res.status === 429, res && res.status);
  check("  ... no more than three requests", r.calls.length === 3, r.calls.length);
  check("  ... and a 429 is never cached", r.puts.length === 0, r.puts);
}
{
  const r = runSw({ url: jaArt, statuses: [503, 200] });
  const res = await r.responded;
  check("a 503 is retried too", res && res.status === 200 && r.calls.length === 2, [res && res.status, r.calls.length]);
}
for (const [ra, want] of [[3, 3000], [100, 15000]]) {
  const r = runSw({ url: jaArt, statuses: [429, 200], retryAfter: ra });
  await r.responded;
  check(`Retry-After: ${ra} -> waits ${want}ms`, r.delays[0] === want, r.delays);
}
{
  const r = runSw({ url: STORAGE + "intl/ja/x.webp?v=1", statuses: [404, 200] });
  const res = await r.responded;
  check("a 404 is NOT retried (the file is not there)", res && res.status === 404 && r.calls.length === 1, [res && res.status, r.calls.length]);
}
{
  const r = runSw({ url: "https://tcgplayer-cdn.tcgplayer.com/product/1_in_1000x1000.jpg", statuses: [429, 200] });
  const res = await r.responded;
  check("only storage art is retried (another host's 429 passes through)", res && res.status === 429 && r.calls.length === 1, [res && res.status, r.calls.length]);
}
{
  const hit = new Response("cached", { status: 200 });
  const r = runSw({ url: jaArt, statuses: [200], hit });
  const res = await r.responded;
  check("versioned storage art, cached -> served with NO request", res === hit && r.calls.length === 0, r.calls.length);
}
{
  const hit = new Response("cached", { status: 200 });
  const r = runSw({ url: STORAGE + "collectibles/pins/07.png", statuses: [200], hit });
  const res = await r.responded;
  await new Promise(ok => setImmediate(ok));
  check("UNversioned storage art, cached -> served, and still revalidated", res === hit && r.calls.length === 1, r.calls.length);
}

// ── Index.html: the English-art fallback ────────────────────────────────────
const idx = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const cut = (from, to) => {
  const a = idx.indexOf(from), b = idx.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error("could not find " + from);
  return idx.slice(a, b);
};
const locBlock = cut("let CARD_LOC = null;", "async function fetchCardLocalizations");
const locFn = cut("function localizeCatalog(rows, loc){", "\n// Separate cache for sealed-product prices");

class FakeImg {
  constructor(src) { this._src = src; }
  getAttribute(k) { return k === "src" ? this._src : null; }
  set src(v) { this._src = v; }
  get src() { return this._src; }
}
const listeners = [];
const win = { addEventListener: (t, f, capture) => listeners.push({ t, f, capture }) };
const cctx = { window: win, HTMLImageElement: FakeImg, Map, console };
vm.createContext(cctx);
vm.runInContext(locBlock + "\n" + locFn, cctx);

const errL = listeners.find(l => l.t === "error");
check("one window 'error' listener is registered", listeners.filter(l => l.t === "error").length === 1);
check("  ... in the CAPTURE phase (an <img> error does not bubble)", errL && errL.capture === true);

const JA = STORAGE + "intl/ja/097_DLCS13_Mushu_StealthyDragon_JA.webp?v=0bab8edf57";
const EN = "/img-proxy/card/digital/normal/crd_bf600b734e644e82ab7a90529c6f0cb8.avif?1783188871";
const rows = [{ card_id: "crd_mushu", img_small: EN, img_normal: EN, img_large: EN }];
cctx.rows = rows;
cctx.loc = new Map([["crd_mushu", { name: "ムーシュー", version: "姑息な龍", image_url: JA, match_how: "number" }]]);
const out = vm.runInContext("localizeCatalog(rows, loc)", cctx);
check("localizeCatalog still shows the localized art", out[0].img_normal === JA);

const fire = (target) => {
  let stopped = false;
  errL.f({ target, stopPropagation: () => { stopped = true; } });
  return stopped;
};
const img = new FakeImg(JA);
check("a failed localized image switches to the English art", fire(img) && img.getAttribute("src") === EN, img.getAttribute("src"));
check("  ... and if the English art fails too, the error reaches the surface", fire(img) === false && img.getAttribute("src") === EN);
const other = new FakeImg("/Logos/rarity/rare.svg");
check("an unrelated image is left alone", fire(other) === false && other.getAttribute("src") === "/Logos/rarity/rare.svg");
check("a non-image error target is ignored", fire({ tagName: "SCRIPT" }) === false);

// A row that never went through the catalog (matview, movers) uses cardDisplayImage.
const JA2 = STORAGE + "intl/ja/109_DLCS13_DashParr_SuperFast_JA.webp?v=3645274140";
const EN2 = "/img-proxy/card/digital/normal/crd_b184.avif?1";
vm.runInContext(`CARD_LOC = new Map([["crd_dash", {image_url: ${JSON.stringify(JA2)}}]]);`, cctx);
const shown = vm.runInContext(`cardDisplayImage("crd_dash", ${JSON.stringify(EN2)})`, cctx);
const img2 = new FakeImg(shown);
check("cardDisplayImage's localized art falls back the same way", shown === JA2 && fire(img2) && img2.getAttribute("src") === EN2, img2.getAttribute("src"));

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
