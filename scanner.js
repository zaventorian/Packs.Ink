/*
 * Packs.Ink card scanner — on-device visual matcher.
 *
 * Loads the shipped descriptor index (scanner/index.json + color.bin + dhash.bin)
 * and matches a camera frame (canvas) against ~2,950 Lorcana cards entirely in the
 * browser. No backend, no per-scan cost. Mirrors scripts/scanner/descriptors.py:
 *   - colorSig: 12x12 RGB grid, global mean-centred + L2-normalised (432-dim)
 *   - dhash64 : 9x8 grayscale horizontal-gradient hash (light tiebreaker)
 *
 * Ranking is cosine (dot product, since refs are unit-norm) on the colour sig;
 * the top-K are re-ranked with a small dHash-hamming penalty to separate cards
 * that share a colour palette but differ in layout.
 *
 * Exposes window.CardScanner. Classic script (no build step), like logo.js.
 */
(function () {
  "use strict";

  var GRID = 12;
  var DIMS = GRID * GRID * 3; // 432
  var BASE = "scanner/";

  var state = {
    loaded: false,
    loading: null,
    count: 0,
    dims: DIMS,
    scale: 1,
    color: null, // Int8Array(count*DIMS)
    dhashLo: null, // Uint32Array(count)
    dhashHi: null, // Uint32Array(count)
    cards: null, // [{id,name,version,set_id,rarity,art_key}]
  };

  // --- reusable offscreen canvases (avoid per-frame allocation) ---
  var tmp = document.createElement("canvas");
  var tmpCtx = tmp.getContext("2d", { willReadFrequently: true });
  var small = document.createElement("canvas");
  small.width = GRID; small.height = GRID;
  var smallCtx = small.getContext("2d", { willReadFrequently: true });
  var gcv = document.createElement("canvas");
  gcv.width = 9; gcv.height = 8;
  var gctx = gcv.getContext("2d", { willReadFrequently: true });

  function popcount(x) {
    x = x - ((x >>> 1) & 0x55555555);
    x = (x & 0x33333333) + ((x >>> 2) & 0x33333333);
    x = (x + (x >>> 4)) & 0x0f0f0f0f;
    return (x * 0x01010101) >>> 24;
  }

  // Two-step high-quality downscale of a source (canvas/video/image region) to
  // GRIDxGRID, then the colour sig. `sx,sy,sw,sh` = crop rect in the source.
  function colorSig(src, sx, sy, sw, sh) {
    var mid = 48;
    tmp.width = mid; tmp.height = mid;
    tmpCtx.imageSmoothingEnabled = true;
    tmpCtx.imageSmoothingQuality = "high";
    tmpCtx.drawImage(src, sx, sy, sw, sh, 0, 0, mid, mid);
    smallCtx.imageSmoothingEnabled = true;
    smallCtx.imageSmoothingQuality = "high";
    smallCtx.drawImage(tmp, 0, 0, mid, mid, 0, 0, GRID, GRID);
    var data = smallCtx.getImageData(0, 0, GRID, GRID).data; // RGBA, row-major
    var v = new Float32Array(DIMS);
    var mean = 0, p, c, val;
    for (p = 0; p < GRID * GRID; p++) {
      for (c = 0; c < 3; c++) {
        val = data[p * 4 + c];
        v[p * 3 + c] = val;
        mean += val;
      }
    }
    mean /= DIMS;
    var norm = 0, i;
    for (i = 0; i < DIMS; i++) { v[i] -= mean; norm += v[i] * v[i]; }
    norm = Math.sqrt(norm) || 1;
    for (i = 0; i < DIMS; i++) v[i] /= norm;
    return v;
  }

  // dHash: 9x8 grayscale (ITU-R 601, matching PIL "L"), horizontal gradient.
  function dhash64(src, sx, sy, sw, sh) {
    gctx.imageSmoothingEnabled = true;
    gctx.imageSmoothingQuality = "high";
    gctx.drawImage(src, sx, sy, sw, sh, 0, 0, 9, 8);
    var d = gctx.getImageData(0, 0, 9, 8).data;
    var g = new Float32Array(72), k;
    for (k = 0; k < 72; k++) {
      g[k] = 0.299 * d[k * 4] + 0.587 * d[k * 4 + 1] + 0.114 * d[k * 4 + 2];
    }
    var lo = 0, hi = 0, bit = 0, y, x, idx;
    for (y = 0; y < 8; y++) {
      for (x = 0; x < 8; x++) {
        idx = y * 9 + x;
        var on = g[idx + 1] > g[idx] ? 1 : 0;
        if (bit < 32) lo = (lo | (on << bit)) >>> 0;
        else hi = (hi | (on << (bit - 32))) >>> 0;
        bit++;
      }
    }
    return { lo: lo >>> 0, hi: hi >>> 0 };
  }

  function load() {
    if (state.loaded) return Promise.resolve(state);
    if (state.loading) return state.loading;
    state.loading = Promise.all([
      fetch(BASE + "index.json").then(function (r) { return r.json(); }),
      fetch(BASE + "color.bin").then(function (r) { return r.arrayBuffer(); }),
      fetch(BASE + "dhash.bin").then(function (r) { return r.arrayBuffer(); }),
    ]).then(function (res) {
      var man = res[0];
      state.count = man.count;
      state.dims = man.dims;
      state.scale = man.scale || 1;
      state.cards = man.cards;
      state.color = new Int8Array(res[1]);
      var dv = new DataView(res[2]);
      state.dhashLo = new Uint32Array(man.count);
      state.dhashHi = new Uint32Array(man.count);
      for (var i = 0; i < man.count; i++) {
        state.dhashLo[i] = dv.getUint32(i * 8, true);
        state.dhashHi[i] = dv.getUint32(i * 8 + 4, true);
      }
      state.loaded = true;
      return state;
    });
    return state.loading;
  }

  // Search a prepared crop. Returns top-k [{row, card, color, dist}].
  // `lambda` blends dHash hamming into the top-N re-rank (0 = colour only).
  function searchCrop(src, sx, sy, sw, sh, k, lambda) {
    if (!state.loaded) throw new Error("CardScanner not loaded");
    k = k || 5;
    lambda = lambda == null ? 0.12 : lambda;
    var qv = colorSig(src, sx, sy, sw, sh);
    var qd = dhash64(src, sx, sy, sw, sh);
    var color = state.color, dims = state.dims, n = state.count;
    // colour dot products (refs are unit-norm * scale; scale is constant so it
    // doesn't affect ranking)
    var scores = new Float32Array(n);
    var base = 0, i, d, acc;
    for (i = 0; i < n; i++) {
      acc = 0; base = i * dims;
      for (d = 0; d < dims; d++) acc += qv[d] * color[base + d];
      scores[i] = acc;
    }
    // take top-K2 by colour, then re-rank with dHash penalty
    var K2 = Math.max(k, 25);
    var idxs = topK(scores, K2);
    var colMax = scores[idxs[0]] || 1;
    var reranked = idxs.map(function (ri) {
      var ham = popcount((state.dhashLo[ri] ^ qd.lo) >>> 0) +
                popcount((state.dhashHi[ri] ^ qd.hi) >>> 0);
      // normalise colour to ~[0,1] vs the round's best, subtract dHash penalty
      var blended = (scores[ri] / colMax) - lambda * (ham / 64);
      return { row: ri, score: scores[ri], blended: blended, ham: ham };
    });
    reranked.sort(function (a, b) { return b.blended - a.blended; });
    return reranked.slice(0, k).map(function (r) {
      return {
        row: r.row,
        card: state.cards[r.row],
        color: r.score,
        ham: r.ham,
        blended: r.blended,
      };
    });
  }

  function topK(scores, k) {
    // simple partial selection; n is small (~3k) so this is fine per frame
    var n = scores.length;
    var idx = new Array(n);
    for (var i = 0; i < n; i++) idx[i] = i;
    idx.sort(function (a, b) { return scores[b] - scores[a]; });
    return idx.slice(0, k);
  }

  // ---- text matcher (OCR'd card text → fuzzy match vs the card DB) ----------
  // Validated to fix the cases colour confuses (Helga, Joshua Sweet): even
  // garbled OCR matches because distinctive name/ability tokens carry weight
  // (IDF — rare tokens score high, generic "during your turn" tokens don't).
  var text = { loaded: false, loading: null, cards: null, toks: null, idf: null };

  function tnorm(s) { return (s || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim(); }
  function ttoks(s) { return tnorm(s).split(" ").filter(function (w) { return w.length >= 3; }); }

  function loadText() {
    if (text.loaded) return Promise.resolve(text);
    if (text.loading) return text.loading;
    text.loading = fetch(BASE + "text.json").then(function (r) { return r.json(); }).then(function (cards) {
      text.cards = cards;
      var N = cards.length, df = Object.create(null);
      text.toks = new Array(N);
      for (var i = 0; i < N; i++) {
        var set = Object.create(null), ts = ttoks(cards[i].b);
        for (var j = 0; j < ts.length; j++) set[ts[j]] = 1;
        text.toks[i] = set;
        for (var t in set) df[t] = (df[t] || 0) + 1;
      }
      var idf = Object.create(null);
      for (var k in df) idf[k] = Math.log(N / (df[k] + 1));
      text.idf = idf; text.loaded = true;
      return text;
    });
    return text.loading;
  }

  // ocrText = raw OCR string; returns top-k [{id,name,version,score}]
  function textMatch(ocrText, k) {
    if (!text.loaded) return [];
    k = k || 8;
    var qset = Object.create(null), qt = ttoks(ocrText), i;
    for (i = 0; i < qt.length; i++) qset[qt[i]] = 1;
    // collector-number hint: any 1-3 digit group followed by /  (e.g. 175/204)
    var cnHints = (ocrText.match(/\b(\d{1,3})\s*\/\s*\d{2,3}\b/g) || [])
      .map(function (m) { return m.replace(/\s*\/.*$/, ""); });
    var cards = text.cards, toks = text.toks, idf = text.idf, N = cards.length;
    var scores = new Float32Array(N);
    for (i = 0; i < N; i++) {
      var s = 0, set = toks[i];
      for (var w in qset) if (set[w]) s += idf[w];
      if (cnHints.length && cards[i].cn && cnHints.indexOf(String(cards[i].cn)) >= 0) s += 6; // boost
      scores[i] = s;
    }
    var order = topK(scores, Math.max(k, 12));
    return order.slice(0, k).map(function (ri) {
      return { id: cards[ri].id, name: cards[ri].n, version: cards[ri].v, score: scores[ri] };
    });
  }

  window.CardScanner = {
    load: load,
    searchCrop: searchCrop,
    colorSig: colorSig,
    dhash64: dhash64,
    loadText: loadText,
    textMatch: textMatch,
    get state() { return state; },
    get textState() { return text; },
  };
})();
