// test_sw_install.mjs — a service-worker install must not succeed without the app shell.
//
//     node scripts/test_sw_install.mjs
//
// Runs the real sw.js install handler in a sandbox with a fake Cache API. The
// handler used to swallow every precache failure, so an update on a flaky
// connection installed a worker WITHOUT the shell; activate then deleted the
// old cache and the controllerchange reload landed on nothing offline (review,
// 2026-10-06). Now the shell, the vendored libraries and the stylesheet are
// all-or-nothing (the install fails and the working worker stays), while
// icons, the manifest and the wordmark stay best-effort.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync(new URL("../sw.js", import.meta.url), "utf8");
let failed = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) console.log(`        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`);
};

async function install(failing) {
  const handlers = {};
  const stored = new Set();
  const fail = (u) => failing.some((f) => u.startsWith(f));
  const cache = {
    add: async (u) => { if (fail(u)) throw new Error("net"); stored.add(u); },
    addAll: async (us) => { if (us.some(fail)) throw new Error("net"); us.forEach((u) => stored.add(u)); },
    put: async () => {}, match: async () => undefined, keys: async () => [], delete: async () => true,
  };
  const self = {
    addEventListener: (t, h) => { handlers[t] = h; },
    skipWaiting: () => {}, clients: { claim: () => {} }, location: { origin: "https://packs.ink" },
  };
  const ctx = vm.createContext({ self, caches: { open: async () => cache, keys: async () => [], match: async () => undefined },
    URL, Request, Response, Headers, fetch: async () => { throw new Error("no network"); }, console });
  vm.runInContext(src, ctx);
  let p;
  handlers.install({ waitUntil: (x) => { p = x; } });
  try { await p; return { ok: true, stored }; } catch { return { ok: false, stored }; }
}

check("a clean install succeeds", (await install([])).ok, true);
check("the shell failing FAILS the install (the working worker stays)", (await install(["/"])).ok, false);
check("a vendored library failing fails it", (await install(["/vendor/react-dom"])).ok, false);
check("the stylesheet failing fails it", (await install(["/styles.css"])).ok, false);
const icon = await install(["/icon-512.png"]);
check("an icon failing does NOT fail it", icon.ok, true);
check("...and everything else is still cached", icon.stored.has("/") && icon.stored.has("/manifest.json"), true);
check("the manifest failing does not fail it", (await install(["/manifest.json"])).ok, true);

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
