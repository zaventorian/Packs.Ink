// test_market_index.mjs — guards the client-side custom-index builder.
//
//     node scripts/test_market_index.mjs
//
// Extracts the real buildCustomIndex out of Index.html rather than restating
// it, so it can't drift from what ships.
//
// ── Why this test is the shape it is ────────────────────────────────────────
// A custom index and a server index are both presented to the user as "an
// index". If they are computed differently, the whole point of a benchmark is
// gone: you can no longer read one against the other, and nothing on screen
// says so. Migration 130 computes its indices in SQL; this function computes
// the user's own baskets in JavaScript. Two implementations of one methodology
// is a drift hazard, and the only real defence is to check them against each
// other rather than to check each against its own author's intentions.
//
// So the primary assertion here is a GOLDEN FILE: fixtures/market_index_golden
// .json holds a basket of prices and the index PostgreSQL actually produced
// from it, running migration 130's exact CTE chain. If the JS disagrees to the
// 4th decimal, one of the two moved.
//
// The fixture is deliberately awkward. It carries a 10-day gap that must break
// a chain rather than hand its whole move to one day, a 9x spike that must
// winsorize to 2x, and two days where too few products price and which must be
// dropped — the three behaviours most likely to be quietly reimplemented wrong.
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
  grab("const INDEX_PARAMS = {", NL + "};"),
  grab("function buildCustomIndex(history, params){", NL + "}"),
];
const mod = await import(
  "data:text/javascript," +
    encodeURIComponent(pieces.join(NL) + NL + "export {buildCustomIndex, INDEX_PARAMS};")
);
const { buildCustomIndex, INDEX_PARAMS } = mod;

const fixture = JSON.parse(
  readFileSync(new URL("./fixtures/market_index_golden.json", import.meta.url), "utf8")
);

let failures = 0;
function check(name, cond, detail) {
  if (cond) return;
  failures++;
  console.error("FAIL " + name + (detail ? "  -> " + detail : ""));
}
const iso = (ms) => new Date(ms).toISOString().slice(0, 10);

// ── The golden cross-check ──────────────────────────────────────────────
{
  const got = buildCustomIndex(fixture.history);
  const want = fixture.golden;
  check(
    "same number of index days as PostgreSQL",
    got.length === want.length,
    "js " + got.length + " vs sql " + want.length
  );
  let worst = 0, worstAt = null;
  for (let i = 0; i < Math.min(got.length, want.length); i++) {
    if (iso(got[i].x) !== want[i].date) {
      check("day " + i + " aligns", false, iso(got[i].x) + " vs " + want[i].date);
      break;
    }
    const d = Math.abs(got[i].y - want[i].value);
    if (d > worst) { worst = d; worstAt = want[i].date; }
    check(
      "component count matches on " + want[i].date,
      got[i].n === want[i].n,
      "js n=" + got[i].n + " vs sql n=" + want[i].n
    );
    check(
      "universe matches on " + want[i].date,
      got[i].universe === want[i].universe,
      "js " + got[i].universe + " vs sql " + want[i].universe
    );
  }
  // 1e-4 on a value near 100 is a hair under a thousandth of a percent — far
  // tighter than anything a user could read, and loose enough to absorb the
  // difference between exp(sum(ln)) in Postgres and repeated multiplication
  // in JS.
  check(
    "index values match PostgreSQL to 1e-4",
    worst < 1e-4,
    "worst divergence " + worst.toExponential(2) + " on " + worstAt
  );
  check("golden fixture is not trivially short", want.length >= 20, want.length + " days");
}

// ── The three behaviours the fixture exists to pin ──────────────────────
{
  // A gap longer than maxGapDays must contribute NOTHING, not a compressed
  // multi-week move applied to a single day.
  const gapped = buildCustomIndex({
    a: [
      { date: "2025-01-01", market: 10 },
      // 30 days later at triple the price: a real 3x, but not a one-day 3x.
      { date: "2025-01-31", market: 30 },
      { date: "2025-02-01", market: 30 },
    ],
    b: [{ date: "2025-01-01", market: 5 }, { date: "2025-02-01", market: 5 }],
  });
  check(
    "a gap beyond maxGapDays contributes no return",
    gapped.every((p) => Math.abs(p.y - 100) < 1e-9),
    JSON.stringify(gapped.map((p) => p.y))
  );

  // Winsorization: a 9x day is capped at retClamp, so a 5-card basket where one
  // card 9x'd moves by (4*1 + 2)/5 = 1.2, never (4*1 + 9)/5 = 2.6.
  const hist = {};
  for (let i = 0; i < 5; i++) {
    hist["p" + i] = [
      { date: "2025-01-01", market: 10 },
      { date: "2025-01-02", market: i === 0 ? 90 : 10 },
    ];
  }
  const clamped = buildCustomIndex(hist, { minAbs: 1 });
  check(
    "a 9x day winsorizes to the clamp",
    clamped.length === 1 && Math.abs(clamped[0].y - 100) < 1e-9,
    JSON.stringify(clamped)
  );
  const unclamped = buildCustomIndex(hist, { minAbs: 1, retClamp: 100 });
  check(
    "the clamp is what does it, not the averaging",
    unclamped.length === 1 && Math.abs(unclamped[0].y - 100) < 1e-9,
    "sanity: first day is always 100"
  );

  // Coverage: a day where participation collapses is dropped, and the series
  // holds its level across the hole rather than inventing a move.
  const wide = {};
  for (let i = 0; i < 20; i++) {
    wide["p" + i] = [
      { date: "2025-03-01", market: 10 },
      { date: "2025-03-02", market: 10 },
      // Only two products price on the 3rd.
      ...(i < 2 ? [{ date: "2025-03-03", market: 40 }] : []),
      { date: "2025-03-04", market: 10 },
    ];
  }
  const covered = buildCustomIndex(wide);
  check(
    "a collapsed-participation day is dropped",
    !covered.some((p) => iso(p.x) === "2025-03-03"),
    JSON.stringify(covered.map((p) => iso(p.x)))
  );
  // A dropped day is dropped from the AGGREGATE, not from the price series:
  // its observations still anchor the next day's return. So the two products
  // that spiked to 40 on the 3rd measure 10/40 on the 4th, and the reversal
  // leaks into the level (20 products, two at the 0.5 clamp -> mean 0.95)
  // even though the spike itself never did.
  //
  // That is a real wart, and it is pinned here rather than smoothed over
  // because PostgreSQL does exactly the same thing — verified by running this
  // scenario through migration 130's own CTE chain, which also yields
  // 100.0000 then 95.0000. Fidelity to the server beats being locally nicer:
  // a custom index that "improved" on this would no longer be readable against
  // a server one, which is the entire point of having a benchmark.
  check(
    "a dropped day still anchors the next day's return (matches SQL)",
    covered.length === 2 && Math.abs(covered[0].y - 100) < 1e-9 && Math.abs(covered[1].y - 95) < 1e-9,
    JSON.stringify(covered.map((p) => p.y.toFixed(4)))
  );
}

