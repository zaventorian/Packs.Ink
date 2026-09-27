// charts.js — the /chart/... routes Discord's image proxy fetches.
//
//   /chart/p/<pid>/<N|C|H|F>/<range>.png?d=<price date>
//   /chart/g/<card_id>/<grader>/<grade>/<range>.png?b=<printing bucket>&d=<date>
//
// The ?d= date is part of the URL on purpose: Discord caches an image by URL,
// so a new day's prices need a new URL, and an old message keeps the chart it
// was sent with.
import { renderChart, THEME } from "./chart.js";
import { priceHistory, gradedSales, RANGES, FIN_PRINTING } from "./data.js";
import { gradedSlotBucket } from "./site.generated.js";

const DAY = 86400000;
const tOf = (d) => Date.parse(String(d).slice(0, 10) + "T00:00:00Z");
const money = (v) => (v == null ? null : v >= 1000 ? "$" + Math.round(v).toLocaleString("en-US") : "$" + Number(v).toFixed(2));
const png = (bytes) => new Response(bytes, {
  headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=43200" },
});

export function priceChartSpec(rows, rangeKey, { sealed = false } = {}) {
  const mk = [], lo = [];
  for (const r of rows || []) {
    const t = tOf(r.date);
    if (!Number.isFinite(t)) continue;
    // A published $0 is a missing price, not a price: drawn, it is a cliff
    // to the axis that never happened.
    if (Number(r.market_price) > 0) mk.push([t, Number(r.market_price)]);
    if (Number(r.low_price) > 0) lo.push([t, Number(r.low_price)]);
  }
  const legend = [];
  // Sealed product has no condition, so its market price is just "Market".
  if (mk.length) legend.push({ label: sealed ? "Market" : "NM Market", color: THEME.gold, value: money(mk[mk.length - 1][1]) });
  if (lo.length) legend.push({ label: "Low", color: THEME.lilac, value: money(lo[lo.length - 1][1]) });
  return {
    lines: [
      ...(mk.length ? [{ pts: mk, color: THEME.gold, width: 2.6, fill: true, endDot: true }] : []),
      ...(lo.length ? [{ pts: lo, color: THEME.lilac, width: 1.7 }] : []),
    ],
    legend, corner: (RANGES[rangeKey] || {}).label, empty: "No TCGplayer price history yet",
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

export async function chartResponse(url, db) {
  const p = url.pathname.match(/^\/chart\/p\/(\d{1,9})\/([NCHF])\/([a-z0-9]+)\.png$/);
  if (p) {
    const range = RANGES[p[3]];
    if (!range) return new Response("unknown range", { status: 404 });
    const rows = await priceHistory(db, Number(p[1]), FIN_PRINTING[p[2]], { sinceDays: range.days });
    return png(renderChart(priceChartSpec(rows, p[3], { sealed: url.searchParams.get("s") === "1" })));
  }
  const g = url.pathname.match(/^\/chart\/g\/([^/]{1,80})\/([A-Za-z]{2,4})\/(10|[1-9](?:\.5)?)\/([a-z0-9]+)\.png$/);
  if (g) {
    const range = RANGES[g[4]];
    if (!range) return new Response("unknown range", { status: 404 });
    const cardId = decodeURIComponent(g[1]);
    const bucket = url.searchParams.get("b") || "";
    let sales = await gradedSales(db, cardId, g[2].toUpperCase(), g[3]);
    // One market ("") keeps every sale; otherwise only this printing's, and a
    // sale nobody classified belongs to neither.
    if (bucket) sales = sales.filter((s) => gradedSlotBucket(s.printing) === bucket);
    if (range.days) {
      const since = Date.now() - range.days * DAY;
      sales = sales.filter((s) => tOf(s.sold_date) >= since);
    }
    return png(renderChart(salesChartSpec(sales, g[4], `${g[2].toUpperCase()} ${g[3]}`)));
  }
  return new Response("not found", { status: 404 });
}
