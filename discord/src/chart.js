// chart.js — draws a price chart into an RGB buffer and returns PNG bytes.
//
// No canvas exists in a Worker, so this is a small rasteriser: anti-aliased
// strokes (distance to segment, max-coverage per series so joints don't
// double up), an area fill, filled dots, and text from the glyphs baked by
// tools/bake_font.py. Everything is sized for an 800px image that Discord
// shows at ~400px, so 1px of detail here is half a pixel on screen.

import { FONTS } from "./font.generated.js";
import { encodePNG } from "./png.js";

export const THEME = {
  bg: [24, 19, 34],
  grid: [255, 255, 255],
  axis: [168, 160, 190],
  text: [236, 232, 245],
  muted: [150, 142, 172],
  gold: [227, 179, 65],
  lilac: [157, 140, 255],
  green: [92, 196, 128],
  red: [232, 104, 104],
  teal: [86, 196, 206],
};

const DAY = 86400000;
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

// ── glyphs ────────────────────────────────────────────────────────────────
const FACES = {};
function face(name) {
  if (FACES[name]) return FACES[name];
  const f = FONTS[name];
  const bin = atob(f.data);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return (FACES[name] = { ...f, bytes });
}
const glyphOf = (f, ch) => f.glyphs[ch.charCodeAt(0)] || f.glyphs[63]; // "?"

export function measure(str, fontName = "reg") {
  const f = face(fontName);
  let w = 0;
  for (const ch of String(str)) w += glyphOf(f, ch)[4];
  return w;
}

