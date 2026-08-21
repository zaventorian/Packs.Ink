// Guard test for the stream ticker's config layer (ticker.html — /lab/ticker).
// Extracts parseTickerCfg + buildTickerRequests VERBATIM out of ticker.html so
// the test can't drift from what ships — same pattern as test_swiss_engine.mjs.
// Run: node scripts/test_ticker_query.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const html = readFileSync(join(root, "ticker.html"), "utf8");

const start = html.indexOf("const TK_WINDOWS");
const end = html.indexOf("/* ── end pure config layer ── */");
if (start < 0 || end < 0) {
  console.error("FAIL: could not locate the pure config layer in ticker.html");
  process.exit(1);
}
const src = html.slice(start, end);
const { parseTickerCfg, buildTickerRequests, TK_RARITIES } = new Function(
  src + "\nreturn {parseTickerCfg, buildTickerRequests, TK_RARITIES};"
)();

let failures = 0;
const check = (label, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { console.log("  ok  " + label); return; }
  failures++;
  console.error("FAIL  " + label + "\n      got  " + g + "\n      want " + w);
};
const qs = (req) => Object.fromEntries(new URLSearchParams(req.qs));

// Defaults: 1W risers on NM Market, $1 floor, 40 items.
{
  const reqs = buildTickerRequests(parseTickerCfg(""));
  check("defaults: one request", reqs.length, 1);
  const q = qs(reqs[0]);
  check("defaults: order", q.order, "mkt_pct_7d.desc");
  check("defaults: gainers only", q.mkt_pct_7d, "gt.0");
  check("defaults: price floor", q.market_today, "gte.1");
  check("defaults: limit", q.limit, "40");
  check("defaults: select carries both value cols",
    q.select.includes("market_today") && q.select.includes("mkt_pct_7d"), true);
}

// Metric + window map onto the matview's real column names.
{
  const q = qs(buildTickerRequests(parseTickerCfg("?m=low&w=1d"))[0]);
  check("low/1d: order", q.order, "pct_1d.desc");
  check("low/1d: price col", q.low_today, "gte.1");
  const q2 = qs(buildTickerRequests(parseTickerCfg("?w=1y"))[0]);
  check("1y window column", q2.order, "mkt_pct_365d.desc");
  const q3 = qs(buildTickerRequests(parseTickerCfg("?w=2wk"))[0]);
  check("unknown window falls back to 1w", q3.order, "mkt_pct_7d.desc");
}

// Fallers flip the sign filter and the sort direction.
{
  const q = qs(buildTickerRequests(parseTickerCfg("?dir=down"))[0]);
  check("down: order asc", q.order, "mkt_pct_7d.asc");
  check("down: losers only", q.mkt_pct_7d, "lt.0");
}

// Both = two requests splitting the item budget.
{
  const reqs = buildTickerRequests(parseTickerCfg("?dir=both&n=30"));
  check("both: two requests", reqs.map(r => r.dir), ["up", "down"]);
  check("both: split limits", reqs.map(r => qs(r).limit), ["15", "15"]);
}

// Rarity filter: loose input normalizes to canonical names; junk drops out.
{
  const cfg = parseTickerCfg("?rar=rare,super-rare,ICONIC,bogus");
  check("rarity normalize", cfg.rar, ["Rare", "Super Rare", "Iconic"]);
  const q = qs(buildTickerRequests(cfg)[0]);
  check("rarity in-list", q.rarity, 'in.("Rare","Super Rare","Iconic")');
  const all = parseTickerCfg("?rar=" + TK_RARITIES.join(","));
  check("all rarities selected = no filter", "rarity" in qs(buildTickerRequests(all)[0]), false);
}

// min=0 keeps a not-null guard instead of a gte filter.
{
  const q = qs(buildTickerRequests(parseTickerCfg("?min=0"))[0]);
  check("min=0: not-null guard", q.market_today, "not.is.null");
}

// Clamps: count, speed, min; bad colors rejected, transparent accepted.
{
  const c = parseTickerCfg("?n=9999&speed=1&min=-5&bg=zzzzzz&fg=0aB1c2");
  check("count clamp", c.count, 150);
  check("speed clamp", c.speed, 15);
  check("min clamp", c.min, 0);
  check("bad bg rejected", c.bg, "#171226");
  check("fg hex accepted", c.fg, "#0ab1c2");
  check("transparent bg", parseTickerCfg("?bg=transparent").transparent, true);
}

if (failures) {
  console.error("\n" + failures + " failure(s)");
  process.exit(1);
}
console.log("\nAll ticker config tests passed.");
