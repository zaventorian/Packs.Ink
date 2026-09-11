// test_price_standing.mjs — guards the "is this actually a good price" badge.
//
//     node scripts/test_price_standing.mjs
//
// Extracts the real priceStanding out of Index.html, house pattern.
//
// This badge renders at the buy moment, next to an affiliate link, which makes
// a wrong one the most expensive kind of wrong on the site: it tells somebody
// to spend money on a claim we made up. Every case below is one where the
// obvious implementation says something false and confident.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const NL = String.fromCharCode(10);
const grab = (a, b) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error("missing marker: " + a);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error("missing end: " + b);
  return src.slice(i, j + b.length);
};
const grabLine = (p) => {
  const l = src.split(/\r?\n/).find((x) => x.startsWith(p));
  if (!l) throw new Error("missing line: " + p);
  return l;
};

const mod = await import("data:text/javascript," + encodeURIComponent([
  grab("const PRICE_STANDING_WINDOWS = [", NL + "];"),
  grabLine("const PRICE_STANDING_MIN_POINTS = "),
  grabLine("const PRICE_STANDING_MIN_SPAN_RATIO = "),
  grabLine("const PRICE_STANDING_MIN_SPREAD = "),
  grabLine("const PRICE_STANDING_LOW = "),
  grabLine("const PRICE_STANDING_NEAR_LOW = "),
  grabLine("const PRICE_STANDING_HIGH = "),
  grab("function priceStanding(rows, opts){", NL + "}"),
  "export {priceStanding, PRICE_STANDING_MIN_POINTS, PRICE_STANDING_MIN_SPREAD};",
].join(NL)));
const { priceStanding } = mod;

let failed = 0;
const ok = (name, cond, detail) => {
  if (!cond) failed++;
  console.log((cond ? "PASS  " : "FAIL  ") + name + (cond ? "" : "  " + (detail ?? "")));
};

// Build `days` daily rows ending today, priced by fn(i).
const DAY = 86400000;
const series = (days, fn) => {
  const end = Date.parse("2026-09-10T00:00:00Z");
  return Array.from({length: days}, (_, i) => ({
    date: new Date(end - (days - 1 - i) * DAY).toISOString().slice(0, 10),
    market_price: fn(i, days),
    low_price: fn(i, days) * 0.8,
  }));
};

// ── The two claims it exists to make ────────────────────────────────────────
const falling = priceStanding(series(365, (i, n) => 100 - (i / (n - 1)) * 50));
ok("a year of decline reads as the cheapest", falling?.tone === "low", JSON.stringify(falling));
ok("…and claims the LONGEST qualifying window",
  falling?.window === "12-month", falling?.window);
ok("…with a human label", falling?.label === "Cheapest in 12 months", falling?.label);

const rising = priceStanding(series(365, (i, n) => 50 + (i / (n - 1)) * 50));
ok("a year of rise reads as near the high", rising?.tone === "high", JSON.stringify(rising));

// ── Everything it must refuse to say ────────────────────────────────────────
// A V: today sits mid-range. The middle of the range is not news.
const vshape = priceStanding(series(365, (i, n) => {
  const half = Math.floor(n / 2);
  return i < half ? 100 - (i / half) * 50 : 50 + ((i - half) / half) * 25;
}));
ok("mid-range says nothing", vshape === null, JSON.stringify(vshape));

// ⚠ The bug this caught: ties count at-or-below, so a flat line computes to
// pct 1.0 and would announce "near its 12-month high" — the opposite of true.
const flat = priceStanding(series(365, () => 20));
ok("a flat year says nothing (not 'near its high')", flat === null, JSON.stringify(flat));
const nearlyFlat = priceStanding(series(365, (i, n) => 20 + (i / (n - 1)) * 1.0));
ok("a 5% drift is still flat enough to say nothing",
  nearlyFlat === null, JSON.stringify(nearlyFlat));

// A card that has sat at its floor for months is not at a special low today.
const longFloor = priceStanding(series(365, (i, n) => (i < n * 0.6 ? 5 : 5 + (i - n * 0.6) / 10)));
ok("a long-held floor is not 'cheapest' just because today matches it",
  longFloor?.tone !== "low", JSON.stringify(longFloor));

// ── The sample floors ───────────────────────────────────────────────────────
ok("too few points says nothing", priceStanding(series(10, (i) => 100 - i)) === null);
ok("no rows says nothing", priceStanding([]) === null);
ok("null says nothing", priceStanding(null) === null);

// 40 samples all inside one week clears the count floor but describes a week,
// not a quarter — the span floor is what stops it claiming one.
const end = Date.parse("2026-09-10T00:00:00Z");
const bunched = Array.from({length: 40}, (_, i) => ({
  date: new Date(end - Math.floor(i / 6) * DAY).toISOString().slice(0, 10),
  market_price: 100 - i,
}));
ok("40 points inside a week cannot claim a quarter",
  priceStanding(bunched) === null, JSON.stringify(priceStanding(bunched)));

// ── It reads market_price, not the sticker ──────────────────────────────────
// low_price carries phantom spikes (smooth_low_prices.py exists for them). A
// card whose MARKET is flat but whose LOW cratered on one bad listing must not
// announce a buying opportunity.
const phantomLow = series(365, () => 20).map((r, i, a) => ({
  ...r, low_price: i === a.length - 1 ? 1.5 : 20,
}));
ok("a phantom low does not create a 'cheapest' claim",
  priceStanding(phantomLow) === null, JSON.stringify(priceStanding(phantomLow)));
// Asked for low_price explicitly it WOULD fire — proving the default is doing
// the work, not that the function is blind.
ok("…and that is the default's doing, not blindness",
  priceStanding(phantomLow, {field: "low_price"})?.tone === "low");

// ── Shape ───────────────────────────────────────────────────────────────────
ok("a hit reports its sample size and value",
  Number.isFinite(falling?.n) && falling.n > 300 && Math.abs(falling.value - 50) < 0.01,
  JSON.stringify(falling));
ok("pct is a fraction", falling?.pct >= 0 && falling?.pct <= 1, String(falling?.pct));
ok("tone is one of the three", ["low", "near-low", "high"].includes(rising?.tone), rising?.tone);

// A shorter history falls back to a shorter window rather than staying silent.
const short = priceStanding(series(100, (i, n) => 100 - (i / (n - 1)) * 50));
ok("100 days of data still yields a 3-month claim",
  short?.tone === "low" && short.window === "3-month", JSON.stringify(short));

console.log(NL + (failed ? failed + " FAILED" : "all passed"));
process.exit(failed ? 1 : 0);
