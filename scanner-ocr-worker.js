/*
 * Packs.Ink card scanner — PP-OCRv3 text reader (Web Worker).
 *
 * Replaces Tesseract.js. Runs PaddleOCR PP-OCRv3 (det + rec) entirely on-device
 * via onnxruntime-web, WASM single-thread + SIMD (NO WebGPU — WebGPU crashes iOS
 * Safari). Reading the card's printed NAME is the primary, domain-gap-immune
 * identity signal; the collector NUMBER is the version backbone.
 *
 * Pipeline (mirrors rapidocr_onnxruntime, validated in scripts/scanner/
 * ppocr_web_sim.py at 17/17 character + 58% number on real close photos):
 *   NAME   : det the upper 0.74 of the rectified card -> connected-component
 *            boxes (the card is rectified so text is axis-aligned -> no contours)
 *            -> the 3 tallest boxes that contain a letter -> rec each.
 *   NUMBER : crop the bottom-left ROI, upscale 5x, det -> rec L-to-R -> "147/204".
 *
 * Protocol (promise-by-id, mirrors scanner-worker.js):
 *   main -> {type:"ocr", id, buffer:<rectified RGBA ArrayBuffer>, w, h}
 *   worker -> {type:"result", id, lines:[name candidates, tallest first],
 *              cnNum:"147"|null, cnSet:"12"|null}
 *   worker -> {type:"ready"} once models are loaded; {type:"failed"} on load error.
 *
 * The OCR runs in its OWN worker (not the opencv detect/rectify worker) so a slow
 * ~1s number read never stalls the live ambient hover loop.
 */
"use strict";

var ORT_VER = "1.20.1";
var ORT_BASE = "https://cdn.jsdelivr.net/npm/onnxruntime-web@" + ORT_VER + "/dist/";

// PP-OCRv3 det preprocessing (rapidocr config.yaml, verbatim)
var DET_MEAN = [0.485, 0.456, 0.406];
var DET_STD = [0.229, 0.224, 0.225];
var DET_SIDE = 736; // limit_side_len, limit_type='min'
var DET_THRESH = 0.3; // DBPostProcess.thresh
var DET_BOX_THRESH = 0.5; // DBPostProcess.box_thresh

var det = null, rec = null, DICT = null, ready = false;

self.onmessage = function (e) {
  var d = e.data;
  if (d.type === "ocr") { handleOcr(d); }
};

function fail(err) {
  try { self.postMessage({ type: "failed", error: String(err && err.message || err) }); } catch (_e) {}
}

(function init() {
  try {
    importScripts(ORT_BASE + "ort.wasm.min.js");
  } catch (e) { fail(e); return; }
  var ort = self.ort;
  // WASM only, single-thread (no SharedArrayBuffer / COOP-COEP needed), SIMD on.
  ort.env.wasm.wasmPaths = ORT_BASE;
  ort.env.wasm.numThreads = 1;
  ort.env.wasm.simd = true;
  ort.env.logLevel = "error";

  var opt = { executionProviders: ["wasm"], graphOptimizationLevel: "all" };
  Promise.all([
    fetch("scanner/ch_PP-OCRv3_det_infer.onnx").then(function (r) { return r.arrayBuffer(); }),
    fetch("scanner/ch_PP-OCRv3_rec_infer.onnx").then(function (r) { return r.arrayBuffer(); }),
    fetch("scanner/ppocr_keys_v1.txt").then(function (r) { return r.text(); }),
  ]).then(function (res) {
    var keys = res[2].replace(/\r/g, "").split("\n");
    while (keys.length && keys[keys.length - 1] === "") keys.pop();
    DICT = ["blank"].concat(keys, [" "]); // index 0 = CTC blank, last = space
    return Promise.all([
      ort.InferenceSession.create(res[0], opt),
      ort.InferenceSession.create(res[1], opt),
    ]);
  }).then(function (s) {
    det = s[0]; rec = s[1]; ready = true;
    self.postMessage({ type: "ready" });
  }).catch(fail);
})();

