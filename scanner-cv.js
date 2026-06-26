/*
 * Packs.Ink scanner — card detection + perspective rectification (opencv.js).
 *
 * Finds the dominant card-shaped quadrilateral in a captured frame and warps it
 * flat to a canonical image — the single biggest accuracy lever (removes
 * perspective/background/scale before matching). Runs ONCE per user tap (not in
 * a live loop) and every opencv call is wrapped: any failure sets a `broken`
 * flag, returns null, and the caller falls back to a plain crop. opencv's WASM
 * can abort() on a degenerate input and that must never crash the app.
 *
 * Exposes window.CardCV. opencv.js (~10MB) is lazy-loaded from jsDelivr on first
 * use and cached by the service worker afterwards.
 */
(function () {
  "use strict";

  var OPENCV_URL = "https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.10.0-release.1/dist/opencv.js";
  var cvReady = null;
  var broken = false;            // once opencv errors, stop using it this session
  var CARD_ASPECT = 5 / 7;

  function load() {
    if (broken) return Promise.reject(new Error("opencv unavailable"));
    if (cvReady) return cvReady;
    cvReady = new Promise(function (resolve, reject) {
      if (window.cv && window.cv.Mat) { resolve(window.cv); return; }
      var s = document.createElement("script");
      s.async = true; s.src = OPENCV_URL;
      s.onerror = function () { broken = true; reject(new Error("opencv.js load failed")); };
      s.onload = function () {
        var cv = window.cv;
        var done = function () { resolve(window.cv); };
        if (cv instanceof Promise) { cv.then(function (m) { window.cv = m; done(); }, function () { broken = true; reject(new Error("opencv init failed")); }); }
        else if (window.cv && window.cv.Mat) { done(); }
        else { window.cv = window.cv || {}; window.cv.onRuntimeInitialized = done; }
      };
      document.head.appendChild(s);
    });
    return cvReady;
  }

  function orderQuad(pts) {
    var bySum = pts.slice().sort(function (a, b) { return (a.x + a.y) - (b.x + b.y); });
    var byDiff = pts.slice().sort(function (a, b) { return (a.y - a.x) - (b.y - b.x); });
    return [bySum[0], byDiff[0], bySum[3], byDiff[3]]; // TL, TR, BR, BL
  }
  function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

  // a quad is usable only if it's non-degenerate: 4 finite points, every side a
  // reasonable length, sides roughly card-proportioned. Guards getPerspectiveTransform.
  function quadOk(q, minSide) {
    if (!q || q.length !== 4) return false;
    for (var i = 0; i < 4; i++) {
      if (!isFinite(q[i].x) || !isFinite(q[i].y)) return false;
      var d = dist(q[i], q[(i + 1) % 4]);
      if (!(d > (minSide || 12))) return false;
    }
    return true;
  }

  // Detect the best card-like quad in a source canvas/video frame. Returns
  // { quad:[{x,y}x4 in source px], score, landscape } or null. Never throws.
  function detect(src, opts) {
    if (broken || !window.cv || !window.cv.Mat) return null;
    opts = opts || {};
    var cv = window.cv;
    var minAreaFrac = opts.minAreaFrac != null ? opts.minAreaFrac : 0.08;
    var sw = src.videoWidth || src.width, sh = src.videoHeight || src.height;
    if (!sw || !sh) return null;
    var procW = 480, scale = procW / sw, procH = Math.round(sh * scale);
    var work = detect._cv || (detect._cv = document.createElement("canvas"));
    work.width = procW; work.height = procH;
    work.getContext("2d").drawImage(src, 0, 0, procW, procH);

    var srcMat, gray, blur, edges, contours, hier, best = null, bestScore = 0;
    try {
      srcMat = cv.imread(work);
      gray = new cv.Mat(); blur = new cv.Mat(); edges = new cv.Mat();
      contours = new cv.MatVector(); hier = new cv.Mat();
      cv.cvtColor(srcMat, gray, cv.COLOR_RGBA2GRAY);
      cv.GaussianBlur(gray, blur, new cv.Size(5, 5), 0);
      cv.Canny(blur, edges, 60, 180);
      var k = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(5, 5));
      cv.dilate(edges, edges, k); k.delete();
      cv.findContours(edges, contours, hier, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE);
      var imgArea = procW * procH;
      for (var i = 0; i < contours.size(); i++) {
        var c = contours.get(i), area = cv.contourArea(c);
        if (area < imgArea * minAreaFrac) { c.delete(); continue; }
        var approx = new cv.Mat();
        cv.approxPolyDP(c, approx, 0.02 * cv.arcLength(c, true), true);
        if (approx.rows === 4 && cv.isContourConvex(approx)) {
          var pts = [];
          for (var p = 0; p < 4; p++) pts.push({ x: approx.data32S[p * 2], y: approx.data32S[p * 2 + 1] });
          var q = orderQuad(pts);
          if (quadOk(q, 24)) {
            var w = (dist(q[0], q[1]) + dist(q[3], q[2])) / 2;
            var h = (dist(q[0], q[3]) + dist(q[1], q[2])) / 2;
            var ar = Math.min(w, h) / Math.max(w, h);
            var arScore = 1 - Math.min(1, Math.abs(ar - CARD_ASPECT) / 0.22);
            var score = arScore * 0.6 + Math.min(1, area / imgArea) * 0.4;
            if (arScore > 0 && score > bestScore) {
              bestScore = score;
              best = q.map(function (pt) { return { x: pt.x / scale, y: pt.y / scale }; });
              best._landscape = w > h;
            }
          }
        }
        approx.delete(); c.delete();
      }
    } catch (e) {
      broken = true; best = null;
    } finally {
      if (srcMat) srcMat.delete(); if (gray) gray.delete(); if (blur) blur.delete();
      if (edges) edges.delete(); if (contours) contours.delete(); if (hier) hier.delete();
    }
    if (!best || !quadOk(best, 30)) return null;
    return { quad: best, score: bestScore, landscape: !!best._landscape };
  }

  // Warp the detected quad to a flat canonical card canvas. Source is downscaled
  // before imread to keep WASM memory low. Returns a canvas, or null on failure.
  function rectify(src, quad, outW, outH) {
    if (broken || !window.cv || !window.cv.Mat) return null;
    if (!quadOk(quad, 24)) return null;
    var cv = window.cv;
    outW = outW || 360; outH = outH || 504;
    var sw = src.videoWidth || src.width, sh = src.videoHeight || src.height;
    var sc = Math.min(1, 1280 / Math.max(sw, sh));
    var dw = Math.max(1, Math.round(sw * sc)), dh = Math.max(1, Math.round(sh * sc));
    var work = rectify._cv || (rectify._cv = document.createElement("canvas"));
    work.width = dw; work.height = dh;
    work.getContext("2d").drawImage(src, 0, 0, sw, sh, 0, 0, dw, dh);
    var q = quad.map(function (p) { return { x: p.x * sc, y: p.y * sc }; });
    var srcMat, dst, srcTri, dstTri, M, out = null;
    try {
      srcMat = cv.imread(work); dst = new cv.Mat();
      srcTri = cv.matFromArray(4, 1, cv.CV_32FC2, [q[0].x, q[0].y, q[1].x, q[1].y, q[2].x, q[2].y, q[3].x, q[3].y]);
      dstTri = cv.matFromArray(4, 1, cv.CV_32FC2, [0, 0, outW, 0, outW, outH, 0, outH]);
      M = cv.getPerspectiveTransform(srcTri, dstTri);
      cv.warpPerspective(srcMat, dst, M, new cv.Size(outW, outH), cv.INTER_LINEAR, cv.BORDER_CONSTANT, new cv.Scalar());
      out = document.createElement("canvas"); out.width = outW; out.height = outH;
      cv.imshow(out, dst);
    } catch (e) {
      broken = true; out = null;
    } finally {
      if (srcMat) srcMat.delete(); if (dst) dst.delete(); if (srcTri) srcTri.delete();
      if (dstTri) dstTri.delete(); if (M) M.delete();
    }
    return out;
  }

  window.CardCV = {
    load: load, detect: detect, rectify: rectify,
    ready: function () { return !broken && !!(window.cv && window.cv.Mat); },
    isBroken: function () { return broken; },
  };
})();
