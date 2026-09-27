/*
 * Packs.Ink scanner — OpenCV Web Worker.
 *
 * Runs ALL OpenCV.js work (card-quad detection + perspective rectification +
 * CLAHE lighting normalisation) OFF the main thread, so a slow WASM op blocks
 * this worker, never the UI. This is the fix for the page freezing.
 *
 * Protocol (main → worker):
 *   {type:'detect',  id, bitmap}            → {type:'detect',  id, quad|null, w, h}
 *   {type:'rectify', id, bitmap, quad, outW, outH}
 *                                           → {type:'rectify', id, width, height, buffer?} (buffer transferred)
 *   {type:'verify-ref', id, ref:{id,bitmap}}  → {type:'verify-ref', id, ok}  (caches one reference)
 *   {type:'verify',  id, query, refs:[{id,bitmap}], cands:[ids], wantStrip}
 *                                           → {type:'verify', id, scores, ncc, win, strip?}
 *                                             or {type:'verify', id, missing:[ids]}
 * Emits {type:'ready'} once OpenCV's runtime is initialised, or {type:'failed'}.
 *
 * Uses the single-threaded @techstark/opencv-js build (the threaded build is
 * broken under importScripts — opencv#25790 — and would force COOP/COEP).
 */
"use strict";

let cv = null, ready = false;
const CARD_ASPECT = 5 / 7;

// OpenCV is VENDORED same-origin (vendor/opencv/opencv.js, 2026-09-26): it was the
// scanner's last CDN dependency, so a jsDelivr outage took detection down with it,
// and a cross-origin copy can't sit in the service worker's deploy-surviving
// scanner cache. The file is the npm tarball, byte-identical to the jsDelivr copy
// below. jsDelivr stays as the FALLBACK only, for a build that ships without the
// vendored file (an older native bundle) — `src` says which one loaded.
let cvSrc = null;
for (const src of [
  "vendor/opencv/opencv.js",
  "https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.10.0-release.1/dist/opencv.js",
]) {
  try { importScripts(src); cvSrc = src; break; } catch (e) { cvSrc = null; }
}
if (!cvSrc) postMessage({ type: "failed", error: "importScripts: opencv.js unreachable (vendored + CDN)" });

(function initCv() {
  const c = self.cv;
  const done = () => { cv = self.cv; ready = true; postMessage({ type: "ready", src: cvSrc }); };
  if (c instanceof Promise) { c.then((m) => { self.cv = m; done(); }, (e) => postMessage({ type: "failed", error: "cv promise: " + e })); }
  else if (c && c.Mat) { done(); }
  else if (c) { c.onRuntimeInitialized = done; }
  else if (cvSrc) { postMessage({ type: "failed", error: "cv undefined after importScripts" }); }
})();

function bitmapToMat(bitmap) {
  const oc = new OffscreenCanvas(bitmap.width, bitmap.height);
  const ctx = oc.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0);
  const id = ctx.getImageData(0, 0, bitmap.width, bitmap.height);
  return cv.matFromImageData(id);
}

function orderQuad(pts) {
  const bySum = pts.slice().sort((a, b) => (a.x + a.y) - (b.x + b.y));
  const byDiff = pts.slice().sort((a, b) => (a.y - a.x) - (b.y - b.x));
  return [bySum[0], byDiff[0], bySum[3], byDiff[3]]; // TL,TR,BR,BL
}
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
function quadOk(q, minSide) {
  if (!q || q.length !== 4) return false;
  for (let i = 0; i < 4; i++) {
    if (!isFinite(q[i].x) || !isFinite(q[i].y)) return false;
    if (!(dist(q[i], q[(i + 1) % 4]) > (minSide || 12))) return false;
  }
  return true;
}

// median grey level of a single-channel CV_8U Mat (for adaptive Canny).
function medianOfMat(m) {
  const hist = new Uint32Array(256), d = m.data, n = d.length;
  for (let i = 0; i < n; i++) hist[d[i]]++;
  let acc = 0; const half = n / 2;
  for (let v = 0; v < 256; v++) { acc += hist[v]; if (acc >= half) return v; }
  return 128;
}