class Canvas {
  constructor(w, h, bg) {
    this.w = w; this.h = h;
    this.px = new Uint8Array(w * h * 3);
    const row = new Uint8Array(w * 3);
    for (let x = 0; x < w; x++) { row[x * 3] = bg[0]; row[x * 3 + 1] = bg[1]; row[x * 3 + 2] = bg[2]; }
    for (let y = 0; y < h; y++) this.px.set(row, y * w * 3);
  }
  blend(x, y, c, a) {
    if (a <= 0 || x < 0 || y < 0 || x >= this.w || y >= this.h) return;
    const i = (y * this.w + x) * 3, p = this.px;
    if (a >= 1) { p[i] = c[0]; p[i + 1] = c[1]; p[i + 2] = c[2]; return; }
    // 8.8 fixed point: three Math.round calls per pixel were a third of the
    // render time.
    const k = (a * 256 + 0.5) | 0;
    p[i] += ((c[0] - p[i]) * k + 128) >> 8;
    p[i + 1] += ((c[1] - p[i + 1]) * k + 128) >> 8;
    p[i + 2] += ((c[2] - p[i + 2]) * k + 128) >> 8;
  }
  hline(x0, x1, y, c, a) { for (let x = Math.max(0, x0); x <= Math.min(this.w - 1, x1); x++) this.blend(x, y, c, a); }
  vline(x, y0, y1, c, a) { for (let y = Math.max(0, y0); y <= Math.min(this.h - 1, y1); y++) this.blend(x, y, c, a); }
  // Text with its baseline at y. align: "left" | "right" | "center". Returns width.
  text(str, x, y, color, { font: fontName = "reg", align = "left", alpha = 1 } = {}) {
    const f = face(fontName);
    const s = String(str);
    const width = measure(s, fontName);
    let pen = align === "right" ? x - width : align === "center" ? x - width / 2 : x;
    for (const ch of s) {
      const [gw, gh, gx, gy, adv, off] = glyphOf(f, ch);
      const ox = Math.round(pen + gx), oy = y + gy;
      for (let j = 0; j < gh; j++) {
        for (let i = 0; i < gw; i++) {
          const k = off + j * gw + i;
          const b = f.bytes[k >> 1];
          const v = (k & 1) ? b & 15 : b >> 4;
          if (v) this.blend(ox + i, oy + j, color, (v / 15) * alpha);
        }
      }
      pen += adv;
    }
    return width;
  }
  disc(cx, cy, r, color, alpha = 1) {
    const x0 = Math.floor(cx - r - 1), x1 = Math.ceil(cx + r + 1);
    const y0 = Math.floor(cy - r - 1), y1 = Math.ceil(cy + r + 1);
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const ex = x + 0.5 - cx, ey = y + 0.5 - cy;
        const d = Math.sqrt(ex * ex + ey * ey);
        const c = Math.min(1, Math.max(0, r + 0.5 - d));
        if (c > 0) this.blend(x, y, color, c * alpha);
      }
    }
  }
  // Anti-aliased polyline. Coverage is accumulated as a MAX per pixel over
  // the whole line and composited once, so the joint between two segments is
  // not blended twice (which draws a dark bead at every data point).
  stroke(pts, color, width, alpha = 1) {
    if (!pts.length) return;
    const hw = width / 2, pad = Math.ceil(hw + 2);
    let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity;
    for (const [x, y] of pts) {
      if (x < minx) minx = x; if (x > maxx) maxx = x;
      if (y < miny) miny = y; if (y > maxy) maxy = y;
    }
    const bx0 = Math.max(0, Math.floor(minx) - pad), by0 = Math.max(0, Math.floor(miny) - pad);
    const bx1 = Math.min(this.w - 1, Math.ceil(maxx) + pad), by1 = Math.min(this.h - 1, Math.ceil(maxy) + pad);
    const bw = bx1 - bx0 + 1, bh = by1 - by0 + 1;
    if (bw <= 0 || bh <= 0) return;
    const cov = new Uint8Array(bw * bh);
    // Composite only what was drawn: the box is most of the plot, the line is
    // a few thousand pixels of it.
    const touched = [];
    const seg = (ax, ay, bx, by) => {
      const x0 = Math.max(bx0, Math.floor(Math.min(ax, bx) - hw - 1));
      const x1 = Math.min(bx1, Math.ceil(Math.max(ax, bx) + hw + 1));
      const y0 = Math.max(by0, Math.floor(Math.min(ay, by) - hw - 1));
      const y1 = Math.min(by1, Math.ceil(Math.max(ay, by) + hw + 1));
      const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
      for (let y = y0; y <= y1; y++) {
        const py = y + 0.5;
        for (let x = x0; x <= x1; x++) {
          const px = x + 0.5;
          let t = len2 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0;
          t = t < 0 ? 0 : t > 1 ? 1 : t;
          const qx = px - (ax + t * dx), qy = py - (ay + t * dy);
          const d = Math.sqrt(qx * qx + qy * qy);
          const c = hw + 0.5 - d;
          if (c <= 0) continue;
          const v = c >= 1 ? 255 : Math.round(c * 255);
          const k = (y - by0) * bw + (x - bx0);
          if (v > cov[k]) { if (!cov[k]) touched.push(k); cov[k] = v; }
        }
      }
    };
    if (pts.length === 1) seg(pts[0][0], pts[0][1], pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) seg(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]);
    for (const k of touched) {
      this.blend(bx0 + (k % bw), by0 + ((k / bw) | 0), color, (cov[k] / 255) * alpha);
    }
  }
}

// ── scales ────────────────────────────────────────────────────────────────
function niceStep(range, target) {
  const raw = range / Math.max(1, target);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / mag;
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
}

// "$2.5k", not "$2,500": the axis gutter is a fixed strip at the left edge,
// and a long label is simply cut off there.
export function fmtAxisMoney(v, step) {
  if (v >= 1000) {
    // As many decimals as the STEP needs: a $2,500 step reads "$12.5k", a
    // $5,000 one "$10k" — and never "$1k" for ten thousand.
    let d = 0;
    while (d < 3 && Math.abs(Math.round((step / 1000) * 10 ** d) - (step / 1000) * 10 ** d) > 1e-9) d++;
    let t = (v / 1000).toFixed(d);
    if (t.includes(".")) t = t.replace(/0+$/, "").replace(/\.$/, "");
    return "$" + t + "k";
  }
  if (step >= 1) return "$" + Math.round(v);
  if (step >= 0.1) return "$" + v.toFixed(v < 10 ? 2 : 1);
  return "$" + v.toFixed(2);
}

