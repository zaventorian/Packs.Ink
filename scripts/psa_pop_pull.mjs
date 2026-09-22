// psa_pop_pull.mjs — pull PSA population counts for the English Lorcana sets.
//
//     node scripts/psa_pop_pull.mjs --dry-run       # discover sets, pull nothing
//     node scripts/psa_pop_pull.mjs                 # discover + pull every set
//     node scripts/psa_pop_pull.mjs --set 245613    # one set
//
// Requires a Chrome started by graded_run.ps1 (or the same flags) with a PSA
// tab open and SIGNED IN — every PSA pop page below /Pop redirects to
// collectors.com/signin otherwise, which this treats as a hard stop.
//
// ── How it talks to PSA, and why this shape ────────────────────────────────
// Every request is issued by the ALREADY-OPEN PAGE, via its own fetch(): same
// origin, same cookies, same TLS fingerprint, same headers a click produces.
// Nothing here navigates, clicks or types, and the CDP side sends only
// Runtime.evaluate — never Runtime.enable, which is the CDP-presence tell that
// Playwright's connect_over_cdp gives off and that Cloudflare-class bot
// management looks for. PSA is demonstrably Cloudflare-fronted (a datacenter IP
// gets its interstitial), so that distinction is the whole reason for the raw
// socket below instead of Playwright.
//
// ⚠ PAGE_SIZE is 300 because that is what the site's own table asks for. A
// bigger page would fetch every set in one request and is precisely the kind of
// off-pattern parameter that stands out in a log; two ordinary requests are
// cheaper than one unusual one.
//
// ⚠ Requests are SEQUENTIAL with a jittered pause. Never parallelise this. A
// full refresh is ~28 requests, so there is nothing to gain and an obvious
// burst pattern to lose.
//
// ⚠ It STOPS on the first sign of a wall — a non-200, a sign-in redirect, or a
// challenge-shaped body — and never retries. Hammering a soft check is what
// turns it into an account-level flag, and this account is Zaven's real one.
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "pop_output");
const CDP = process.env.PSA_CDP || "http://localhost:9222";

const PAGE_SIZE = 300;          // see note above — match the site's own table
const CATEGORY_ID = "156940";   // TCG Cards
const DELAY_MS = [2500, 5200];  // jittered pause between requests

// Lorcana's English sets are the ones whose slug carries `-en-`; the French and
// German printings are separate sets on PSA (`-fr-`, `-de-`) and are a different
// market we do not track. The Demo Deck, Errata and Oversized entries are
// deliberately IN — they are English product, just unusual.
const EN_SLUG = /disney-lorcana[a-z-]*-en-/i;
const YEARS = [
  { year: 2023, headingID: 227655 },
  { year: 2024, headingID: 256988 },
  { year: 2025, headingID: 290436 },
  { year: 2026, headingID: 326969 },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = () => DELAY_MS[0] + Math.random() * (DELAY_MS[1] - DELAY_MS[0]);

class Wall extends Error {}

// ── A CDP session that only ever evaluates ─────────────────────────────────
async function cdpSession(match) {
  const tabs = await (await fetch(CDP + "/json/list")).json();
  const tab = tabs.find((t) => t.type === "page" && (t.url || "").includes(match));
  if (!tab) {
    const open = tabs.filter((t) => t.type === "page").map((t) => "  " + t.url).join("\n");
    throw new Error(`no open tab matching ${match}\nopen tabs:\n${open || "  (none)"}`);
  }
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = () => rej(new Error("could not attach to " + tab.url));
  });
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    const p = pending.get(m.id);
    if (!p) return;
    pending.delete(m.id);
    if (m.error) return p.rej(new Error(JSON.stringify(m.error)));
    const r = m.result;
    if (r.exceptionDetails) return p.rej(new Error(r.exceptionDetails.text));
    p.res(r.result?.value);
  };
  return {
    url: tab.url,
    evaluate(expression) {
      const myId = ++id;
      return new Promise((res, rej) => {
        pending.set(myId, { res, rej });
        setTimeout(() => {
          if (pending.delete(myId)) rej(new Error("CDP timeout"));
        }, 45000);
        ws.send(JSON.stringify({
          id: myId,
          method: "Runtime.evaluate",
          params: { expression, returnByValue: true, awaitPromise: true },
        }));
      });
    },
    close: () => ws.close(),
  };
}

// A body that is a sign-in page or a challenge means STOP, not retry.
function assertNotWall(res, what) {
  if (!res) throw new Wall(`${what}: no response`);
  if (res.status !== 200) throw new Wall(`${what}: HTTP ${res.status}`);
  const blob = (res.finalUrl || "") + " " + String(res.bodyHead || "").toLowerCase();
  for (const bit of ["signin", "/login", "captcha", "attention required",
                     "you have been blocked", "cloudflare ray id",
                     "checking your browser", "unusual traffic"]) {
    if (blob.toLowerCase().includes(bit)) throw new Wall(`${what}: looks like a wall (${bit})`);
  }
}