// ---- canvas helpers (OffscreenCanvas; iOS Safari 16.4+) --------------------
function scratch(w, h) {
  var c = new OffscreenCanvas(Math.max(1, w | 0), Math.max(1, h | 0));
  var ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  return { c: c, ctx: ctx };
}

// det preprocessing: crop (sx,sy,sw,sh) of `srcCanvas`, resize to a /32 multiple
// (limit_side_len), normalize (x/255-mean)/std -> NCHW Float32. Returns the tensor
// input dims + the resize ratios (to map det-space boxes back to source space).
function preprocDet(srcCanvas, sx, sy, sw, sh, limitType, side) {
  var ratio;
  if (limitType === "max") ratio = Math.max(sw, sh) > side ? side / Math.max(sw, sh) : 1;
  else ratio = Math.min(sw, sh) < side ? side / Math.min(sw, sh) : 1;
  var rw = Math.max(32, Math.round(sw * ratio / 32) * 32);
  var rh = Math.max(32, Math.round(sh * ratio / 32) * 32);
  var s = scratch(rw, rh);
  s.ctx.drawImage(srcCanvas, sx, sy, sw, sh, 0, 0, rw, rh);
  var data = s.ctx.getImageData(0, 0, rw, rh).data;
  var n = rw * rh, f = new Float32Array(3 * n), p;
  for (var i = 0; i < n; i++) {
    p = i * 4;
    f[i] = (data[p] / 255 - DET_MEAN[0]) / DET_STD[0];
    f[n + i] = (data[p + 1] / 255 - DET_MEAN[1]) / DET_STD[1];
    f[2 * n + i] = (data[p + 2] / 255 - DET_MEAN[2]) / DET_STD[2];
  }
  return { data: f, rw: rw, rh: rh };
}

// DB postprocess WITHOUT contours/minAreaRect: the card is rectified so text is
// axis-aligned -> threshold + connected components + axis-aligned bbox is enough
// (validated at name-parity with rapidocr in ppocr_web_sim.py). Returns boxes in
// SOURCE-crop coords: [{x0,y0,x1,y1,h}].
function ccBoxes(prob, W, H, ratioW, ratioH) {
  // binary (prob > thresh) with a cheap forward 2x2 dilate (bridge 1px gaps)
  var on = new Uint8Array(W * H), x, y, idx;
  for (y = 0; y < H; y++) for (x = 0; x < W; x++) {
    idx = y * W + x;
    if (prob[idx] > DET_THRESH) on[idx] = 1;
  }
  var dil = new Uint8Array(W * H);
  for (y = 0; y < H; y++) for (x = 0; x < W; x++) {
    idx = y * W + x;
    if (on[idx] || (x + 1 < W && on[idx + 1]) || (y + 1 < H && on[idx + W]) ||
        (x + 1 < W && y + 1 < H && on[idx + W + 1])) dil[idx] = 1;
  }
  // 8-connected components via an explicit stack flood fill
  var lab = new Int32Array(W * H), stack = new Int32Array(W * H), boxes = [];
  var minSide = 3;
  for (var start = 0; start < W * H; start++) {
    if (!dil[start] || lab[start]) continue;
    var sp = 0; stack[sp++] = start; lab[start] = 1;
    var minx = W, miny = H, maxx = -1, maxy = -1, sum = 0, cnt = 0;
    while (sp > 0) {
      var cur = stack[--sp];
      var cx = cur % W, cy = (cur / W) | 0;
      if (cx < minx) minx = cx; if (cx > maxx) maxx = cx;
      if (cy < miny) miny = cy; if (cy > maxy) maxy = cy;
      sum += prob[cur]; cnt++;
      for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
        if (!dx && !dy) continue;
        var nx = cx + dx, ny = cy + dy;
        if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
        var ni = ny * W + nx;
        if (dil[ni] && !lab[ni]) { lab[ni] = 1; stack[sp++] = ni; }
      }
    }
    var bw = maxx - minx + 1, bh = maxy - miny + 1;
    if (bw <= minSide || bh <= minSide) continue;
    if (sum / cnt < DET_BOX_THRESH) continue; // box_score_fast (mean prob in box)
    // unclip approx: small proportional pad (rapidocr unclip_ratio=1.6 ~ a few px)
    var pad = Math.max(1, (bh * 0.2) | 0);
    boxes.push([Math.max(0, minx - pad), Math.max(0, miny - pad),
                Math.min(W, maxx + 1 + pad), Math.min(H, maxy + 1 + pad)]);
  }
  boxes = mergeLines(boxes);
  return boxes.map(function (b) {
    return { x0: b[0] / ratioW, y0: b[1] / ratioH, x1: b[2] / ratioW, y1: b[3] / ratioH,
             h: (b[3] - b[1]) / ratioH };
  });
}