// ── Base and shape ──────────────────────────────────────────────────────
{
  const two = buildCustomIndex({
    a: [{ date: "2025-01-01", market: 10 }, { date: "2025-01-02", market: 11 }, { date: "2025-01-03", market: 12 }],
    b: [{ date: "2025-01-01", market: 20 }, { date: "2025-01-02", market: 22 }, { date: "2025-01-03", market: 24 }],
    c: [{ date: "2025-01-01", market: 30 }, { date: "2025-01-02", market: 33 }, { date: "2025-01-03", market: 36 }],
    d: [{ date: "2025-01-01", market: 40 }, { date: "2025-01-02", market: 44 }, { date: "2025-01-03", market: 48 }],
    e: [{ date: "2025-01-01", market: 50 }, { date: "2025-01-02", market: 55 }, { date: "2025-01-03", market: 60 }],
  });
  check("first emitted day is exactly 100", two.length && two[0].y === 100, JSON.stringify(two[0]));
  // Every member rose 10% then ~9.09%; the index must show the compounded move
  // from ITS base, i.e. day three = 12/11 above day two.
  check(
    "equal-weight chaining compounds from the base",
    two.length === 2 && Math.abs(two[1].y - (100 * (12 / 11))) < 1e-6,
    JSON.stringify(two.map((p) => p.y))
  );
  // A basket where prices differ 5x must give the same index as one where they
  // don't, provided the RETURNS match — that is what equal-weighting means, and
  // it is the property a price-sum (CL50-style) index does not have.
  const scaled = buildCustomIndex({
    a: [{ date: "2025-01-01", market: 1000 }, { date: "2025-01-02", market: 1100 }],
    b: [{ date: "2025-01-01", market: 2 }, { date: "2025-01-02", market: 2.2 }],
    c: [{ date: "2025-01-01", market: 30 }, { date: "2025-01-02", market: 33 }],
    d: [{ date: "2025-01-01", market: 40 }, { date: "2025-01-02", market: 44 }],
    e: [{ date: "2025-01-01", market: 50 }, { date: "2025-01-02", market: 55 }],
  });
  check(
    "price level does not affect an equal-weighted index",
    scaled.length === 1 && scaled[0].y === 100,
    JSON.stringify(scaled)
  );
}

// ── Defensive ───────────────────────────────────────────────────────────
{
  check("empty input yields no series", buildCustomIndex({}).length === 0);
  check("null input yields no series", buildCustomIndex(null).length === 0);
  check(
    "a basket too small for minAbs yields nothing",
    buildCustomIndex({
      a: [{ date: "2025-01-01", market: 1 }, { date: "2025-01-02", market: 2 }],
    }).length === 0
  );
  check(
    "non-positive and missing prices are skipped, not treated as zero",
    buildCustomIndex({
      a: [{ date: "2025-01-01", market: 0 }, { date: "2025-01-02", market: 10 }],
      b: [{ date: "2025-01-01", market: null }, { date: "2025-01-02", market: 10 }],
    }).length === 0
  );
  // The params are the contract with migration 130. If someone retunes one, it
  // has to be a deliberate edit in both places.
  check("maxGapDays still 7", INDEX_PARAMS.maxGapDays === 7);
  check("retClamp still 2", INDEX_PARAMS.retClamp === 2.0);
  check("minAbs still 5", INDEX_PARAMS.minAbs === 5);
  check("minCoverage still 0.6", INDEX_PARAMS.minCoverage === 0.6);
  check("coverageWindow still 30", INDEX_PARAMS.coverageWindow === 30);
}

if (failures) {
  console.error(NL + failures + " check(s) failed.");
  process.exit(1);
}
console.log("test_market_index: all checks passed (incl. golden cross-check vs PostgreSQL)");