// ── Phase 1: which English Lorcana sets exist, per year ────────────────────
// The year pages are ordinary server-rendered HTML with every set inline (their
// DataTable is client-side), so one GET each gives the whole list. Fetching the
// document rather than navigating to it is also ~30 fewer requests: no scripts,
// styles or images come along.
const discoverExpr = (path) => `
(async () => {
  const r = await fetch(${JSON.stringify(path)}, {credentials: "same-origin"});
  const text = await r.text();
  const doc = new DOMParser().parseFromString(text, "text/html");
  const sets = Array.from(doc.querySelectorAll('a[href*="disney-lorcana"]')).map(a => {
    const href = a.getAttribute("href") || "";
    const m = href.match(/\\/(\\d+)\\/?$/);
    return {name: (a.textContent || "").trim().replace(/\\s+/g, " "),
            path: href, headingID: m ? Number(m[1]) : null};
  }).filter(s => s.headingID);
  return {status: r.status, finalUrl: r.url, bodyHead: text.slice(0, 400), sets};
})()`;

// ── Phase 2: one set's rows, paged exactly as the site pages them ──────────
const itemsExpr = (headingID, start) => `
(async () => {
  const body = new URLSearchParams({
    draw: "1", start: ${JSON.stringify(String(start))}, length: ${JSON.stringify(String(PAGE_SIZE))},
    search: "", headingID: ${JSON.stringify(String(headingID))},
    categoryID: ${JSON.stringify(CATEGORY_ID)}, isPSADNA: "false"
  });
  const r = await fetch("/Pop/GetSetItems", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
      "X-Requested-With": "XMLHttpRequest"
    },
    body: body.toString()
  });
  const text = await r.text();
  let json = null;
  try { json = JSON.parse(text); } catch (e) {}
  return {status: r.status, finalUrl: r.url, bodyHead: text.slice(0, 400),
          recordsTotal: json && json.recordsTotal, rows: json && (json.data || json.aaData)};
})()`;

async function main() {
  const argv = process.argv.slice(2);
  const dryRun = argv.includes("--dry-run");
  const only = argv.includes("--set") ? Number(argv[argv.indexOf("--set") + 1]) : null;

  mkdirSync(OUT, { recursive: true });
  const s = await cdpSession("psacard.com");
  console.log("attached to: " + s.url);

  try {
    // Phase 1
    let sets = [];
    for (const y of YEARS) {
      const res = await s.evaluate(discoverExpr(`/pop/tcg-cards/${y.year}/${y.headingID}`));
      assertNotWall(res, `year ${y.year}`);
      const seen = new Set();
      const mine = res.sets.filter((x) => {
        if (!EN_SLUG.test(x.path) || seen.has(x.headingID)) return false;
        seen.add(x.headingID);
        return true;
      }).map((x) => ({ ...x, year: y.year }));
      sets.push(...mine);
      const skipped = new Set(res.sets.filter((x) => !EN_SLUG.test(x.path)).map((x) => x.headingID));
      console.log(`  ${y.year}: ${mine.length} English Lorcana sets (${skipped.size} non-English skipped)`);
      await sleep(jitter());
    }
    sets.sort((a, b) => a.year - b.year || a.headingID - b.headingID);
    writeFileSync(join(OUT, "psa_lorcana_sets.json"), JSON.stringify(sets, null, 2));
    console.log(`\n${sets.length} English Lorcana sets total -> pop_output/psa_lorcana_sets.json`);
    for (const x of sets) console.log(`  ${x.headingID}  ${x.name}`);

    if (dryRun) { console.log("\n--dry-run: pulling nothing."); return; }

    // Phase 2
    const targets = only ? sets.filter((x) => x.headingID === only) : sets;
    if (only && !targets.length) throw new Error(`set ${only} is not an English Lorcana set`);
    const stamp = new Date().toISOString().slice(0, 10);
    let grand = 0;

    for (const set of targets) {
      const file = join(OUT, `psa_pop_${set.headingID}_${stamp}.json`);
      if (existsSync(file)) { console.log(`\n${set.name}: already pulled today, skipping`); continue; }
      console.log(`\n${set.name} (heading ${set.headingID})`);
      const rows = [];
      let total = null;
      for (let start = 0; total === null || start < total; start += PAGE_SIZE) {
        await sleep(jitter());
        const res = await s.evaluate(itemsExpr(set.headingID, start));
        assertNotWall(res, set.name);
        if (!Array.isArray(res.rows)) throw new Wall(`${set.name}: no rows in response`);
        total = res.recordsTotal ?? res.rows.length;
        rows.push(...res.rows);
        console.log(`  ${Math.min(start + PAGE_SIZE, total)}/${total}`);
        if (!res.rows.length) break;
      }
      writeFileSync(file, JSON.stringify(
        { set, pulled_at: new Date().toISOString(), recordsTotal: total, rows }, null, 2));
      grand += rows.length;
    }
    console.log(`\nDone: ${grand} rows across ${targets.length} sets -> ${OUT}`);
  } catch (e) {
    if (e instanceof Wall) {
      console.error(`\nSTOPPED: ${e.message}`);
      console.error("Not retrying. Check that Chrome is still signed in to PSA, clear anything");
      console.error("it is showing you by hand, and re-run — finished sets are skipped.");
      process.exitCode = 3;
    } else {
      console.error("\n" + e.message);
      process.exitCode = 1;
    }
  } finally {
    s.close();
  }
}

await main();
