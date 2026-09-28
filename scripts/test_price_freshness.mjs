// test_price_freshness.mjs — a price move has to be OBSERVED inside its window.
//
//     node scripts/test_price_freshness.mjs
//
// Found 2026-09-27: price_movers reported a SKU's last day-over-day change as its
// "1D" move forever once the SKU stopped updating. Cruella De Vil - Miserable As
// Usual (Promo Set 1, Holofoil) led the home Promo Movers, the Screener's NM
// Market view, the ticker and the Discord digest at "+108%" — a Jun 1 -> Aug 9
// move, 48 days after its last market price. Migration 172 fixed the matview.
// The same flaw lived in the two CLIENT-side Δ% helpers, which anchored every
// window on the series' own last sample: the card page said Cruella moved +108%
// "1D" and Stitch - Rock Star +102% "1M", 81 days after its last market price.
//
// Extracts the real code out of Index.html (house pattern) and replays the real
// dates. Every way this breaks is silent — a number that looks like any other.
import { readFileSync, readdirSync } from "node:fs";

const root = new URL("../", import.meta.url);
const src = readFileSync(new URL("Index.html", root), "utf8").replace(/\r\n/g, "\n");
const NL = "\n";
const grab = (a, b) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error("missing marker: " + a);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error("missing end: " + b);
  return src.slice(i, j + b.length);
};
const mod = await import("data:text/javascript," + encodeURIComponent([
  grab("const CARD_DELTA_WINDOWS = [", NL + "];"),
  grab("const computeSeriesDeltas = (rows, field, asOf) => {", NL + "};"),
  grab("let _catalogPriceDate = null;", "const catalogPriceDate = () => _catalogPriceDate;"),
  grab("const seriesPricedOn = (rows, field, asOf) => {", NL + "};"),
  grab("function computeSealedDeltas(history, opts){", NL + "}"),
  "export {CARD_DELTA_WINDOWS, computeSeriesDeltas, setCatalogPriceDate, catalogPriceDate, seriesPricedOn, computeSealedDeltas};",
].join(NL)));

let failed = 0;
const ok = (name, cond, detail) => {
  if (!cond) failed++;
  console.log((cond ? "PASS  " : "FAIL  ") + name + (cond ? "" : "  " + JSON.stringify(detail)));
};
const near = (a, b) => a != null && b != null && Math.abs(a - b) < 1e-6;
const DAY = 86400000;
const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
const daily = (from, to, fn) => {
  const out = [];
  for (let t = Date.parse(from); t <= Date.parse(to); t += DAY) out.push({date: iso(t), ...fn(iso(t))});
  return out;
};

const TODAY = "2026-09-27";
// Cruella's real market series: $600 through Jun 1, gone, then one $1,250 on Aug 9.
const cruella = [
  ...daily("2026-05-15", "2026-06-01", () => ({market_price: 600, low_price: 1250})),
  {date: "2026-08-09", market_price: 1250, low_price: 1250},
  {date: "2026-09-04", market_price: null, low_price: 0.25},
];
// A card priced every day through today.
const fresh = daily("2025-09-01", TODAY, (d) => ({market_price: 10 + (Date.parse(d) - Date.parse("2025-09-01")) / DAY / 100}));

// ── computeSeriesDeltas: the card page ─────────────────────────────────────
{
  const old = mod.computeSeriesDeltas(cruella, "market_price");
  ok("without asOf it keeps the old anchoring (and the old phantom)", near(old.byWin["1d"], 108.3333333), old.byWin);
  const d = mod.computeSeriesDeltas(cruella, "market_price", TODAY);
  ok("Cruella: no 1D / 1W / 1M move — her last market price is 49 days old",
    d.byWin["1d"] === null && d.byWin["1w"] === null && d.byWin["1m"] === null, d.byWin);
  ok("…but 3M, which DOES contain it, compares against the price 90 days back ($600)",
    near(d.byWin["3m"], (1250 - 600) / 600 * 100), d.byWin["3m"]);
  ok("…and the last known price is still reported", d.now === 1250, d.now);
  const lo = mod.computeSeriesDeltas(cruella, "low_price", TODAY);
  ok("Low: the Sep 4 listing is 23 days old — no 1D / 1W, a 1M move", lo.byWin["1d"] === null &&
    lo.byWin["1w"] === null && near(lo.byWin["1m"], (0.25 - 1250) / 1250 * 100), lo.byWin);

  const a = mod.computeSeriesDeltas(fresh, "market_price");
  const b = mod.computeSeriesDeltas(fresh, "market_price", TODAY);
  ok("a card priced today gets exactly the values it always had, every window",
    JSON.stringify(a) === JSON.stringify(b), {a: a.byWin, b: b.byWin});
  ok("…including a real 1D move", a.byWin["1d"] > 0, a.byWin["1d"]);
  const early = mod.computeSeriesDeltas(fresh, "market_price", "2026-09-20");
  ok("an asOf OLDER than the data never reaches past it (a session that outlived an ETL)",
    JSON.stringify(early) === JSON.stringify(a), early.byWin);
  const yday = fresh.slice(0, -1);
  const y = mod.computeSeriesDeltas(yday, "market_price", TODAY);
  ok("priced yesterday, not today: no 1D, but 1W still stands", y.byWin["1d"] === null && y.byWin["1w"] !== null, y.byWin);
  ok("an empty series is still empty", JSON.stringify(mod.computeSeriesDeltas([], "market_price", TODAY)) ===
    JSON.stringify({now: null, byWin: {}}));
}