// merge boxes on the same text line (vertical overlap + small horizontal gap) so
// a word split into char-blobs reads as one line.
function mergeLines(boxes) {
  boxes.sort(function (a, b) { return a[1] - b[1] || a[0] - b[0]; });
  var merged = [];
  for (var i = 0; i < boxes.length; i++) {
    var b = boxes[i], hit = null;
    for (var j = 0; j < merged.length; j++) {
      var m = merged[j];
      var ov = Math.min(b[3], m[3]) - Math.max(b[1], m[1]);
      var minh = Math.min(b[3] - b[1], m[3] - m[1]) || 1;
      if (ov / minh > 0.5) {
        var gap = Math.max(b[0], m[0]) - Math.min(b[2], m[2]);
        if (gap < 0.6 * minh) { hit = m; break; }
      }
    }
    if (hit) {
      hit[0] = Math.min(hit[0], b[0]); hit[1] = Math.min(hit[1], b[1]);
      hit[2] = Math.max(hit[2], b[2]); hit[3] = Math.max(hit[3], b[3]);
    } else merged.push(b.slice());
  }
  return merged;
}

// rec one text box: crop (x0,y0,x1,y1) of srcCanvas, resize to H=48, normalize
// (x/255-0.5)/0.5 -> NCHW, run rec, CTC greedy decode.
function recOne(srcCanvas, x0, y0, x1, y1) {
  var w = (x1 - x0) | 0, h = (y1 - y0) | 0;
  if (w < 2 || h < 2) return Promise.resolve("");
  var tw = Math.max(8, Math.round(48 * w / h));
  var s = scratch(tw, 48);
  s.ctx.drawImage(srcCanvas, x0, y0, w, h, 0, 0, tw, 48);
  var data = s.ctx.getImageData(0, 0, tw, 48).data;
  var n = tw * 48, f = new Float32Array(3 * n), p;
  for (var i = 0; i < n; i++) {
    p = i * 4;
    f[i] = (data[p] / 255 - 0.5) / 0.5;
    f[n + i] = (data[p + 1] / 255 - 0.5) / 0.5;
    f[2 * n + i] = (data[p + 2] / 255 - 0.5) / 0.5;
  }
  var ort = self.ort;
  var t = new ort.Tensor("float32", f, [1, 3, 48, tw]);
  var feed = {}; feed[rec.inputNames[0]] = t;
  return rec.run(feed).then(function (o) {
    var out = o[rec.outputNames[0]];
    return ctcDecode(out.data, out.dims[1], out.dims[2]);
  });
}

function ctcDecode(data, T, C) {
  var out = "", prev = 0;
  for (var t = 0; t < T; t++) {
    var base = t * C, best = 0, bv = data[base];
    for (var c = 1; c < C; c++) { var v = data[base + c]; if (v > bv) { bv = v; best = c; } }
    if (best !== 0 && best !== prev && best < DICT.length) out += DICT[best];
    prev = best;
  }
  return out;
}