// Score every contour on an edge map and return the best card-shaped quad.
// `gates` = {rectMin, fillMin, arTol, areaMin}. Rejects non-card shapes:
// rectangularity, ~5:7 aspect (orientation-agnostic via min/max so landscape
// Locations also pass), and "fill" (the contour must mostly fill the quad — drops
// a minAreaRect bounding a sprawling stack). A SOFT centre-bias prefers the card
// the user is pointing at; a clean 4-pt quad beats a minAreaRect fallback (but the
// fallback still wins when it's the only read).
// point inside a convex quad (sign-consistent cross test, tol px slack)
function pointInQuad(p, q, tol) {
  let sign = 0;
  for (let i = 0; i < 4; i++) {
    const a = q[i], b = q[(i + 1) % 4];
    const ex = b.x - a.x, ey = b.y - a.y;
    const len = Math.hypot(ex, ey) || 1;
    const d = (ex * (p.y - a.y) - ey * (p.x - a.x)) / len;
    if (d > tol) { if (sign < 0) return false; sign = 1; }
    else if (d < -tol) { if (sign > 0) return false; sign = -1; }
  }
  return true;
}

function scanForQuad(edges, scale, procW, procH, gates) {
  const contours = new cv.MatVector(), hier = new cv.Mat();
  const imgArea = procW * procH;
  const cx = procW / 2, cy = procH / 2, halfDiag = Math.hypot(cx, cy);
  const cands = [];
  const consider = (q, contourArea, fromClean) => {
    const w1 = dist(q[0], q[1]), w2 = dist(q[3], q[2]);
    const h1 = dist(q[0], q[3]), h2 = dist(q[1], q[2]);
    const wq = (w1 + w2) / 2, hq = (h1 + h2) / 2;
    if (Math.min(wq, hq) < 20) return;
    const rect = (Math.min(w1, w2) / Math.max(w1, w2)) * (Math.min(h1, h2) / Math.max(h1, h2));
    if (rect < gates.rectMin) return;
    const ar = Math.min(wq, hq) / Math.max(wq, hq);
    const arScore = 1 - Math.min(1, Math.abs(ar - CARD_ASPECT) / gates.arTol);
    if (arScore <= 0) return;
    const quadArea = wq * hq, fill = Math.min(1, contourArea / (quadArea + 1e-6));
    if (fill < gates.fillMin) return;
    const qx = (q[0].x + q[1].x + q[2].x + q[3].x) / 4;
    const qy = (q[0].y + q[1].y + q[2].y + q[3].y) / 4;
    const centreScore = 1 - Math.min(1, Math.hypot(qx - cx, qy - cy) / halfDiag);
    let score = arScore * 0.3 + rect * 0.22 + fill * 0.16 + Math.min(1, quadArea / imgArea) * 0.1 + centreScore * 0.22;
    if (!fromClean) score *= 0.92;
    cands.push({ q, score, area: quadArea, landscape: wq > hq });
  };
  try {
    cv.findContours(edges, contours, hier, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE);
    for (let i = 0; i < contours.size(); i++) {
      const c = contours.get(i), area = cv.contourArea(c);
      if (area < imgArea * gates.areaMin) { c.delete(); continue; }
      const peri = cv.arcLength(c, true);
      for (const ep of [0.02, 0.035, 0.05, 0.07]) {
        const a = new cv.Mat();
        cv.approxPolyDP(c, a, ep * peri, true);
        if (a.rows === 4 && cv.isContourConvex(a)) {
          const pts = [];
          for (let p = 0; p < 4; p++) pts.push({ x: a.data32S[p * 2], y: a.data32S[p * 2 + 1] });
          consider(orderQuad(pts), area, true); a.delete(); break;
        }
        a.delete();
      }
      try {
        const rr = cv.minAreaRect(c);
        const box = cv.RotatedRect.points(rr);
        consider(orderQuad([{ x: box[0].x, y: box[0].y }, { x: box[1].x, y: box[1].y },
          { x: box[2].x, y: box[2].y }, { x: box[3].x, y: box[3].y }]), area, false);
      } catch (e) { /* skip */ }
      c.delete();
    }
  } finally { contours.delete(); hier.delete(); }
  if (!cands.length) return { best: null, bestScore: 0, bestLandscape: false };
  let best = cands[0];
  for (const c of cands) if (c.score > best.score) best = c;
  // ART-BOX-TRAP fix: a card's inner art frame (~4:3 landscape ≈ an inverted
  // 5:7) passes every gate and can outscore the true card boundary at close
  // range → landscape-squashed rectifies of portrait cards (field QA ids
  // 90/93/102). If a much larger gate-passing quad fully CONTAINS the winner,
  // take the outer one. Guards (validated on the close+real sets, 0 changes):
  //  · container must be fully INTERIOR to the frame — the image-border contour
  //    passes every gate and contains everything, so it would hijack otherwise;
  //  · ≥1.9× area — art-box→card is ~2.2-3.1×, a stack outline around the top
  //    card is only ~1.2-1.6× (must NOT fire there).
  let chosen = best;
  const m = 0.03 * Math.min(procW, procH);
  for (const c of cands) {
    if (c.area <= best.area * 1.9 || c.area <= chosen.area) continue;
    let interior = true;
    for (const p of c.q) if (!(p.x > m && p.x < procW - m && p.y > m && p.y < procH - m)) { interior = false; break; }
    if (!interior) continue;
    let contains = true;
    for (const p of best.q) if (!pointInQuad(p, c.q, 4)) { contains = false; break; }
    if (contains) chosen = c;
  }
  return {
    best: chosen.q.map((p) => ({ x: p.x / scale, y: p.y / scale })),
    bestScore: chosen.score,
    bestLandscape: chosen.landscape,
  };
}