// ── seriesPricedOn: the price-standing chip ────────────────────────────────
ok("standing speaks for a series priced today", mod.seriesPricedOn(fresh, "market_price", TODAY));
ok("…not for one last priced weeks ago", !mod.seriesPricedOn(cruella, "market_price", TODAY));
ok("…judged on the FIELD, not the row: Sep 4 had a Low but no market price",
  !mod.seriesPricedOn(cruella, "market_price", "2026-09-04") && mod.seriesPricedOn(cruella, "low_price", "2026-09-04"));
ok("…and with no asOf it says what it has", mod.seriesPricedOn(cruella, "market_price", null));

// ── the catalog date stamp ─────────────────────────────────────────────────
ok("catalogPriceDate() is null until the catalog loads", mod.catalogPriceDate() === null);
mod.setCatalogPriceDate(TODAY);
ok("…and returns what App stamped", mod.catalogPriceDate() === TODAY);
mod.setCatalogPriceDate(undefined);
ok("…and clears on an empty stamp (a pre-latestDate cache)", mod.catalogPriceDate() === null);

// ── computeSealedDeltas: sealed tiles, Screener Sealed, Sealed Movers, modal ─
{
  const pid = (id, rows) => rows.map(r => ({...r, tcgplayer_product_id: id, printing: "Normal"}));
  // A case last listed Aug 26 (the real Shimmering Skies Trove Case shape).
  const gone = pid(2, [...daily("2026-05-01", "2026-07-27", () => ({low_price: 230, market_price: 238})),
                        {date: "2026-08-26", low_price: 246.33, market_price: 245}]);
  const live = pid(1, fresh);
  const both = mod.computeSealedDeltas([...live, ...gone]);
  const g = both.find(r => r.tcgplayer_product_id === 2), l = both.find(r => r.tcgplayer_product_id === 1);
  ok("a batch guards itself: the stale case has no 1D / 1W / 1M", g.pct_1d === null && g.pct_7d === null &&
    g.pct_30d === null && g.mkt_pct_30d === null, g);
  ok("…while its 3M, which contains Aug 26, still reads", g.pct_90d !== null, g.pct_90d);
  const [alone] = mod.computeSealedDeltas(live);
  ok("…and the live product in that batch is untouched", JSON.stringify(alone) === JSON.stringify(l), {alone, l});
  const [lone] = mod.computeSealedDeltas(gone);
  ok("a lone series is its own newest date (the documented sealed behaviour)", lone.pct_30d !== null, lone.pct_30d);
  const [modal] = mod.computeSealedDeltas(gone, {asOf: TODAY});
  ok("…and the single-product modal guards it by passing asOf", modal.pct_1d === null && modal.pct_30d === null, modal);
  const [back] = mod.computeSealedDeltas(live, {asOf: "2026-09-01"});
  ok("an asOf older than the data is ignored, never a step backwards", JSON.stringify(back) === JSON.stringify(alone), back);
  const mixed = mod.computeSealedDeltas([...live, ...gone], {asOf: "2026-09-01"}).find(r => r.tcgplayer_product_id === 2);
  ok("…even when it would re-open a stale product's week: the batch's own newest date still rules",
    mixed.pct_7d === null && mixed.pct_30d === null, mixed);
  const [mat] = mod.computeSealedDeltas(gone, {asOf: TODAY, maxLagDays: (d) => Math.max(14, d / 2)});
  ok("asOf composes with the playmats' maxLagDays", mat.pct_1d === null, mat);
}

// ── the card windows are the matview's windows ─────────────────────────────
{
  const files = readdirSync(new URL("supabase/", root)).filter(f => /^\d+_.*\.sql$/.test(f))
    .sort((a, b) => parseInt(b) - parseInt(a));
  const mig = files.find(f => readFileSync(new URL("supabase/" + f, root), "utf8")
    .includes("create materialized view public.price_movers"));
  const sql = readFileSync(new URL("supabase/" + mig, root), "utf8");
  const bounds = [...sql.matchAll(/a\.low_date > a\.newest_date - (\d+)\s+then .*? as pct_(\w+)/g)].map(m => +m[1]);
  ok(`${mig} guards every Low window on the latest observation`, bounds.length === 6, bounds);
  ok("…with the same windows the card page draws",
    JSON.stringify(bounds) === JSON.stringify(mod.CARD_DELTA_WINDOWS.map(w => w.days)),
    {matview: bounds, card: mod.CARD_DELTA_WINDOWS.map(w => w.days)});
}

// ── the wiring, pinned at source ───────────────────────────────────────────
{
  const seriesCalls = src.match(/computeSeriesDeltas\([^)]*\)/g).filter(c => !c.includes("rows, field, asOf"));
  ok("every computeSeriesDeltas call passes asOf", seriesCalls.length >= 6 && seriesCalls.every(c => /, asOf\)$/.test(c)), seriesCalls);
  const standing = src.match(/standing: [^\n]*priceStanding\([^\n]*/g) || [];
  ok("every card-page standing chip is gated on seriesPricedOn",
    standing.length === 3 && standing.every(s => s.includes("seriesPricedOn(")), standing);
  ok("statRows reads the catalog date", src.includes("    const asOf = catalogPriceDate();"));
  ok("App stamps it on a cache replay", src.includes("      setCatalogPriceDate(cached.latestDate);"));
  ok("…and on a fresh fetch", src.includes("      setCatalogPriceDate(maxPriceDate);"));
  ok("the sealed modal passes it", /computeSealedDeltas\(rows, \{asOf: catalogPriceDate\(\)/.test(src));
}

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