// det a region of srcCanvas, rec every box -> [{text, x0, h}] (source coords).
function ocrRegion(srcCanvas, sx, sy, sw, sh, limitType, side) {
  var pre = preprocDet(srcCanvas, sx, sy, sw, sh, limitType, side);
  var ort = self.ort;
  var t = new ort.Tensor("float32", pre.data, [1, 3, pre.rh, pre.rw]);
  var feed = {}; feed[det.inputNames[0]] = t;
  return det.run(feed).then(function (o) {
    var out = o[det.outputNames[0]]; // [1,1,oh,ow]
    var oh = out.dims[2], ow = out.dims[3];
    var boxes = ccBoxes(out.data, ow, oh, ow / sw, oh / sh);
    // chain the rec calls (one at a time keeps memory flat)
    var res = [];
    return boxes.reduce(function (chain, b) {
      return chain.then(function () {
        return recOne(srcCanvas, sx + b.x0, sy + b.y0, sx + b.x1, sy + b.y1).then(function (txt) {
          if (txt && txt.trim().length >= 1) res.push({ text: txt, x0: b.x0, h: b.h });
        });
      });
    }, Promise.resolve()).then(function () { return res; });
  });
}

function handleOcr(d) {
  if (!ready) { self.postMessage({ type: "result", id: d.id, lines: [], cnNum: null, cnSet: null }); return; }
  var W = d.w, H = d.h;
  var s = scratch(W, H);
  s.ctx.putImageData(new ImageData(new Uint8ClampedArray(d.buffer), W, H), 0, 0);
  var card = s.c;

  // NAME: det the upper 0.74, keep the 3 tallest boxes that contain a letter
  // (excludes the tall cost/lore digits).
  ocrRegion(card, 0, 0, W, Math.round(H * 0.74), "min", DET_SIDE).then(function (lines) {
    var cand = lines.filter(function (l) {
      return l.text.trim().length >= 2 && /[A-Za-z]/.test(l.text);
    }).sort(function (a, b) { return b.h - a.h; });
    var namelines = cand.slice(0, 3).map(function (l) { return l.text; });
    return readNumber(card, W, H).then(function (num) {
      self.postMessage({ type: "result", id: d.id, lines: namelines, cnNum: num.cnNum, cnSet: num.cnSet });
    });
  }).catch(function (err) {
    self.postMessage({ type: "result", id: d.id, lines: [], cnNum: null, cnSet: null, error: String(err && err.message || err) });
  });
}

// NUMBER: crop the bottom-left ROI, upscale 5x (so rec sees the tiny digits), det
// + rec, read "147/204" -> "147". The validated winner ('low .96-1.0 x5' = 64%).
function readNumber(card, W, H) {
  var ROIS = [[0.0, 0.955, 0.50, 1.0, 5], [0.0, 0.93, 0.60, 1.0, 5]];
  var idx = 0;
  function tryNext() {
    if (idx >= ROIS.length) return Promise.resolve({ cnNum: null, cnSet: null });
    var r = ROIS[idx++];
    var rx = Math.round(W * r[0]), ry = Math.round(H * r[1]);
    var rw = Math.round(W * r[2]) - rx, rh = Math.round(H * r[3]) - ry, up = r[4];
    if (rw < 4 || rh < 2) return tryNext();
    var up5 = scratch(rw * up, rh * up);
    up5.ctx.drawImage(card, rx, ry, rw, rh, 0, 0, rw * up, rh * up);
    return ocrRegion(up5.c, 0, 0, rw * up, rh * up, "min", DET_SIDE).then(function (lines) {
      lines.sort(function (a, b) { return a.x0 - b.x0; }); // left-to-right
      var txt = lines.map(function (l) { return l.text; }).join(" ");
      var m = txt.match(/(\d{1,3})\s*[\/Il|1]\s*(\d{2,3})/);
      if (m) {
        var sm = txt.match(/EN[^\d]{0,4}(\d{1,2})/i);
        return { cnNum: m[1], cnSet: sm ? sm[1] : null };
      }
      return tryNext();
    });
  }
  return tryNext();
}