// Detect best card quad. mat is RGBA at the bitmap resolution; we downscale a
// grayscale copy to ~480px for contour finding, then scale the quad back up.
// TWO PASSES: pass 1 = fixed Canny + standard gates (the path that already works
// for a single flat card / glary foils). Pass 2 runs ONLY when pass 1 finds
// nothing — adaptive low Canny from the image median + a heavier dilate to bridge
// the faint card-on-card edges of a STACK or a dim card, with relaxed gates. Pass
// 2 can't regress a working detection (it only fires on a miss); on the real-photo
// set it lifted detection 73% → 100% (the stacks that were total no-detects now at
// least produce a card to OCR / colour-match / tap-correct).
function detectQuad(mat) {
  const W = mat.cols, H = mat.rows;
  const procW = 480, scale = procW / W, procH = Math.round(H * scale);
  let small = new cv.Mat(), gray = new cv.Mat(), blur = new cv.Mat(), edges = new cv.Mat();
  let res = { best: null, bestScore: 0, bestLandscape: false };
  try {
    cv.resize(mat, small, new cv.Size(procW, procH));
    cv.cvtColor(small, gray, cv.COLOR_RGBA2GRAY);
    // CLAHE so the card's edges survive dim / uneven lighting (edge detection is
    // the bottleneck in low light; CLAHE stays in DETECTION only, never on the
    // rectified card — that would put the query in a different colour space).
    const cl = new cv.CLAHE(3.0, new cv.Size(8, 8));
    cl.apply(gray, gray); cl.delete();
    cv.GaussianBlur(gray, blur, new cv.Size(5, 5), 0);
    // pass 1
    cv.Canny(blur, edges, 40, 120);
    let k = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(7, 7));
    cv.dilate(edges, edges, k); k.delete();
    res = scanForQuad(edges, scale, procW, procH, { rectMin: 0.6, fillMin: 0.7, arTol: 0.26, areaMin: 0.05 });
    // pass 2 (only on a miss)
    if (!res.best) {
      const med = medianOfMat(blur);
      const lo = Math.max(0, Math.round(0.55 * med)), hi = Math.max(lo + 20, Math.round(1.1 * med));
      cv.Canny(blur, edges, lo, hi);
      k = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(9, 9));
      cv.dilate(edges, edges, k); cv.dilate(edges, edges, k); k.delete();
      res = scanForQuad(edges, scale, procW, procH, { rectMin: 0.5, fillMin: 0.55, arTol: 0.30, areaMin: 0.04 });
    }
  } finally {
    small.delete(); gray.delete(); blur.delete(); edges.delete();
  }
  // conf is the winning score (0..1-ish); the main thread gates the green
  // "locked" state on it but always draws a (dim) box when a quad exists.
  return (res.best && quadOk(res.best, 28))
    ? { quad: res.best, conf: res.bestScore, landscape: res.bestLandscape }
    : { quad: null, conf: 0, landscape: false };
}

