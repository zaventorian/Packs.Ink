// Guard test for the stream ticker's config layer (ticker.html — /ticker).
// Extracts parseTickerCfg + buildTickerPlan VERBATIM out of ticker.html so
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
const { parseTickerCfg, buildTickerPlan, TK_GROUPS, nextTickerRefreshMs } = new Function(
  src + "\nreturn {parseTickerCfg, buildTickerPlan, TK_GROUPS, nextTickerRefreshMs};"
)();

let failures = 0;
const check = (label, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { console.log("  ok  " + label); return; }
  failures++;
  console.error("FAIL  " + label + "\n      got  " + g + "\n      want " + w);
};
const qs = (req) => Object.fromEntries(new URLSearchParams(req.qs));

// Defaults: (1D, 1W) × (Chase, Rare–Legendary) risers on NM Market, $1 floor.
{
  const plan = buildTickerPlan(parseTickerCfg(""));
  check("defaults: 4 sections in window-major order",
    plan.map(s => s.win + "/" + s.group),
    ["1d/chase", "1d/rareleg", "1w/chase", "1w/rareleg"]);
  check("defaults: section headers", plan.map(s => s.title + " · " + s.sub).slice(0, 2),
    ["1D Risers · Chase", "1D Risers · Rare – Legendary"]);
  const q = qs(plan[0].requests[0]);
  check("defaults: order", q.order, "mkt_pct_1d.desc");
  check("defaults: gainers only", q.mkt_pct_1d, "gt.0");
  check("defaults: price floor $5", q.market_today, "gte.5");
  check("custom floor respected",
    qs(buildTickerPlan(parseTickerCfg("?min=1"))[0].requests[0]).market_today, "gte.1");
  check("defaults: limit", q.limit, "15");
  check("defaults: chase rarity filter", q.rarity, 'in.("Enchanted","Epic","Iconic")');
  check("defaults: rareleg rarity filter", qs(plan[1].requests[0]).rarity,
    'in.("Rare","Super Rare","Legendary")');
  check("defaults: no printing filter when both on", "printing" in q || "or" in q, false);
}

// Window/metric map onto the matview's real column names; canonical order wins.
{
  const plan = buildTickerPlan(parseTickerCfg("?m=low&w=1y,1d&g=all"));
  check("low metric + canonical window order", plan.map(s => qs(s.requests[0]).order),
    ["pct_1d.desc", "pct_365d.desc"]);
  check("all group: no rarity filter", "rarity" in qs(plan[0].requests[0]), false);
  check("low metric price col", qs(plan[0].requests[0]).low_today, "gte.5");
  check("unknown tokens fall back to defaults",
    buildTickerPlan(parseTickerCfg("?w=2wk&g=mythic")).map(s => s.win + "/" + s.group),
    ["1d/chase", "1d/rareleg", "1w/chase", "1w/rareleg"]);
}

// Direction: fallers flip sign + sort; both = two requests splitting the budget.
{
  const down = buildTickerPlan(parseTickerCfg("?dir=down&w=1w&g=all"))[0];
  check("down: header word", down.title, "1W Fallers");
  check("down: order asc", qs(down.requests[0]).order, "mkt_pct_7d.asc");
  check("down: losers only", qs(down.requests[0]).mkt_pct_7d, "lt.0");
  const both = buildTickerPlan(parseTickerCfg("?dir=both&w=1w&g=all&n=30"))[0];
  check("both: header word", both.title, "1W Movers");
  check("both: two requests", both.requests.map(r => r.dir), ["up", "down"]);
  check("both: split limits", both.requests.map(r => qs(r).limit), ["15", "15"]);
}

// Promo group uses eq; single-printing groups skip the foil filter entirely.
{
  const promo = buildTickerPlan(parseTickerCfg("?w=1w&g=promo&nf=0"))[0];
  const q = qs(promo.requests[0]);
  check("promo: eq filter", q.rarity, "eq.Promo");
  check("promo: foil filter bypassed", "printing" in q || "or" in q, false);
  const chase = qs(buildTickerPlan(parseTickerCfg("?w=1w&g=chase&foil=0"))[0].requests[0]);
  check("chase: foil filter bypassed", "printing" in chase || "or" in chase, false);
}

// Foil toggles on groups that DO have both printings.
{
  const nfOnly = qs(buildTickerPlan(parseTickerCfg("?w=1w&g=rareleg&foil=0"))[0].requests[0]);
  check("rareleg non-foil only", nfOnly.printing, 'in.("Normal","Non-Foil")');
  const foilOnly = qs(buildTickerPlan(parseTickerCfg("?w=1w&g=rareleg&nf=0"))[0].requests[0]);
  check("rareleg foil only", foilOnly.printing, 'in.("Cold Foil","Holofoil","Foil")');
  const allNf = qs(buildTickerPlan(parseTickerCfg("?w=1w&g=all&foil=0"))[0].requests[0]);
  check("all group: chase-bypass OR", allNf.or,
    '(printing.in.("Normal","Non-Foil"),rarity.in.("Enchanted","Epic","Iconic","Promo"))');
  const cfg = parseTickerCfg("?foil=0&nf=0");
  check("both printings off resets to both on", [cfg.foil, cfg.nonfoil], [true, true]);
}

// Clamps + colors.
{
  const c = parseTickerCfg("?n=9999&speed=1&min=-5&bg=zzzzzz&fg=0aB1c2");
  check("count clamp", c.count, 60);
  check("speed clamp", c.speed, 15);
  check("min clamp", c.min, 0);
  check("bad bg rejected", c.bg, "#171226");
  check("fg hex accepted", c.fg, "#0ab1c2");
  check("transparent bg", parseTickerCfg("?bg=transparent").transparent, true);
  const q = qs(buildTickerPlan(parseTickerCfg("?w=1w&g=all&min=0"))[0].requests[0]);
  check("min=0: not-null guard", q.market_today, "not.is.null");
}

// Refresh scheduling follows the ETL clock: 30-min checks through the publish
// + retry window (20:00–03:00 UTC), otherwise sleep until 20:45 UTC.
{
  const at = (h, m) => new Date(Date.UTC(2026, 7, 21, h, m, 0));
  check("in-window 21:00 UTC", nextTickerRefreshMs(at(21, 0)), 30 * 60 * 1000);
  check("in-window 02:59 UTC", nextTickerRefreshMs(at(2, 59)), 30 * 60 * 1000);
  check("03:00 UTC sleeps to 20:45", nextTickerRefreshMs(at(3, 0)), (17 * 60 + 45) * 60 * 1000);
  check("10:00 UTC sleeps to 20:45", nextTickerRefreshMs(at(10, 0)), (10 * 60 + 45) * 60 * 1000);
  check("19:59 UTC sleeps 46 min", nextTickerRefreshMs(at(19, 59)), 46 * 60 * 1000);
}

// Every group's rarity list stays inside the canonical vocabulary.
{
  const CANON = ["Common","Uncommon","Rare","Super Rare","Legendary","Enchanted","Epic","Iconic","Promo"];
  check("group rarities are canonical",
    TK_GROUPS.every(g => !g.rarities || g.rarities.every(r => CANON.includes(r))), true);
}

if (failures) {
  console.error("\n" + failures + " failure(s)");
  process.exit(1);
}
console.log("\nAll ticker config tests passed.");
