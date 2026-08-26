// test_alerts.mjs — guards the price-alert evaluator.
//
//     node scripts/test_alerts.mjs
//
// Extracts the real functions out of Index.html rather than restating them, so
// they can't drift from what ships.
//
// Every failure mode here is silent and lands on the user, not on us. A rule
// that never fires looks identical to a market that never moved. A rule that
// fires every day turns the inbox into noise and gets the whole feature muted.
// A pct_down comparison with the wrong sign fires on gains. And the cooldown is
// the only thing standing between "a card parked above its threshold" and a
// daily alert about it forever.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const NL = String.fromCharCode(10);

function grab(start, end) {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
}

const pieces = [
  grab("function alertObservedValue(row, alert){", NL + "}"),
  grab("function alertConditionMet(observed, alert){", NL + "}"),
  grab("function evaluateAlerts({alerts, watchlists, rowByKey, priceDate, lastFiredByKey, nowMs}){", NL + "}"),
];
const mod = await import(
  "data:text/javascript," +
    encodeURIComponent(
      pieces.join(NL) + NL +
        "export {alertObservedValue, alertConditionMet, evaluateAlerts};"
    )
);
const { alertObservedValue, alertConditionMet, evaluateAlerts } = mod;

let failures = 0;
function check(name, cond, detail) {
  if (cond) return;
  failures++;
  console.error("FAIL " + name + (detail ? "  -> " + detail : ""));
}
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  check(name, g === w, "got " + g + " want " + w);
}

const DAY = 86400000;
const NOW = Date.parse("2026-08-25T12:00:00Z");
const PD = "2026-08-25";

const row = (over = {}) => ({
  card_id: "crd_a", printing: "Normal",
  low_today: 10, market_today: 12,
  pct_1d: 1, pct_7d: 30, pct_30d: -25, pct_90d: 5, pct_180d: 0, pct_365d: 100,
  mkt_pct_1d: 2, mkt_pct_7d: 12, mkt_pct_30d: -8, mkt_pct_90d: 3, mkt_pct_180d: 1, mkt_pct_365d: 60,
  ...over,
});
const rows = (list) => new Map(list.map((r) => [r.card_id + "|" + (r.printing || "Normal"), r]));
const run = (alerts, opts = {}) =>
  evaluateAlerts({
    alerts,
    watchlists: opts.watchlists || [],
    rowByKey: opts.rowByKey || rows([row()]),
    priceDate: PD,
    lastFiredByKey: opts.lastFiredByKey || new Map(),
    nowMs: opts.nowMs ?? NOW,
  });
const rule = (over = {}) => ({
  id: "al1", card_id: "crd_a", printing: "Normal", enabled: true,
  basis: "market", kind: "above", threshold: 10, window_key: "pct_7d",
  cooldown_days: 7, ...over,
});

// ── Which number a rule reads ───────────────────────────────────────────
{
  eq("above/below on market basis reads market_today",
    alertObservedValue(row(), rule({ kind: "above", basis: "market" })), 12);
  eq("above/below on low basis reads low_today",
    alertObservedValue(row(), rule({ kind: "above", basis: "low" })), 10);
  // The basis has to steer the Δ% family too, or a market-basis rule silently
  // judges itself against the low-price series — which for this data set is a
  // completely different number (30 vs 12 on the same card, same window).
  eq("pct on low basis reads pct_*",
    alertObservedValue(row(), rule({ kind: "pct_up", basis: "low", window_key: "pct_7d" })), 30);
  eq("pct on market basis reads mkt_pct_*",
    alertObservedValue(row(), rule({ kind: "pct_up", basis: "market", window_key: "pct_7d" })), 12);
  eq("a missing row observes nothing", alertObservedValue(null, rule()), null);
  eq("a null column observes nothing",
    alertObservedValue(row({ market_today: null }), rule({ kind: "above" })), null);
}

// ── The comparisons ─────────────────────────────────────────────────────
{
  check("above fires at the threshold", alertConditionMet(10, rule({ kind: "above", threshold: 10 })));
  check("above fires over it", alertConditionMet(11, rule({ kind: "above", threshold: 10 })));
  check("above stays quiet under it", !alertConditionMet(9, rule({ kind: "above", threshold: 10 })));
  check("below fires at the threshold", alertConditionMet(10, rule({ kind: "below", threshold: 10 })));
  check("below stays quiet over it", !alertConditionMet(11, rule({ kind: "below", threshold: 10 })));
  check("pct_up fires on a big gain", alertConditionMet(30, rule({ kind: "pct_up", threshold: 25 })));
  check("pct_up stays quiet on a small gain", !alertConditionMet(10, rule({ kind: "pct_up", threshold: 25 })));
  // The sign convention: the user types 10 for "down 10%".
  check("pct_down fires on a drop past the threshold",
    alertConditionMet(-25, rule({ kind: "pct_down", threshold: 10 })));
  check("pct_down does NOT fire on a gain",
    !alertConditionMet(25, rule({ kind: "pct_down", threshold: 10 })));
  check("pct_down treats a negative threshold the same as a positive one",
    alertConditionMet(-25, rule({ kind: "pct_down", threshold: -10 })));
  check("nothing fires on a null observation", !alertConditionMet(null, rule()));
  check("nothing fires on NaN", !alertConditionMet(NaN, rule()));
  check("an unknown kind never fires", !alertConditionMet(999, rule({ kind: "sideways" })));
}