// gray-world white balance + CLAHE on L — normalises the dim/directional light.
function normalize(mat) {
  // gray-world WB
  const ch = new cv.MatVector();
  cv.split(mat, ch);
  const means = [cv.mean(ch.get(0))[0], cv.mean(ch.get(1))[0], cv.mean(ch.get(2))[0]];
  const g = (means[0] + means[1] + means[2]) / 3 || 1;
  for (let i = 0; i < 3; i++) {
    const m = ch.get(i);
    m.convertTo(m, -1, g / (means[i] || 1), 0);
    ch.set(i, m);
  }
  cv.merge(ch, mat); ch.delete();
  // CLAHE on L
  const lab = new cv.Mat(); cv.cvtColor(mat, lab, cv.COLOR_RGBA2RGB); cv.cvtColor(lab, lab, cv.COLOR_RGB2Lab);
  const lch = new cv.MatVector(); cv.split(lab, lch);
  const clahe = new cv.CLAHE(2.5, new cv.Size(8, 8));
  const l0 = lch.get(0); clahe.apply(l0, l0); lch.set(0, l0); clahe.delete();
  cv.merge(lch, lab); lch.delete();
  cv.cvtColor(lab, lab, cv.COLOR_Lab2RGB); cv.cvtColor(lab, mat, cv.COLOR_RGB2RGBA);
  lab.delete();
}

function rectify(mat, quad, outW, outH) {
  let dst = new cv.Mat(), srcTri = null, dstTri = null, M = null;
  try {
    srcTri = cv.matFromArray(4, 1, cv.CV_32FC2, [quad[0].x, quad[0].y, quad[1].x, quad[1].y, quad[2].x, quad[2].y, quad[3].x, quad[3].y]);
    dstTri = cv.matFromArray(4, 1, cv.CV_32FC2, [0, 0, outW, 0, outW, outH, 0, outH]);
    M = cv.getPerspectiveTransform(srcTri, dstTri);
    cv.warpPerspective(mat, dst, M, new cv.Size(outW, outH), cv.INTER_LINEAR, cv.BORDER_CONSTANT, new cv.Scalar());
    // NOTE: deliberately NOT normalising the rectified card — the reference
    // colour index is built from raw Lorcast art, so CLAHE/WB here would put the
    // query in a different colour space and HURT matching (verified on real
    // photos). CLAHE stays in detectQuad (edges only). colour_sig already
    // mean-centres + L2-normalises, which handles global brightness.
    const out = new ImageData(new Uint8ClampedArray(dst.data), outW, outH);
    return out;
  } finally {
    dst.delete(); if (srcTri) srcTri.delete(); if (dstTri) dstTri.delete(); if (M) M.delete();
  }
}

// ---- VERSION VERIFY: ORB + RANSAC against each candidate printing's own art ----
// (2026-09-26 audit) The name read is good at WHICH CHARACTER and weak at WHICH
// PRINTING, and colour is no help on a camera photo (41% right version). Matching
// ORB keypoints against the candidates' reference art and counting RANSAC
// homography inliers picks the right version 97% of the time on human-reviewed
// field crops, and 98% of the time it is confident. It works on a bad rectify too
// (a homography does not care where the card sits in the crop), which matters
// because the detector frames the card well only a fifth of the time.
// This worker only MEASURES: inliers per candidate, how alike each candidate's art
// is to the winner's (identical art cannot be told apart by keypoints — Epic vs its
// base, a reprint across sets), and the collector-number strip warped through the
// winner's homography for the registered read. The page decides (scanOrbVerdict).
// 1000, measured 2026-09-26 on 40 gold field rows: 1500 = 39/40 right, 395ms warm;
// 1000 = 37/40, 235ms; 700 = 36/40, 138ms. Brute-force matching costs features
// squared and a phone runs ~5x a desktop, while precision-when-confident held at
// 97% at every size — the extra features buy a couple of rows, not certainty.
const ORB_FEATURES = 1000;
const VERIFY_QUERY_SIDE = 900;   // the audit's query size; bigger only adds noise keypoints
const VERIFY_REF_SIDE = 700;     // Lorcast "normal" art is 488x681, i.e. native
const REF_CACHE_MAX = 48;        // a playset re-scans the same family; features are the cost
const THUMB_W = 96, THUMB_H = 134;
// the registered strip: canonical card = 2x the 488x681 reference. The number line
// sits at y .952-.992, x .015-.34; the strip carries y .930-1.0 so the page can try
// a few vertical offsets against a registration error.
const CANON_W = 976, CANON_H = 1362;
const STRIP_X0 = 0.015, STRIP_X1 = 0.34, STRIP_Y0 = 0.930, STRIP_Y1 = 1.0;
const refCache = new Map();
let orbDet = null, bfm = null;

