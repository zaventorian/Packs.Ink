/*
 * Packs.Ink scanner — card detection + perspective rectification (opencv.js).
 *
 * Finds the dominant card-shaped quadrilateral in a camera frame and warps it
 * flat to a canonical image. This is the single biggest accuracy lever: it
 * removes perspective, background and scale variance before matching, and it
 * gives the live "card detected ✓" outline that replaces the old per-frame
 * flicker. Matcher-agnostic — feeds whatever descriptor/embedding runs next.
 *
 * Exposes window.CardCV. opencv.js (~8MB) is lazy-loaded on first use and
 * cached by the service worker afterwards.
 */
(function () {
  "use strict";

  var OPENCV_URL = "https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.10.0-release.1/dist/opencv.js";
  var cvReady = null;
  var CARD_ASPECT = 5 / 7;          // portrait card; locations are the inverse

  function load() {
    if (cvReady) return cvReady;
    cvReady = new Promise(function (resolve, reject) {
      if (window.cv && window.cv.Mat) { resolve(window.cv); return; }
      var s = document.createElement("script");
      s.async = true;
      s.src = OPENCV_URL;
      s.onerror = function () { reject(new Error("opencv.js load failed")); };
      s.onload = function () {
        var cv = window.cv;
        var done = function () { resolve(window.cv); };
        if (cv instanceof Promise) { cv.then(function (m) { window.cv = m; done(); }); }
        else if (window.cv && window.cv.Mat) { done(); }
        else { window.cv = window.cv || {}; window.cv.onRuntimeInitialized = done; }
      };
      document.head.appendChild(s);
    });
    return cvReady;
  }

  // order 4 points TL,TR,BR,BL via sum/diff
  function orderQuad(pts) {
    var bySum = pts.slice().sort(function (a, b) { return (a.x + a.y) - (b.x + b.y); });
    var byDiff = pts.slice().sort(function (a, b) { return (a.y - a.x) - (b.y - b.x); });
    var tl = bySum[0], br = bySum[3], tr = byDiff[0], bl = byDiff[3];
    return [tl, tr, br, bl];
  }
  function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

  // Detect the best card-like quad in a source canvas/video frame.
  // Runs on a downscaled copy for speed; returns quad in SOURCE pixel coords
  // plus a 0..1 score, or null. opts.minAreaFrac default 0.10.
  function detect(src, opts) {
    var cv = window.cv;
    if (!cv || !cv.Mat) return null;
    opts = opts || {};
    var minAreaFrac = opts.minAreaFrac != null ? opts.minAreaFrac : 0.10;
    var sw = src.videoWidth || src.width, sh = src.videoHeight || src.height;
    if (!sw || !sh) return null;
    var procW = 480, scale = procW / sw, procH = Math.round(sh * scale);

    var work = detect._cv || (detect._cv = document.createElement("canvas"));
    work.width = procW; work.height = procH;
    work.getContext("2d").drawImage(src, 0, 0, procW, procH);

    var srcMat = cv.imread(work);
    var gray = new cv.Mat(), blur = new cv.Mat(), edges = new cv.Mat();
    var contours = new cv.MatVector(), hier = new cv.Mat();
    var best = null, bestScore = 0;
    try {
      cv.cvtColor(srcMat, gray, cv.COLOR_RGBA2GRAY);
      cv.GaussianBlur(gray, blur, new cv.Size(5, 5), 0);
      cv.Canny(blur, edges, 60, 180);
      var k = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(5, 5));
      cv.dilate(edges, edges, k); k.delete();
      cv.findContours(edges, contours, hier, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE);
      var imgArea = procW * procH;
      for (var i = 0; i < contours.size(); i++) {
        var c = contours.get(i);
        var area = cv.contourArea(c);
        if (area < imgArea * minAreaFrac) { c.delete(); continue; }
        var peri = cv.arcLength(c, true);
        var approx = new cv.Mat();
        cv.approxPolyDP(c, approx, 0.02 * peri, true);
        if (approx.rows === 4 && cv.isContourConvex(approx)) {
          var pts = [];
          for (var p = 0; p < 4; p++) pts.push({ x: approx.data32S[p * 2], y: approx.data32S[p * 2 + 1] });
          var q = orderQuad(pts);
          var wTop = dist(q[0], q[1]), wBot = dist(q[3], q[2]);
          var hL = dist(q[0], q[3]), hR = dist(q[1], q[2]);
          var w = (wTop + wBot) / 2, h = (hL + hR) / 2;
          var ar = Math.min(w, h) / Math.max(w, h);          // 0..1, ~0.714 for a card
          var arScore = 1 - Math.min(1, Math.abs(ar - CARD_ASPECT) / 0.22);
          var areaScore = Math.min(1, area / imgArea);
          var score = arScore * 0.6 + areaScore * 0.4;
          if (arScore > 0 && score > bestScore) {
            bestScore = score;
            best = q.map(function (pt) { return { x: pt.x / scale, y: pt.y / scale }; });
            best._landscape = w > h;
          }
        }
        approx.delete(); c.delete();
      }
    } finally {
      srcMat.delete(); gray.delete(); blur.delete(); edges.delete(); contours.delete(); hier.delete();
    }
    if (!best) return null;
    return { quad: best, score: bestScore, landscape: !!best._landscape };
  }

  // Warp the detected quad to a canonical flat card canvas (portrait by default).
  function rectify(src, quad, outW, outH) {
    var cv = window.cv;
    outW = outW || 400; outH = outH || 560;
    var work = rectify._cv || (rectify._cv = document.createElement("canvas"));
    var sw = src.videoWidth || src.width, sh = src.videoHeight || src.height;
    work.width = sw; work.height = sh;
    work.getContext("2d").drawImage(src, 0, 0, sw, sh);
    var srcMat = cv.imread(work);
    var dst = new cv.Mat();
    var q = quad;
    // if the card is landscape (location), rotate the source-corner order so the
    // long edge maps to the output width — keeps art upright-ish for matching
    var srcTri = cv.matFromArray(4, 1, cv.CV_32FC2,
      [q[0].x, q[0].y, q[1].x, q[1].y, q[2].x, q[2].y, q[3].x, q[3].y]);
    var dstTri = cv.matFromArray(4, 1, cv.CV_32FC2, [0, 0, outW, 0, outW, outH, 0, outH]);
    var M = cv.getPerspectiveTransform(srcTri, dstTri);
    cv.warpPerspective(srcMat, dst, M, new cv.Size(outW, outH),
      cv.INTER_LINEAR, cv.BORDER_CONSTANT, new cv.Scalar());
    var out = document.createElement("canvas");
    out.width = outW; out.height = outH;
    cv.imshow(out, dst);
    srcMat.delete(); dst.delete(); srcTri.delete(); dstTri.delete(); M.delete();
    return out;
  }

  window.CardCV = { load: load, detect: detect, rectify: rectify, ready: function () { return !!(window.cv && window.cv.Mat); } };
})();