// ── Scope resolution ────────────────────────────────────────────────────
{
  eq("a card rule fires once", run([rule({ kind: "above", threshold: 5 })]).length, 1);
  eq("a disabled rule never fires",
    run([rule({ kind: "above", threshold: 5, enabled: false })]).length, 0);

  const wl = [{ id: "wl1", name: "L", items: [
    { card_id: "crd_a", printing: "Normal" },
    { card_id: "crd_b", printing: "Cold Foil" },
    { card_id: "crd_c", printing: "Normal" },
  ]}];
  const rk = rows([
    row(),
    row({ card_id: "crd_b", printing: "Cold Foil", market_today: 200 }),
    row({ card_id: "crd_c", market_today: 1 }),
  ]);
  const fired = run([rule({ id: "L1", card_id: null, watchlist_id: "wl1", kind: "above", threshold: 5 })],
    { watchlists: wl, rowByKey: rk });
  // Two of the three clear $5; each is its own event. Collapsing them would
  // make the inbox say "your list moved" and leave the user to find out which.
  eq("a list rule fires per card, not per list", fired.length, 2);
  eq("each firing names its own card", fired.map((f) => f.card_id).sort(), ["crd_a", "crd_b"]);
  eq("a firing carries the printing that matched", fired.find(f => f.card_id === "crd_b").printing, "Cold Foil");
  eq("a firing snapshots the observed value", fired.find(f => f.card_id === "crd_b").observed, 200);
  eq("a firing carries the price date", fired[0].price_date, PD);

  // A list can hold a printing price_movers has no row for; falling back to
  // Normal beats never firing.
  const rkNoFoil = rows([row(), row({ card_id: "crd_b", market_today: 200 })]);
  const fb = run([rule({ id: "L2", card_id: null, watchlist_id: "wl1", kind: "above", threshold: 100 })],
    { watchlists: wl, rowByKey: rkNoFoil });
  eq("an unmatched printing falls back to Normal", fb.length, 1);

  eq("a list rule with no list resolves to nothing",
    run([rule({ card_id: null, watchlist_id: "nope" })], { watchlists: wl }).length, 0);
}

// ── Cooldown ────────────────────────────────────────────────────────────
{
  const r = [rule({ kind: "above", threshold: 5, cooldown_days: 7 })];
  const key = "al1|crd_a|Normal";
  eq("fires when never fired before", run(r).length, 1);
  eq("stays quiet one day into a 7-day cooldown",
    run(r, { lastFiredByKey: new Map([[key, NOW - 1 * DAY]]) }).length, 0);
  eq("stays quiet six days in",
    run(r, { lastFiredByKey: new Map([[key, NOW - 6 * DAY]]) }).length, 0);
  eq("fires again once the cooldown has elapsed",
    run(r, { lastFiredByKey: new Map([[key, NOW - 8 * DAY]]) }).length, 1);
  // cooldown_days 0 means "at most once per snapshot", which the unique index
  // enforces; the evaluator must not block it locally.
  eq("a zero cooldown does not block a re-fire",
    run([rule({ kind: "above", threshold: 5, cooldown_days: 0 })],
      { lastFiredByKey: new Map([[key, NOW - 1000]]) }).length, 1);
  // The cooldown is per (rule, card) — one card cooling down must not silence
  // the rest of a watchlist.
  const wl = [{ id: "wl1", name: "L", items: [
    { card_id: "crd_a", printing: "Normal" }, { card_id: "crd_b", printing: "Normal" },
  ]}];
  const rk = rows([row(), row({ card_id: "crd_b" })]);
  const out = run([rule({ id: "L1", card_id: null, watchlist_id: "wl1", kind: "above", threshold: 5 })],
    { watchlists: wl, rowByKey: rk, lastFiredByKey: new Map([["L1|crd_a|Normal", NOW - DAY]]) });
  eq("cooldown is per card, not per rule", out.map((f) => f.card_id), ["crd_b"]);
}

// ── Defensive ───────────────────────────────────────────────────────────
{
  eq("no alerts, no firings", run([]).length, 0);
  eq("null alerts is survivable", evaluateAlerts({
    alerts: null, watchlists: null, rowByKey: new Map(),
    priceDate: PD, lastFiredByKey: new Map(), nowMs: NOW }).length, 0);
  eq("a null entry in the list is skipped", run([null, rule({ kind: "above", threshold: 5 })]).length, 1);
  eq("a card with no price row never fires",
    run([rule({ card_id: "crd_missing", kind: "above", threshold: 1 })]).length, 0);
  eq("a non-numeric threshold never fires",
    run([rule({ kind: "above", threshold: "abc" })]).length, 0);
}

if (failures) {
  console.error(NL + failures + " check(s) failed.");
  process.exit(1);
}
console.log("test_alerts: all checks passed");