function grayFromBitmap(bitmap, maxSide, keepRgba) {
  const sc = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * sc)), h = Math.max(1, Math.round(bitmap.height * sc));
  const oc = new OffscreenCanvas(w, h);
  const ctx = oc.getContext("2d", { willReadFrequently: true });
  // reference art is transparent outside its rounded corners: composite on white,
  // as the index builder and the audit did, or the corners read as black edges
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h);
  ctx.drawImage(bitmap, 0, 0, w, h);
  const rgba = cv.matFromImageData(ctx.getImageData(0, 0, w, h));
  const gray = new cv.Mat();
  cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY);
  oc.width = 1; oc.height = 1;
  if (!keepRgba) { rgba.delete(); return { gray, w, h, scale: sc }; }
  return { gray, rgba, w, h, scale: sc };
}

function featsOf(gray) {
  if (!orbDet) orbDet = new cv.ORB(ORB_FEATURES);
  const kp = new cv.KeyPointVector(), desc = new cv.Mat(), none = new cv.Mat();
  try { orbDet.detectAndCompute(gray, none, kp, desc); }
  finally { none.delete(); }
  const n = kp.size(), pts = new Float32Array(n * 2);
  for (let i = 0; i < n; i++) { const p = kp.get(i).pt; pts[2 * i] = p.x; pts[2 * i + 1] = p.y; }
  kp.delete();
  return { pts, desc, n };
}

function thumbOfGray(gray) {
  const t = new cv.Mat();
  cv.resize(gray, t, new cv.Size(THUMB_W, THUMB_H), 0, 0, cv.INTER_AREA);
  const n = THUMB_W * THUMB_H, v = new Float32Array(n);
  let mean = 0;
  for (let i = 0; i < n; i++) { v[i] = t.data[i]; mean += v[i]; }
  t.delete();
  mean /= n;
  let norm = 0;
  for (let i = 0; i < n; i++) { v[i] -= mean; norm += v[i] * v[i]; }
  norm = Math.sqrt(norm) || 1;
  for (let i = 0; i < n; i++) v[i] /= norm;
  return v;
}

function nccOf(a, b) {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}

function putRef(id, bitmap) {
  const g = grayFromBitmap(bitmap, VERIFY_REF_SIDE, false);
  try {
    const f = featsOf(g.gray);
    const old = refCache.get(id);
    if (old) { old.desc.delete(); refCache.delete(id); }
    refCache.set(id, { pts: f.pts, desc: f.desc, n: f.n, w: g.w, h: g.h, thumb: thumbOfGray(g.gray) });
  } finally { g.gray.delete(); }
  while (refCache.size > REF_CACHE_MAX) {
    const k = refCache.keys().next().value, v = refCache.get(k);
    v.desc.delete(); refCache.delete(k);
  }
}