function timeTicks(t0, t1) {
  const span = (t1 - t0) / DAY;
  const out = [];
  if (span <= 50) {
    const every = span <= 16 ? 2 : 7;
    const d0 = new Date(t0);
    let t = Date.UTC(d0.getUTCFullYear(), d0.getUTCMonth(), d0.getUTCDate()) + DAY;
    while (t <= t1) {
      const d = new Date(t);
      out.push({ t, label: MON[d.getUTCMonth()] + " " + d.getUTCDate() });
      t += every * DAY;
    }
    return out;
  }
  const steps = [1, 2, 3, 6, 12];
  const months = Math.max(1, span / 30.4);
  const step = steps.find((s) => months / s <= 6) || 12;
  const d0 = new Date(t0);
  let y = d0.getUTCFullYear(), m = d0.getUTCMonth() + 1;
  if (m > 11) { m = 0; y++; }
  while (m % step !== 0) { m++; if (m > 11) { m = 0; y++; } }
  let first = true;
  for (;;) {
    const t = Date.UTC(y, m, 1);
    if (t > t1) break;
    if (t >= t0) {
      const withYear = m === 0 || step >= 6 || (first && span > 200);
      out.push({ t, label: MON[m] + (withYear ? " '" + String(y).slice(2) : "") });
      first = false;
    }
    m += step;
    while (m > 11) { m -= 12; y++; }
  }
  return out;
}

