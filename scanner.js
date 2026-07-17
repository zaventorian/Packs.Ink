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
  var IDXV = "?v=3"; // bump when color.bin/index.json content changes (v3 = Set 13 rebuild 2026-07-14)
  var TXTV = "?v=3"; // bump when text.json content/shape changes (v3 = `s` is the printed SET CODE)

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
    var npx = GRID * GRID, p, i;
    // gray-world white balance: scale each channel to a common mean so a warm/cool
    // colour cast (indoor light / phone auto-WB) doesn't make every card match the
    // yellow/amber reference art. MUST match descriptors.py color_sig — the
    // reference index is built the same way. (Real scans: 2% -> 30% top-1.)
    var mR = 0, mG = 0, mB = 0;
    for (p = 0; p < npx; p++) { mR += data[p * 4]; mG += data[p * 4 + 1]; mB += data[p * 4 + 2]; }
    mR /= npx; mG /= npx; mB /= npx;
    var gray = (mR + mG + mB) / 3;
    var sR = gray / (mR || 1e-3), sG = gray / (mG || 1e-3), sB = gray / (mB || 1e-3);
    var mean = 0, r, g, b;
    for (p = 0; p < npx; p++) {
      r = data[p * 4] * sR; g = data[p * 4 + 1] * sG; b = data[p * 4 + 2] * sB;
      v[p * 3] = r; v[p * 3 + 1] = g; v[p * 3 + 2] = b;
      mean += r + g + b;
    }
    mean /= DIMS;
    var norm = 0;
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
      fetch(BASE + "index.json" + IDXV).then(function (r) { return r.json(); }),
      fetch(BASE + "color.bin" + IDXV).then(function (r) { return r.arrayBuffer(); }),
      fetch(BASE + "dhash.bin" + IDXV).then(function (r) { return r.arrayBuffer(); }),
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
    text.loading = fetch(BASE + "text.json" + TXTV).then(function (r) { return r.json(); }).then(function (cards) {
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

  // ---- NAME matcher (OCR'd name → card): the PRIMARY identity signal ---------
  // Printed text reads the same in a real photo as in the DB — no digital-art
  // domain gap — so a card's NAME is far more reliable than its colours. Colour
  // is demoted to a printing/variant tie-breaker. Mirrors
  // scripts/scanner/ocr_match_validate.py. Built lazily from text.cards.
  var nameDB = null;
  function nmNorm(s){
    s = (s || "").toLowerCase();
    try { s = s.normalize("NFKD").replace(/[̀-ͯ]/g, ""); } catch(e){}
    return s.replace(/['’`._]/g, "").replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
  }
  function nmCanon(s){ return nmNorm(s).replace(/rn/g, "m").replace(/vv/g, "w"); }
  function nmTok(s){ var a = nmNorm(s).split(" "), o = Object.create(null), i; for(i=0;i<a.length;i++) if(a[i].length>=2) o[a[i]]=1; return o; }
  function nmTri(s){ s = "  " + s.replace(/ /g, "") + "  "; var o = Object.create(null), i; for(i=0;i<=s.length-3;i++) o[s.substr(i,3)]=1; return o; }
  function setSize(o){ var n=0,k; for(k in o) n++; return n; }
  function levDist(a, b){
    if(a===b) return 0; if(!a) return b.length; if(!b) return a.length;
    var prev = [], i, j; for(j=0;j<=b.length;j++) prev[j]=j;
    for(i=0;i<a.length;i++){ var cur=[i+1]; for(j=0;j<b.length;j++){ cur[j+1]=Math.min(prev[j+1]+1, cur[j]+1, prev[j]+(a.charAt(i)===b.charAt(j)?0:1)); } prev=cur; }
    return prev[b.length];
  }
  function levSim(a, b){ if(!a.length || !b.length) return 0; if(Math.abs(a.length-b.length) > a.length*0.6) return 0; var L=Math.max(a.length,b.length); return 1 - levDist(a,b)/L; }
  function diceSet(A, B){ var i=0,k,na=setSize(A),nb=setSize(B); if(!na||!nb) return 0; for(k in A) if(B[k]) i++; return 2*i/(na+nb); }
  function tokOverlap(A, B){ var inter=0,k,na=setSize(A),nb=setSize(B); for(k in A) if(B[k]) inter++; var uni=na+nb-inter||1; return 0.5*(inter/uni) + 0.5*(inter/(Math.min(na,nb)||1)); }
  function dedupeIds(arr){ var seen=Object.create(null), out=[], i; for(i=0;i<arr.length;i++){ if(arr[i] && !seen[arr[i]]){ seen[arr[i]]=1; out.push(arr[i]); } } return out; }
  function rrf(lists, weights, k){
    k = k || 60; var score = Object.create(null), i, j;
    for(i=0;i<lists.length;i++){ var w = weights[i]||1, L=lists[i]||[]; for(j=0;j<L.length;j++){ score[L[j]] = (score[L[j]]||0) + w/(k+j+1); } }
    var ids = Object.keys(score); ids.sort(function(a,b){ return score[b]-score[a]; });
    return ids;
  }

  function buildNameDB(){
    if(nameDB || !text.cards) return;
    var cards = text.cards, N = cards.length, i;
    // cnLoose: collector-number → [ids] (across all sets). cnBySet: "SETCODE|number"
    // → [ids] (near-unique: 1-2 cards, the printings). `s` in text.json v3 is the
    // PRINTED set code ("1".."13", "P1", …) — the same token the OCR worker reads
    // off the card's bottom line, so the two sides key identically. byId: id → meta.
    nameDB = { meta: new Array(N), cnLoose: Object.create(null), cnBySet: Object.create(null), byId: Object.create(null) };
    for(i=0;i<N;i++){
      var c = cards[i], nm = c.n || "", ver = c.v || "", full = (nm + " " + ver).replace(/\s+/g," ").trim();
      var tok = nmTok(nm), tv = nmTok(ver), kk; for(kk in tv) tok[kk]=1;
      var cn = nmCanon(nm), cf = nmCanon(full);
      var m = { id: c.id, name: nm, version: ver, set: c.s, nName: cn, nFull: cf, nSq: cn.replace(/ /g,""), nFullSq: cf.replace(/ /g,""), tok: tok, tri: nmTri(cf) };
      nameDB.meta[i] = m; nameDB.byId[c.id] = m;
      if(c.cn != null){ var num = String(c.cn).replace(/\D/g,""); if(num){
        (nameDB.cnLoose[num] = nameDB.cnLoose[num] || []).push(c.id);
        if(c.s){ var k = String(c.s).toUpperCase() + "|" + num; (nameDB.cnBySet[k] = nameDB.cnBySet[k] || []).push(c.id); }
      }}
    }
  }
  // order a small candidate set by name-OCR agreement, then colour rank (the
  // parallel vote: the number narrowed the field, name + colour pick within it).
  function rankCnCandidates(cands, nameTop, colour){
    var namePos = Object.create(null), colPos = Object.create(null), i;
    for(i=0;i<nameTop.length;i++) if(namePos[nameTop[i].id] == null) namePos[nameTop[i].id] = i;
    for(i=0;i<colour.length;i++) if(colPos[colour[i]] == null) colPos[colour[i]] = i;
    return cands.slice().sort(function(a, b){
      var na = namePos[a]==null?99:namePos[a], nb = namePos[b]==null?99:namePos[b];
      if(na !== nb) return na - nb;
      var ca = colPos[a]==null?9999:colPos[a], cb = colPos[b]==null?9999:colPos[b];
      return ca - cb;
    });
  }
  function textScore(qn, qnSq, qtok, qtri, m){
    // compare both spaced and space-stripped forms — OCR often merges or splits
    // words ("LIKEA BIRDIN THESKY"), which the squashed compare is immune to.
    var L = Math.max(levSim(qn, m.nName), levSim(qn, m.nFull), levSim(qnSq, m.nSq), levSim(qnSq, m.nFullSq));
    return 0.42*L + 0.33*tokOverlap(qtok, m.tok) + 0.25*diceSet(qtri, m.tri);
  }
  // rank cards by (possibly garbled) OCR name candidates. `lines` = array of OCR
  // text strings (e.g. the tallest text lines from the name band). Scores each
  // card against the best line. Returns {top:[{id,name,version,score}], conf,
  // margin, marginChar}.
  function rankNames(lines, k){
    buildNameDB(); if(!nameDB) return { top: [], conf: "low", score: 0, margin: 0, marginChar: 0 };
    k = k || 5;
    var queries = [], li;
    for(li=0; li<lines.length; li++){ var qn = nmCanon(lines[li]); if(qn.length < 3) continue; queries.push({ qn: qn, qnSq: qn.replace(/ /g,""), qtok: nmTok(lines[li]), qtri: nmTri(qn) }); }
    if(!queries.length) return { top: [], conf: "low", score: 0, margin: 0, marginChar: 0 };
    var meta = nameDB.meta, best = new Float32Array(meta.length), i, qi;
    for(i=0;i<meta.length;i++){ var s=0; for(qi=0;qi<queries.length;qi++){ var q=queries[qi]; var sc=textScore(q.qn, q.qnSq, q.qtok, q.qtri, meta[i]); if(sc>s) s=sc; } best[i]=s; }
    // look deep enough past k that a card with many printings (6+ Minnies) still
    // reaches the first DIFFERENT character for the margin computation.
    var order = topK(best, Math.max(k, 24));
    var top = order.map(function(ri){ return { id: meta[ri].id, name: meta[ri].name, version: meta[ri].version, score: best[ri] }; });
    var s0 = top[0] ? top[0].score : 0, s1 = top[1] ? top[1].score : 0, margin = s0 - s1;
    // marginChar = gap to the best card of a DIFFERENT character name. The real
    // separator on field reads: a correct read of a distinctive name beats every
    // other character by a wide gap even when its absolute score is mid (garbled
    // OCR), while rules-text bleed matches many characters weakly (tiny gap).
    var n0 = top[0] ? nameDB.byId[top[0].id].nName : "", marginChar = s0;
    for(i=1;i<order.length;i++){
      if(nameDB.meta[order[i]].nName !== n0){ marginChar = s0 - best[order[i]]; break; }
    }
    // conf is CHARACTER-confidence: margin-aware, calibrated on 63 labeled real
    // phone reads (scripts/scanner/conf_calibration.py, 2026-07-10): decisive
    // coverage 6/63 -> 54/63 at 100% precision. Wrong top-1s max out at
    // s0=0.321 / marginChar=0.069 — every branch keeps a buffer above that.
    // (The old absolute-only rule high>=0.80 starved identify(): correct field
    // reads live at 0.37-0.50 and were labeled low -> dead-weight cn reads +
    // no ambient text lock.)
    var conf = (s0 >= 0.72 || (s0 >= 0.42 && marginChar >= 0.10) || (s0 >= 0.36 && marginChar >= 0.15)) ? "high"
             : (s0 >= 0.34 && marginChar >= 0.05) ? "medium" : "low";
    return { top: top.slice(0, k), conf: conf, score: s0, margin: margin, marginChar: marginChar };
  }
  function lookupCN(num){ buildNameDB(); if(!nameDB || num == null) return []; return nameDB.cnLoose[String(num)] || []; }

  // IDENTITY — PARALLEL fusion (vote, don't gate). The collector NUMBER is the
  // backbone: set+number → ~1 card (near-unique primary key). Name-OCR + colour
  // are independent voters that order the narrowed field. Falls back to
  // name-primary, then colour, when the number doesn't read.
  // opts = { lines:[ocr strings], cnNum:"116"|null, cnSet:"12"|null, colourRanked:[ids] }.
  function identify(opts){
    buildNameDB();
    var nm = rankNames(opts.lines || [], 6);
    var colour = opts.colourRanked || [];
    var nameIds = nm.top.map(function(x){ return x.id; });

    // collector-number candidates (a SET-MEMBERSHIP signal — the number narrows
    // 2950 → ~the cards numbered N, but it must NEVER exclude a confident name).
    var numIds = [];
    if(opts.cnNum != null && nameDB){
      var num = String(opts.cnNum).replace(/\D/g, "");
      if(num){
        var setKey = opts.cnSet != null ? String(opts.cnSet).toUpperCase() + "|" + num : null;
        if(setKey && nameDB.cnBySet[setKey]) numIds = nameDB.cnBySet[setKey];
        else numIds = nameDB.cnLoose[num] || [];
      }
    }
    var numSet = Object.create(null), i; for(i=0;i<numIds.length;i++) numSet[numIds[i]] = 1;
    var orderByColour = function(ids){
      var cp = Object.create(null), j; for(j=0;j<colour.length;j++) if(cp[colour[j]]==null) cp[colour[j]]=j;
      return ids.slice().sort(function(a, b){ return (cp[a]==null?1e9:cp[a]) - (cp[b]==null?1e9:cp[b]); });
    };

    // 1. NUMBER + NAME AGREE → lock. The name's best card that is ALSO numbered N
    //    is the strongest, domain-gap-immune identification we can make.
    if(numIds.length){
      for(i=0;i<nameIds.length;i++) if(numSet[nameIds[i]]){
        return { top3: dedupeIds([nameIds[i]].concat(orderByColour(numIds), nameIds, colour)).slice(0, 3), conf: "high", source: "cn+name", nameConf: nm.conf, nameMargin: nm.marginChar, names: nm.top };
      }
    }
    // 2. confident NAME alone → name wins (number absent or misread; colour orders the printing)
    if(nm.conf === "high" && nameIds.length){
      return { top3: dedupeIds(orderByColour(nameIds).concat(colour)).slice(0, 3), conf: "high", source: "name", nameConf: nm.conf, nameMargin: nm.marginChar, names: nm.top };
    }
    // 3. number read but name weak → the numbered cards, ordered by name then colour (needs a tap)
    if(numIds.length){
      var ranked = rankCnCandidates(numIds, nm.top, colour);
      return { top3: dedupeIds(ranked.concat(nameIds, colour)).slice(0, 3), conf: numIds.length <= 2 ? "medium" : "low", source: "cn", nameConf: nm.conf, nameMargin: nm.marginChar, names: nm.top };
    }
    // 4. fallback: name + colour vote
    var fused = rrf([nameIds, colour], [3, 1]);
    return { top3: dedupeIds(fused).slice(0, 3), conf: nm.conf === "medium" ? "medium" : "low", source: "fusion", nameConf: nm.conf, nameMargin: nm.marginChar, names: nm.top };
  }

  window.CardScanner = {
    load: load,
    searchCrop: searchCrop,
    colorSig: colorSig,
    dhash64: dhash64,
    rankNames: rankNames,
    lookupCN: lookupCN,
    identify: identify,
    loadText: loadText,
    textMatch: textMatch,
    get state() { return state; },
    get textState() { return text; },
  };
})();