// inliers of the query against one reference; H (query-gray -> ref px) when asked
function matchInliers(q, r, wantH) {
  if (q.n < 8 || r.n < 8) return { n: 0, H: null };
  if (!bfm) bfm = new cv.BFMatcher(cv.NORM_HAMMING, false);
  const mm = new cv.DMatchVectorVector(), src = [], dst = [];
  try {
    bfm.knnMatch(q.desc, r.desc, mm, 2);
    for (let i = 0; i < mm.size(); i++) {
      const p = mm.get(i);
      if (p.size() === 2) {
        const a = p.get(0), b = p.get(1);
        if (a.distance < 0.8 * b.distance) {
          src.push(q.pts[2 * a.queryIdx], q.pts[2 * a.queryIdx + 1]);
          dst.push(r.pts[2 * a.trainIdx], r.pts[2 * a.trainIdx + 1]);
        }
      }
      p.delete();
    }
  } finally { mm.delete(); }
  if (src.length / 2 < 8) return { n: 0, H: null };
  const s = cv.matFromArray(src.length / 2, 1, cv.CV_32FC2, src);
  const t = cv.matFromArray(dst.length / 2, 1, cv.CV_32FC2, dst);
  const mask = new cv.Mat();
  let n = 0, H = null, Hm = null;
  try {
    Hm = cv.findHomography(s, t, cv.RANSAC, 6.0, mask);
    for (let i = 0; i < mask.rows; i++) n += mask.data[i] ? 1 : 0;
    if (wantH && Hm && Hm.rows === 3 && Hm.cols === 3) H = Array.from(Hm.data64F);
  } catch (e) { n = 0; H = null; }
  finally { s.delete(); t.delete(); mask.delete(); if (Hm) Hm.delete(); }
  return { n, H };
}

// warp the full-resolution query onto the winner's canonical frame, keeping only
// the collector-number strip. M = T(strip origin) . S(ref -> canonical) . H . Q
function registeredStrip(qRgba, qScale, H, ref) {
  const sx = CANON_W / ref.w, sy = CANON_H / ref.h;
  const x0 = STRIP_X0 * CANON_W, y0 = STRIP_Y0 * CANON_H;
  const sw = Math.round((STRIP_X1 - STRIP_X0) * CANON_W), sh = Math.round((STRIP_Y1 - STRIP_Y0) * CANON_H);
  const A = [sx, 0, -x0, 0, sy, -y0, 0, 0, 1];          // T . S
  const Q = [qScale, 0, 0, 0, qScale, 0, 0, 0, 1];      // full-res query -> query-gray
  const mul = (P, R) => {
    const o = new Array(9).fill(0);
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) for (let k = 0; k < 3; k++) o[3 * i + j] += P[3 * i + k] * R[3 * k + j];
    return o;
  };
  const Mv = mul(mul(A, H), Q);
  const M = cv.matFromArray(3, 3, cv.CV_64FC1, Mv), out = new cv.Mat();
  try {
    cv.warpPerspective(qRgba, out, M, new cv.Size(sw, sh), cv.INTER_CUBIC, cv.BORDER_REPLICATE, new cv.Scalar());
    return { w: sw, h: sh, buffer: new Uint8ClampedArray(out.data).buffer, lineY0: Math.round((0.952 - STRIP_Y0) * CANON_H), lineY1: Math.round((0.992 - STRIP_Y0) * CANON_H) };
  } finally { M.delete(); out.delete(); }
}

