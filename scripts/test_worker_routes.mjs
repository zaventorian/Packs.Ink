// test_worker_routes.mjs - the worker's route table, offline.
//
// Runs worker/index.js's real fetch handler against a stub asset layer that
// knows only "/" (the SPA shell) and checks what each kind of path gets back.
// Every failure here is silent in production: a trailing-slash route served the
// shell AT /decks/, so its relative styles.css resolved to /decks/styles.css and
// 404'd, and the page rendered unstyled with broken images (found 2026-10-07).

const mod = await import(new URL("../worker/index.js", import.meta.url).href);
const env = {
  ASSETS: {
    fetch: async (req) => new Response("shell", {
      status: new URL(req.url).pathname === "/" ? 200 : 404,
      headers: {"Content-Type": "text/html"},
    }),
  },
};
let fails = 0;
const check = async (what, url, wantStatus, wantLocation) => {
  const r = await mod.default.fetch(new Request(url), env, {});
  const loc = r.headers.get("Location");
  const ok = r.status === wantStatus && (wantLocation === undefined || loc === wantLocation);
  if(!ok){ fails++; console.log(`FAIL ${what}: ${url} -> ${r.status} ${loc || ""}`); }
  else console.log(`ok  ${what}`);
};

await check("a route is the SPA shell", "https://packs.ink/decks", 200);
await check("the root is the SPA shell", "https://packs.ink/", 200);
await check("a trailing slash goes to the canonical route, query kept",
  "https://packs.ink/decks/?deck=1&token=x", 301, "https://packs.ink/decks?deck=1&token=x");
await check("several trailing slashes too", "https://packs.ink/calendar//", 301, "https://packs.ink/calendar");
await check("a missing file is a real 404", "https://packs.ink/Logos/nope.png", 404);
await check("www goes to the apex", "https://www.packs.ink/decks?x=1", 301, "https://packs.ink/decks?x=1");

if(fails){ console.log(`\n${fails} failure(s)`); process.exit(1); }
console.log("\nworker routes: all passed");