// ── the chart ─────────────────────────────────────────────────────────────
// spec: {
//   w, h,
//   lines:  [{pts:[[t, v]], color, width, fill}],   drawn in order, fill first
//   dots:   [{pts:[[t, v]], color, r}],
//   legend: [{label, color, value}],
//   corner: "3M",                  top-right label beside the brand
//   empty:  "No price history yet" shown when nothing plots
// }
export function renderChart(spec) {
  const W = spec.w || 800, H = spec.h || 340;
  const cv = new Canvas(W, H, THEME.bg);
  const P = { l: 74, r: 22, t: 58, b: 44 };
  let pl = P.l;
  const pr = W - P.r, pt = P.t, pb = H - P.b;

  // header: legend left, brand right
  let lx = 22;
  for (const item of spec.legend || []) {
    cv.disc(lx + 6, 30, 5.5, item.color);
    lx += 18;
    lx += cv.text(item.label, lx, 38, THEME.muted);
    if (item.value) { lx += 8; lx += cv.text(item.value, lx, 38, THEME.text, { font: "bold" }); }
    lx += 26;
  }
  const brandW = measure("packs.ink", "bold");
  cv.text("packs.ink", W - 22, 38, THEME.gold, { font: "bold", align: "right" });
  if (spec.corner) cv.text(spec.corner, W - 22 - brandW - 14, 38, THEME.muted, { align: "right" });

  const all = [];
  for (const s of spec.lines || []) for (const p of s.pts) all.push(p);
  for (const s of spec.dots || []) for (const p of s.pts) all.push(p);
  const good = all.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
  if (!good.length) {
    cv.text(spec.empty || "No price history yet", W / 2, (pt + pb) / 2, THEME.muted, { align: "center" });
    return encodePNG(cv.px, W, H);
  }

  let t0 = Infinity, t1 = -Infinity, v0 = Infinity, v1 = -Infinity;
  for (const [t, v] of good) {
    if (t < t0) t0 = t; if (t > t1) t1 = t;
    if (v < v0) v0 = v; if (v > v1) v1 = v;
  }
  if (spec.t0 != null && spec.t0 < t0) t0 = spec.t0;
  if (t1 - t0 < DAY) { t0 -= DAY; t1 += DAY; }
  // A flat or near-flat series must not be blown up to fill the plot: a 2%
  // wobble drawn floor to ceiling reads as a crash. Keep the visible range at
  // least 20% of the top value.
  const minSpan = Math.max(v1 * 0.2, 0.2);
  if (v1 - v0 < minSpan) {
    const mid = (v0 + v1) / 2;
    v0 = mid - minSpan / 2; v1 = mid + minSpan / 2;
  }
  const padV = (v1 - v0) * 0.08;
  v0 = Math.max(0, v0 - padV); v1 += padV;
  const step = niceStep(v1 - v0, 4);
  const g0 = Math.floor(v0 / step) * step, g1 = Math.ceil(v1 / step) * step;
  v0 = g0; v1 = g1;
  // The gutter is as wide as the widest price label needs, never narrower
  // than the default — so "$0.25" and "$12.5k" both sit fully on the image.
  let widest = 0;
  for (let v = g0; v <= g1 + step / 2; v += step) widest = Math.max(widest, measure(fmtAxisMoney(v, step)));
  pl = Math.max(P.l, Math.ceil(widest) + 26);
  const X = (t) => pl + ((t - t0) / (t1 - t0)) * (pr - pl);
  const Y = (v) => pb - ((v - v0) / (v1 - v0)) * (pb - pt);

  // area fill under each line that asks for one — a per-row colour, because
  // the gradient runs top to bottom of the plot rather than per column
  for (const s of spec.lines || []) {
    if (!s.fill || s.pts.length < 2) continue;
    const pts = s.pts.map(([t, v]) => [X(t), Y(v)]);
    let topY = Infinity;
    for (const [, y] of pts) if (y < topY) topY = y;
    // The fill goes down before anything else, onto plain background, so each
    // row's colour can be worked out once and written straight in.
    const rows = new Uint8Array((pb + 1) * 3);
    for (let y = Math.max(0, Math.floor(topY)); y < pb; y++) {
      const a = 0.3 * Math.max(0, (pb - y) / Math.max(1, pb - topY));
      for (let c = 0; c < 3; c++) rows[y * 3 + c] = Math.round(THEME.bg[c] + (s.color[c] - THEME.bg[c]) * a);
    }
    const px = cv.px;
    let k = 0;
    const xa = Math.max(0, Math.ceil(pts[0][0])), xb = Math.min(W - 1, Math.floor(pts[pts.length - 1][0]));
    for (let x = xa; x <= xb; x++) {
      const cx = x + 0.5;
      while (k < pts.length - 2 && pts[k + 1][0] < cx) k++;
      const [ax, ay] = pts[k], [bx, by] = pts[k + 1];
      const yy = bx === ax ? ay : ay + ((cx - ax) / (bx - ax)) * (by - ay);
      for (let y = Math.max(0, Math.ceil(yy)); y < pb; y++) {
        const i = (y * W + x) * 3;
        px[i] = rows[y * 3]; px[i + 1] = rows[y * 3 + 1]; px[i + 2] = rows[y * 3 + 2];
      }
    }
  }

  // grid + axes
  for (let v = g0; v <= g1 + step / 2; v += step) {
    const y = Math.round(Y(v));
    cv.hline(pl, pr, y, THEME.grid, v === g0 ? 0.16 : 0.07);
    cv.text(fmtAxisMoney(v, step), pl - 12, y + 8, THEME.axis, { align: "right" });
  }
  for (const tk of timeTicks(t0, t1)) {
    const x = Math.round(X(tk.t));
    if (x < pl - 1 || x > pr + 1) continue;
    cv.vline(x, pt, pb, THEME.grid, 0.05);
    cv.text(tk.label, x, H - 16, THEME.axis, { align: "center" });
  }

  for (const s of spec.lines || []) {
    const pts = s.pts.filter((p) => Number.isFinite(p[1])).map(([t, v]) => [X(t), Y(v)]);
    cv.stroke(pts, s.color, s.width || 2.4);
    if (s.endDot && pts.length) {
      const [ex, ey] = pts[pts.length - 1];
      cv.disc(ex, ey, 4.5, s.color);
    }
  }
  for (const s of spec.dots || []) {
    for (const [t, v] of s.pts) cv.disc(X(t), Y(v), s.r || 4, s.color, s.alpha ?? 0.9);
  }
  return encodePNG(cv.px, W, H);
}