function handleVerify(msg) {
  const t0 = Date.now();
  const cands = msg.cands || [];
  for (const r of msg.refs || []) { try { putRef(r.id, r.bitmap); } catch (e) {} finally { if (r.bitmap && r.bitmap.close) r.bitmap.close(); } }
  const missing = cands.filter((id) => !refCache.has(id));
  if (missing.length) {
    if (msg.query && msg.query.close) msg.query.close();
    postMessage({ type: "verify", id: msg.id, missing });
    return;
  }
  let q = null, qf = null, full = null;
  try {
    q = grayFromBitmap(msg.query, VERIFY_QUERY_SIDE, false);
    qf = featsOf(q.gray);
    const scores = {}, Hs = {};
    for (const cid of cands) {
      const r = refCache.get(cid);
      refCache.delete(cid); refCache.set(cid, r);   // LRU touch
      const m = matchInliers(qf, r, true);
      scores[cid] = m.n; if (m.H) Hs[cid] = m.H;
    }
    let win = null;
    for (const cid of cands) if (win === null || scores[cid] > scores[win]) win = cid;
    const ncc = {};
    if (win !== null) { const wt = refCache.get(win).thumb; for (const cid of cands) if (cid !== win) ncc[cid] = Math.round(nccOf(wt, refCache.get(cid).thumb) * 1000) / 1000; }
    let strip = null;
    if (msg.wantStrip && win !== null && Hs[win] && scores[win] >= (msg.minStripInliers || 20)) {
      // the strip needs the full-resolution query: the 900px one leaves the digits ~9px tall
      full = grayFromBitmap(msg.query, 4096, true);
      strip = registeredStrip(full.rgba, q.scale / full.scale, Hs[win], refCache.get(win));
    }
    const reply = { type: "verify", id: msg.id, scores, ncc, win, nq: qf.n, ms: Date.now() - t0, strip };
    postMessage(reply, strip ? [strip.buffer] : []);
  } catch (e) {
    postMessage({ type: "verify", id: msg.id, error: String((e && e.message) || e), ms: Date.now() - t0 });
  } finally {
    if (qf) qf.desc.delete();
    if (q) q.gray.delete();
    if (full) { full.gray.delete(); full.rgba.delete(); }
    if (msg.query && msg.query.close) msg.query.close();
  }
}

onmessage = (e) => {
  const msg = e.data;
  if (msg.type === "detect") {
    if (!ready) { postMessage({ type: "detect", id: msg.id, quad: null, conf: 0, landscape: false }); if (msg.bitmap.close) msg.bitmap.close(); return; }
    let mat = null, det = { quad: null, conf: 0, landscape: false };
    try { mat = bitmapToMat(msg.bitmap); det = detectQuad(mat); } catch (e) { det = { quad: null, conf: 0, landscape: false }; }
    finally { if (mat) mat.delete(); if (msg.bitmap.close) msg.bitmap.close(); }
    postMessage({ type: "detect", id: msg.id, quad: det.quad, conf: det.conf, landscape: det.landscape });
  } else if (msg.type === "capture") {
    // detect + rectify the SAME frame so the warp uses the frame it detected on.
    if (!ready) { postMessage({ type: "capture", id: msg.id, buffer: null, detected: false, quad: null }); if (msg.bitmap.close) msg.bitmap.close(); return; }
    let mat = null, out = null, det = { quad: null, conf: 0, landscape: false };
    try {
      mat = bitmapToMat(msg.bitmap);
      det = detectQuad(mat);
      if (det.quad) {
        // landscape cards (Locations, ~7:5) MUST warp to a landscape canvas — a
        // fixed portrait outW×outH squashes their art + text and breaks both the
        // colour sig and the OCR region. Swap the output dims when landscape.
        const ow = det.landscape ? (msg.outH || 504) : (msg.outW || 360);
        const oh = det.landscape ? (msg.outW || 360) : (msg.outH || 504);
        out = rectify(mat, det.quad, ow, oh);
      }
    } catch (e) { out = null; }
    finally { if (mat) mat.delete(); if (msg.bitmap.close) msg.bitmap.close(); }
    if (out) postMessage({ type: "capture", id: msg.id, width: out.width, height: out.height, detected: true, landscape: det.landscape, conf: det.conf, quad: det.quad, buffer: out.data.buffer }, [out.data.buffer]);
    else postMessage({ type: "capture", id: msg.id, detected: false, conf: det.conf, quad: det.quad, buffer: null });
  } else if (msg.type === "verify") {
    if (!ready) {
      if (msg.query && msg.query.close) msg.query.close();
      for (const r of msg.refs || []) if (r.bitmap && r.bitmap.close) r.bitmap.close();
      postMessage({ type: "verify", id: msg.id, error: "cv not ready" });
      return;
    }
    handleVerify(msg);
  } else if (msg.type === "verify-ref") {
    // one reference's features per message, so the live loop's detect requests
    // get the worker between them (the page sends a cold family one at a time)
    const r = msg.ref || {};
    let ok = false;
    if (ready && r.bitmap) { try { putRef(r.id, r.bitmap); ok = refCache.has(r.id); } catch (e) {} }
    if (r.bitmap && r.bitmap.close) r.bitmap.close();
    postMessage({ type: "verify-ref", id: msg.id, ok });
  }
};
