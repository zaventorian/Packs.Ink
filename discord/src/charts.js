// charts.js — the /chart/... routes Discord's image proxy fetches.
//
//   /chart/p/<pid>/<N|C|H|F>/<range>.png?d=<price date>[&s=1][&r=<card_id>&rb=<bucket>]
//   /chart/g/<card_id>/<grader>/<grade>/<range>.png?b=<printing bucket>&d=<date>
//   /chart/r/<card_id>/<range>.png?rb=<bucket>&d=<date>
//
// The ?d= date is part of the URL on purpose: Discord caches an image by URL,
// so a new day's prices need a new URL, and an old message keeps the chart it
// was sent with. s=1 marks sealed product; r= overlays a card's eBay raw sales.
import { renderChart, THEME } from "./chart.js";
import { priceHistory, gradedSales, rawSales, RANGES, FIN_PRINTING } from "./data.js";
import { gradedSlotBucket } from "./site.generated.js";

const DAY = 86400000;
const tOf = (d) => Date.parse(String(d).slice(0, 10) + "T00:00:00Z");
const money = (v) => (v == null ? null : v >= 1000 ? "$" + Math.round(v).toLocaleString("en-US") : "$" + Number(v).toFixed(2));
const png = (bytes) => new Response(bytes, {
  headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=43200" },
});

export function priceChartSpec(rows, rangeKey, { sealed = false, rawDots = null } = {}) {
  const mk = [], lo = [];
  for (const r of rows || []) {
    const t = tOf(r.date);
    if (!Number.isFinite(t)) continue;
    // A published $0 is a missing price, not a price: drawn, it is a cliff
    // to the axis that never happened.
    if (Number(r.market_price) > 0) mk.push([t, Number(r.market_price)]);
    if (Number(r.low_price) > 0) lo.push([t, Number(r.low_price)]);
  }
  // On a card whose market is really eBay (a promo TCGplayer can't price), the
  // sales are dots over the TCGplayer line, and Low is left off: on exactly
  // those thinly-listed cards Low throws phantom spikes (one reached $10,000
  // against sales of $518-$1,550) that flatten every dot onto the axis. The
  // site's card page makes the same call.
  const hasDots = !!(rawDots && rawDots.length);
  const showLow = lo.length > 0 && !hasDots;
  const legend = [];
  if (hasDots) legend.push({ label: "eBay sales", color: THEME.teal, value: String(rawDots.length) });
  // Low is the headline line, as on the site (Zaven, 2026-10-04); Market is
  // the second. Where Low is left off (eBay dots), Market takes the lead.
  // Sealed product has no condition, so its market price is just "Market".
  const mkLabel = sealed ? "Market" : "NM Market";
  const primary = showLow ? lo : mk, secondary = showLow ? mk : [];
  if (showLow) legend.push({ label: "Low", color: THEME.gold, value: money(lo[lo.length - 1][1]) });
  if (mk.length) legend.push({ label: mkLabel, color: showLow ? THEME.lilac : THEME.gold, value: money(mk[mk.length - 1][1]) });
  return {
    lines: [
      ...(primary.length ? [{ pts: primary, color: THEME.gold, width: 2.6, fill: true, endDot: true }] : []),
      ...(secondary.length ? [{ pts: secondary, color: THEME.lilac, width: 1.7 }] : []),
    ],
    dots: hasDots ? [{ pts: rawDots, color: THEME.teal, r: 4.6, alpha: 0.9 }] : [],
    legend, corner: (RANGES[rangeKey] || {}).label,
    empty: hasDots ? "No sales in this window" : "No TCGplayer price history yet",
  };
}

// Each sale is a DOT, never joined: twelve sales across a year drawn as a
// line would be a price path that never happened. The average of the last
// five is the line.
export function salesChartSpec(sales, rangeKey, label) {
  const pts = (sales || []).map((s) => [tOf(s.sold_date), Number(s.sale_price)])
    .filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]) && p[1] > 0);
  const avg = [];
  for (let i = 0; i < pts.length; i++) {
    const w = pts.slice(Math.max(0, i - 4), i + 1);
    avg.push([pts[i][0], w.reduce((s, p) => s + p[1], 0) / w.length]);
  }
  return {
    lines: avg.length > 1 ? [{ pts: avg, color: THEME.gold, width: 2.2, endDot: true }] : [],
    dots: [{ pts, color: THEME.lilac, r: 4.2, alpha: 0.85 }],
    legend: [
      { label: `${label} sales`, color: THEME.lilac, value: String(pts.length) },
      ...(avg.length ? [{ label: "Avg of last 5", color: THEME.gold, value: money(avg[avg.length - 1][1]) }] : []),
    ],
    corner: (RANGES[rangeKey] || {}).label, empty: "No sales on record in this window",
  };
}

// One market ("") keeps every sale; otherwise only this printing's, and a sale
// nobody classified belongs to neither — a Challenge card's Top Prize foil and
// Prize Wall non-foil are two markets ~50x apart.
async function salesIn(fetcher, bucket, days) {
  let sales = await fetcher();
  if (bucket) sales = sales.filter((s) => gradedSlotBucket(s.printing) === bucket);
  if (days) {
    const since = Date.now() - days * DAY;
    sales = sales.filter((s) => tOf(s.sold_date) >= since);
  }
  return sales;
}

export async function chartResponse(url, db) {
  const q = (k) => url.searchParams.get(k) || "";
  const p = url.pathname.match(/^\/chart\/p\/(\d{1,9})\/([NCHF])\/([a-z0-9]+)\.png$/);
  if (p) {
    const range = RANGES[p[3]];
    if (!range) return new Response("unknown range", { status: 404 });
    const rawCard = q("r");
    const [rows, raw] = await Promise.all([
      priceHistory(db, Number(p[1]), FIN_PRINTING[p[2]], { sinceDays: range.days }),
      rawCard ? salesIn(() => rawSales(db, rawCard), q("rb"), range.days).catch(() => []) : null,
    ]);
    const rawDots = raw ? raw.map((x) => [tOf(x.sold_date), Number(x.sale_price)]).filter((d) => Number.isFinite(d[0]) && d[1] > 0) : null;
    return png(renderChart(priceChartSpec(rows, p[3], { sealed: q("s") === "1", rawDots })));
  }
  const g = url.pathname.match(/^\/chart\/g\/([^/]{1,80})\/([A-Za-z]{2,4})\/(10|[1-9](?:\.5)?)\/([a-z0-9]+)\.png$/);
  if (g) {
    const range = RANGES[g[4]];
    if (!range) return new Response("unknown range", { status: 404 });
    const cardId = decodeURIComponent(g[1]);
    const sales = await salesIn(() => gradedSales(db, cardId, g[2].toUpperCase(), g[3]), q("b"), range.days);
    return png(renderChart(salesChartSpec(sales, g[4], `${g[2].toUpperCase()} ${g[3]}`)));
  }
  // A raw-priced card with no TCGplayer product at all: its eBay sales alone.
  const r = url.pathname.match(/^\/chart\/r\/([^/]{1,80})\/([a-z0-9]+)\.png$/);
  if (r) {
    const range = RANGES[r[2]];
    if (!range) return new Response("unknown range", { status: 404 });
    const sales = await salesIn(() => rawSales(db, decodeURIComponent(r[1])), q("rb"), range.days);
    return png(renderChart(salesChartSpec(sales, r[2], "eBay")));
  }
  return new Response("not found", { status: 404 });
}
