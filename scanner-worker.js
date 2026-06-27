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
 * Emits {type:'ready'} once OpenCV's runtime is initialised, or {type:'failed'}.
 *
 * Uses the single-threaded @techstark/opencv-js build (the threaded build is
 * broken under importScripts — opencv#25790 — and would force COOP/COEP).
 */
"use strict";

let cv = null, ready = false;
const CARD_ASPECT = 5 / 7;

try {
  importScripts("https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.10.0-release.1/dist/opencv.js");
} catch (e) {
  postMessage({ type: "failed", error: "importScripts: " + (e && e.message) });
}

(function initCv() {
  const c = self.cv;
  const done = () => { cv = self.cv; ready = true; postMessage({ type: "ready" }); };
  if (c instanceof Promise) { c.then((m) => { self.cv = m; done(); }, (e) => postMessage({ type: "failed", error: "cv promise: " + e })); }
  else if (c && c.Mat) { done(); }
  else if (c) { c.onRuntimeInitialized = done; }
  else { postMessage({ type: "failed", error: "cv undefined after importScripts" }); }
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

// Detect best card quad. mat is RGBA at the bitmap resolution; we downscale a
// grayscale copy to ~480px for contour finding, then scale the quad back up.
function detectQuad(mat) {
  const W = mat.cols, H = mat.rows;
  const procW = 480, scale = procW / W, procH = Math.round(H * scale);
  let small = new cv.Mat(), gray = new cv.Mat(), blur = new cv.Mat(), edges = new cv.Mat();
  let contours = new cv.MatVector(), hier = new cv.Mat();
  let best = null, bestScore = 0, bestLandscape = false;
  try {
    cv.resize(mat, small, new cv.Size(procW, procH));
    cv.cvtColor(small, gray, cv.COLOR_RGBA2GRAY);
    // boost local contrast so the card's edges survive dim / uneven lighting —
    // edge detection is the bottleneck in low light, and CLAHE makes the card
    // border detectable when raw Canny would miss it entirely.
    const cl = new cv.CLAHE(3.0, new cv.Size(8, 8));
    cl.apply(gray, gray); cl.delete();
    cv.GaussianBlur(gray, blur, new cv.Size(5, 5), 0);
    cv.Canny(blur, edges, 40, 120);
    const k = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(7, 7));
    cv.dilate(edges, edges, k); k.delete();
    cv.findContours(edges, contours, hier, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE);
    const imgArea = procW * procH;
    const cx = procW / 2, cy = procH / 2, halfDiag = Math.hypot(cx, cy);
    // score a candidate quad; keep the best. Rejects non-card shapes:
    // rectangularity (opposite sides similar), ~5:7 aspect (orientation-agnostic
    // via min/max so landscape Locations also pass), and "fill" (the contour must
    // mostly fill the quad — rejects a minAreaRect bounding a sprawling stack
    // contour). A SOFT centre-bias prefers the card the user is pointing at over a
    // larger background rectangle, and a clean 4-pt quad is preferred over a
    // minAreaRect fallback (but the fallback still wins when it's the only read).
    const consider = (q, contourArea, fromClean) => {
      const w1 = dist(q[0], q[1]), w2 = dist(q[3], q[2]);
      const h1 = dist(q[0], q[3]), h2 = dist(q[1], q[2]);
      const wq = (w1 + w2) / 2, hq = (h1 + h2) / 2;
      if (Math.min(wq, hq) < 20) return;
      const rect = (Math.min(w1, w2) / Math.max(w1, w2)) * (Math.min(h1, h2) / Math.max(h1, h2));
      if (rect < 0.6) return;
      const ar = Math.min(wq, hq) / Math.max(wq, hq);
      const arScore = 1 - Math.min(1, Math.abs(ar - CARD_ASPECT) / 0.26);
      if (arScore <= 0) return;
      const quadArea = wq * hq, fill = Math.min(1, contourArea / (quadArea + 1e-6));
      if (fill < 0.7) return;
      const qx = (q[0].x + q[1].x + q[2].x + q[3].x) / 4;
      const qy = (q[0].y + q[1].y + q[2].y + q[3].y) / 4;
      const centreScore = 1 - Math.min(1, Math.hypot(qx - cx, qy - cy) / halfDiag);
      let score = arScore * 0.3 + rect * 0.22 + fill * 0.16 + Math.min(1, quadArea / imgArea) * 0.1 + centreScore * 0.22;
      if (!fromClean) score *= 0.92;
      if (score > bestScore) {
        bestScore = score;
        best = q.map((p) => ({ x: p.x / scale, y: p.y / scale }));
        bestLandscape = wq > hq;
      }
    };
    for (let i = 0; i < contours.size(); i++) {
      const c = contours.get(i), area = cv.contourArea(c);
      if (area < imgArea * 0.05) { c.delete(); continue; }
      const peri = cv.arcLength(c, true);
      // (1) clean 4-point quad — best for perspective
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
      // (2) fallback: best-fit rotated rectangle — robust to imperfect / merged
      // contours (a card sitting on a stack rarely gives a clean 4-pt edge)
      try {
        const rr = cv.minAreaRect(c);
        const box = cv.RotatedRect.points(rr);
        consider(orderQuad([{ x: box[0].x, y: box[0].y }, { x: box[1].x, y: box[1].y },
          { x: box[2].x, y: box[2].y }, { x: box[3].x, y: box[3].y }]), area, false);
      } catch (e) { /* skip */ }
      c.delete();
    }
  } finally {
    small.delete(); gray.delete(); blur.delete(); edges.delete(); contours.delete(); hier.delete();
  }
  // conf is the winning score (0..1-ish); the main thread gates the green
  // "locked" state on it but always draws a (dim) box when a quad exists.
  return (best && quadOk(best, 28))
    ? { quad: best, conf: bestScore, landscape: bestLandscape }
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
  }
};
