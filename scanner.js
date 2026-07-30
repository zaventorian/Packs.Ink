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
  var IDXV = "?v=5"; // bump when color.bin/index.json content changes (v5 = Locations rotated upright + 3210 cards, 2026-07-29; v4 = Set 13 REAL Lorcast art)
  var TXTV = "?v=5"; // bump when text.json content/shape changes (v5 = +rarity code `r` for base-before-chase ordering, 2026-07-23)

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
      // CANONICAL ORDER — base printing before chase reprints (v16, 2026-07-23).
      // Same-(name,version) groups (base + Enchanted/Iconic/Epic/Promo reprints
      // + custom variants) arrived in DB fetch order (no ORDER BY = arbitrary),
      // and every downstream tie inherited it: rankNames' topK is a stable sort,
      // rankVersions*' per-version id lists push in this order, orderByColour is
      // stable for colour-unranked ids. Net effect: ~half the reprint pairs
      // defaulted to the CHASE card on a text-identical read (v15 field: Scar -
      // Finally King → Enchanted ×4, Merida → Iconic ×5, Hades → Iconic ×3,
      // Show Me More! → Enchanted…). One stable sort here fixes every consumer:
      // within a group the base printing leads; chase/custom reprints win only
      // on positive evidence (colour rank, exact collector number). Groups keep
      // their first-occurrence position; members become adjacent. `r` is the
      // rarity code from text.json v5 (missing on a stale cache → no reorder,
      // which is just the old behavior).
      var CHASE_R = { E: 1, I: 1, X: 1, P: 1 };  // Enchanted / Iconic / Epic / Promo
      var firstAt = Object.create(null), ci;
      for (ci = 0; ci < cards.length; ci++) {
        var cc = cards[ci], gk = (cc.n || "") + "|" + (cc.v || "");
        if (firstAt[gk] == null) firstAt[gk] = ci;
        cc._gk = gk; cc._i = ci;
        cc._demote = (CHASE_R[cc.r] ? 2 : 0) + (String(cc.id).lastIndexOf("crd_custom_", 0) === 0 ? 1 : 0);
      }
      cards.sort(function (a, b) {
        if (firstAt[a._gk] !== firstAt[b._gk]) return firstAt[a._gk] - firstAt[b._gk];
        if (a._demote !== b._demote) return a._demote - b._demote;
        return a._i - b._i;
      });
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
      var cv = nmCanon(ver);
      var m = { id: c.id, name: nm, version: ver, set: c.s, r: c.r, nName: cn, nFull: cf, nSq: cn.replace(/ /g,""), nFullSq: cf.replace(/ /g,""), nVer: cv, nVerSq: cv.replace(/ /g,""), tok: tok, tri: nmTri(cf) };
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
  // Half-scores for the JOINT name+version pass (v18). textScore takes the max
  // over lines, so a card whose NAME read on one line and whose VERSION subtitle
  // read on another never combines the two — the card is judged on its single
  // best line. That let three distinct field errors through at conf high:
  //   "PETERPAN" + "Created by the Vine"  -> Hera - Created by the Vine
  //   "JUMBO"    + "NinthWonderof theUnrverso" -> Jumbo Pop
  //   "GENE"     + "OftheLomp"            -> Gene - Niceland Resident
  // In all three the true card had BOTH halves present on separate lines while
  // the winner had one half and a shorter string (levSim/tokOverlap both favour
  // short names against a version-only line — "Hera" beats "Peter Pan" on the
  // shared subtitle of a whole set-13 cycle).
  //
  // levSim early-returns 0 once the length difference exceeds 60%, so a half only
  // scores against a line of comparable length — a long rules-text line cannot
  // manufacture a version match. That length gate is what makes this safe.
  // A half only counts when the line and the field are COMPARABLE IN LENGTH — a
  // 40-char rules line is not a garbled read of a 19-char name. levSim's own guard
  // normalises by the QUERY length, which is the wrong way round here: a long line
  // against a short field passes it (|40-19| < 40*0.6) and returns a junk ~0.2.
  // That is unfixable with a score floor, because a real garbled short read scores
  // about the same (Bullseye read as "let sride" = 0.222 vs a rules line matching
  // Jebidiah Farnsworth = 0.175) — the length ratio separates them cleanly where
  // the score cannot. Not applied to levSim globally: textScore's conf thresholds
  // are calibrated against its current behaviour.
  function lenOk(a, b){
    var la = a.length, lb = b.length;
    if(!la || !lb) return false;
    return (la < lb ? la / lb : lb / la) >= HALF_LEN_RATIO;
  }
  function nameHalf(qn, qnSq, m){
    return Math.max(lenOk(qn, m.nName) ? levSim(qn, m.nName) : 0,
                    lenOk(qnSq, m.nSq) ? levSim(qnSq, m.nSq) : 0);
  }
  function verHalf(qn, qnSq, m){
    if(!m.nVer) return 0;
    return Math.max(lenOk(qn, m.nVer) ? levSim(qn, m.nVer) : 0,
                    lenOk(qnSq, m.nVerSq) ? levSim(qnSq, m.nVerSq) : 0);
  }
  var JOINT_NAME_W = 0.55;    // name half carries slightly more than the version half
  var VER_HALF_FLOOR = 0.62;  // a version half below this is noise, not a subtitle read
  // ...and the name half needs a floor too, or a card whose VERSION happens to
  // equal a stray line rides in on that alone: a frame full of rules text
  // containing "Cookie" scored Jebidiah Farnsworth - Cookie over a legitimate
  // "TNKERBEL" read of Tinker Bell - Giant Fairy. Kept permissive because the
  // real work there is done by the length gate in lenOk() — genuine reads of a
  // short name garble hard ("BULLSEYE" -> "let sride" = 0.222) and a floor high
  // enough to block the rules-text case would take them with it.
  var NAME_HALF_FLOOR = 0.20;
  var HALF_LEN_RATIO = 0.6;   // min(len)/max(len) for a half to be considered
  var ATTRIB_PENALTY = 0.55;  // weight for a "—Character" flavour-attribution line
  // rank cards by (possibly garbled) OCR name candidates. `lines` = array of OCR
  // text strings (e.g. the tallest text lines from the name band). Scores each
  // card against the best line. Returns {top:[{id,name,version,score}], conf,
  // margin, marginChar}.
  function rankNames(lines, k){
    buildNameDB(); if(!nameDB) return { top: [], conf: "low", score: 0, margin: 0, marginChar: 0 };
    k = k || 5;
    var queries = [], li;
    for(li=0; li<lines.length; li++){
      var qn = nmCanon(lines[li]); if(qn.length < 3) continue;
      // A line that STARTS with a dash is a flavour ATTRIBUTION ("—Huey"), never a
      // card name. It reads as a near-exact match for a short character name while
      // the real title, longer and garbled, scores lower — length-normalised
      // similarity means a 4-char exact beats a 24-char 92% match. Field cost: a
      // Junior Woodchuck Guidebook playset answered "Huey - Savvy Nephew" ×4 at
      // conf high, with "IUNIORWOODCHUCKGUDEBOOK" sitting right there in line 0.
      // Penalised rather than dropped: if the attribution is the ONLY thing that
      // read, the card can still be found — just not confidently.
      queries.push({ qn: qn, qnSq: qn.replace(/ /g,""), qtok: nmTok(lines[li]), qtri: nmTri(qn),
                     w: /^\s*[-—–]\s*\S/.test(lines[li]) ? ATTRIB_PENALTY : 1 });
    }
    if(!queries.length) return { top: [], conf: "low", score: 0, margin: 0, marginChar: 0 };
    var meta = nameDB.meta, best = new Float32Array(meta.length), i, qi;
    for(i=0;i<meta.length;i++){ var s=0; for(qi=0;qi<queries.length;qi++){ var q=queries[qi]; var sc=textScore(q.qn, q.qnSq, q.qtok, q.qtri, meta[i]) * q.w; if(sc>s) s=sc; } best[i]=s; }
    // JOINT re-score, TOP-N ONLY. Computing the two halves for all ~3.2k cards
    // cost +61% on identify() (159→255ms in node, so ~0.5→0.8s on a phone) — and
    // a nameMs blowup is what starved the OCR queue in the batch-6 field flow
    // (rowMs p90 260s). The joint pass only ever RESCUES a card the base pass
    // already scored respectably, so N=80 is far more than enough: a card ranked
    // below 80 on text has no name evidence to combine. Safe to reorder within
    // this window only — boosts can never raise a card from outside it into the
    // final top-24, since every final score is >= its own base score.
    var cand = topK(best, Math.min(meta.length, 80));
    var hn = new Float32Array(queries.length), hv = new Float32Array(queries.length);
    for(var ci=0; ci<cand.length; ci++){
      var mi = cand[ci], m2 = meta[mi];
      if(!m2.nVer || m2.nVerSq.length < 5) continue;   // no version, or too short to match on
      for(qi=0;qi<queries.length;qi++){
        var q2 = queries[qi];
        hn[qi] = nameHalf(q2.qn, q2.qnSq, m2) * q2.w;
        hv[qi] = verHalf(q2.qn, q2.qnSq, m2) * q2.w;
      }
      // The two halves MUST come from DIFFERENT lines. That is the entire premise
      // ("the name read on one line, the subtitle on another"), and without it one
      // garbled line double-counts against both fields and invents a score: a lone
      // "DRSULA" scored Ursula - Deal Maker 0.558 over the correct Vanessa's 0.437,
      // and 8 of the 8 replay regressions were this same self-pairing. The version
      // half also has to be a CONVINCING read — a partial ~0.3 overlap with some
      // other card's subtitle is noise, not evidence.
      var bj = 0;
      for(qi=0;qi<queries.length;qi++){
        if(hn[qi] < NAME_HALF_FLOOR) continue;
        for(var qj=0;qj<queries.length;qj++){
          if(qj === qi || hv[qj] < VER_HALF_FLOOR) continue;
          var j = JOINT_NAME_W * hn[qi] + (1 - JOINT_NAME_W) * hv[qj];
          if(j > bj) bj = j;
        }
      }
      // Both halves are <=1 so the joint stays on textScore's [0,1] scale and the
      // calibrated conf thresholds below keep their meaning.
      if(bj > best[mi]) best[mi] = bj;
    }
    // look deep enough past k that a card with many printings (6+ Minnies) still
    // reaches the first DIFFERENT character for the margin computation.
    var order = cand.slice().sort(function(a, b){ return best[b] - best[a]; }).slice(0, Math.max(k, 24));
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

  // ---- VERSION tiebreak by BODY text (rules/flavor/subtitle) -----------------
  // A confident NAME identifies the CHARACTER, but the version subtitle rarely
  // OCRs (small font, crowded out of the tallest-boxes cut by rules text) — the
  // character's versions then tie on name score and the pick fell to COLOUR
  // (~30%). The fix uses text the reads ALREADY contain: rules + flavor lines
  // are a per-version fingerprint (e.g. "Bodyguard (This character may enter
  // play exerted…" = Rajah - Devoted Protector). Score = trigram containment of
  // the concatenated OCR lines against each version's text.json body, both
  // space-stripped (PP-OCR glues words — "chooseonewithBodyguard").
  // Calibrated on the 2026-07-17 phone batch: 7/7 verified wrong versions fixed
  // (Mickey ×2, Mulan, Rajah, Dale, Basil, Lady), 0 regressions; every
  // weak-signal case abstains. Floor s1>=0.22, margin >=0.12 vs the best
  // DIFFERENT version (same-version reprints share one body → grouped).
  var bodyTriCache = Object.create(null);
  // unpadded trigrams — nmTri's boundary-space padding inflates the query set
  // (the containment DENOMINATOR) and shaved a real decide margin (0.1205)
  // under the 0.12 threshold; the offline calibration used unpadded sets.
  function bodyTriSet(s){ var o = Object.create(null), i; for(i=0;i<=s.length-3;i++) o[s.substr(i,3)]=1; return o; }
  function bodyTri(id, b){
    var t = bodyTriCache[id];
    if(!t){ t = bodyTriSet(nmCanon(b || "").replace(/ /g, "")); bodyTriCache[id] = t; }
    return t;
  }
  var charCanonSet = null;   // canon'd character names (≥5 chars) for scene-mix filtering
  function buildCharCanonSet(){
    if(charCanonSet || !text.loaded) return charCanonSet;
    var s = Object.create(null), i;
    for(i=0;i<text.cards.length;i++){
      var cn = nmCanon(text.cards[i].n || "").replace(/ /g, "");
      if(cn.length >= 5) s[cn] = 1;
    }
    charCanonSet = Object.keys(s);
    return charCanonSet;
  }
  function rankVersionsByBody(charName, lines){
    if(!text.loaded || !lines || !lines.length) return null;
    var nName = nmNorm(charName);
    var cs = text.cards, group = [], i;
    for(i=0;i<cs.length;i++) if(nmNorm(cs[i].n || "") === nName) group.push(cs[i]);
    if(group.length < 2) return null;
    // SCENE-MIX filter (7/18 batch 4, id 225): a frame holding TWO cards mixes
    // both cards' text into the query — the foreign card's trigrams dilute the
    // containment ratio below the decide margin (Rapunzel stayed "Sunshine"
    // because the Mulan lines in frame drowned the GLEAM AND GLOW signal).
    // Drop lines that contain ANOTHER character's name; if that empties the
    // set, keep the originals (a card whose own rules mention another name —
    // "…named Pascal…" — degrades to an abstain, never to a wrong pick).
    var ownCn = nmCanon(charName).replace(/ /g, "");
    var names = buildCharCanonSet() || [];
    var use = [], j;
    for(i=0;i<lines.length;i++){
      var lc = nmCanon(lines[i]).replace(/ /g, ""), foreign = false;
      for(j=0;j<names.length;j++){
        var nm2 = names[j];
        if(nm2 === ownCn || (ownCn && (ownCn.indexOf(nm2) >= 0 || nm2.indexOf(ownCn) >= 0))) continue;
        if(lc.indexOf(nm2) >= 0){ foreign = true; break; }
      }
      if(!foreign) use.push(lines[i]);
    }
    if(!use.length) use = lines;
    var q = nmCanon(use.join(" ")).replace(/ /g, "");
    var cn = nmCanon(charName).replace(/ /g, "");
    if(cn) q = q.replace(cn, "");   // the shared name substring can't separate versions
    var Q = bodyTriSet(q), nQ = setSize(Q);
    if(nQ < 12) return null;        // only the name read → no body signal, abstain
    var byVer = Object.create(null), order = [], k;
    for(i=0;i<group.length;i++){
      var v = group[i].v || "";
      var T = bodyTri(group[i].id, group[i].b), inter = 0;
      for(k in Q) if(T[k]) inter++;
      var sc = inter / nQ;
      if(byVer[v] == null){ byVer[v] = { v: v, score: sc, ids: [group[i].id] }; order.push(byVer[v]); }
      else { byVer[v].ids.push(group[i].id); if(sc > byVer[v].score) byVer[v].score = sc; }
    }
    if(order.length < 2) return null;
    order.sort(function(a, b){ return b.score - a.score; });
    var s1 = order[0].score, s2 = order[1].score;
    if(!(s1 >= 0.22 && (s1 - s2) >= 0.12)) return null;
    return { ids: order[0].ids, version: order[0].v, score: s1, margin: s1 - s2 };
  }

  // ---- VERSION tiebreak by SUBTITLE -----------------------------------------
  // The body tiebreak needs the rules/flavor text; but the version SUBTITLE
  // itself often reads (the ×2.5 band, or a lucky tall read) — "Elegant
  // Spaniel", "Amber Champion", "Charging Ahead". rankNames doesn't lean on it
  // because the tall NAME line matches every version of the character equally
  // (both Lady prints match "LADY"), so a decided character with a tied name
  // falls to colour's shortest-name bias (v11: Lady→Family Dog with "Elegant
  // Spanie" RIGHT THERE, Mickey→Giant Mouse, Mulan→Reflecting). Score each
  // version's subtitle against the best OCR line (squashed lev + trigram Dice);
  // fire only when one subtitle clearly wins (>=0.60, margin >=0.15) so a
  // garbled/absent subtitle abstains rather than guessing.
  function rankVersionsBySubtitle(charName, lines){
    if(!text.loaded || !lines || !lines.length) return null;
    var nName = nmNorm(charName), group = [], i;
    for(i=0;i<text.cards.length;i++) if(nmNorm(text.cards[i].n || "") === nName) group.push(text.cards[i]);
    if(group.length < 2) return null;
    var lineSq = [], lineTri = [], lineSqShort = [], j;
    for(j=0;j<lines.length;j++){
      var lc = nmCanon(lines[j]); var sq = lc.replace(/ /g, "");
      if(sq.length >= 4){ lineSq.push(sq); lineTri.push(nmTri(lc)); }
      else if(sq.length >= 2) lineSqShort.push(sq);   // micro-lines ("v10") for exact digit-subtitle matches
    }
    if(!lineSq.length && !lineSqShort.length) return null;
    var byVer = Object.create(null), order = [];
    for(i=0;i<group.length;i++){
      var v = group[i].v || ""; if(!v) continue;
      var vc = nmCanon(v), vsq = vc.replace(/ /g, ""), best = 0;
      if(vsq.length < 4){
        // "V.8"/"V.10"-class micro-subtitles (canon "v8"/"v10") are too short
        // for fuzzy scoring — and the ≥4-char line filter dropped their reads
        // too, so they could NEVER win a subtitle rank (v15 field: OCR read
        // "V.10" verbatim, the ranker skipped it, name-score noise picked V.8
        // ×3). Digit-bearing micro-subtitles now match by EXACT squashed-line
        // equality only; no exact read → abstain (fuzzy 2-3 char compares
        // would false-fire constantly).
        if(!/\d/.test(vsq)) continue;
        for(j=0;j<lineSqShort.length && !best;j++) if(lineSqShort[j] === vsq) best = 1;
        if(!best) continue;
      } else {
        var vtri = nmTri(vc);
        for(j=0;j<lineSq.length;j++){ var s = 0.65 * levSim(lineSq[j], vsq) + 0.35 * diceSet(lineTri[j], vtri); if(s > best) best = s; }
      }
      if(byVer[v] == null){ byVer[v] = { v: v, score: best, ids: [group[i].id] }; order.push(byVer[v]); }
      else { byVer[v].ids.push(group[i].id); if(best > byVer[v].score) byVer[v].score = best; }
    }
    if(order.length < 2) return null;
    order.sort(function(a, b){ return b.score - a.score; });
    var s1 = order[0].score, s2 = order[1].score;
    if(!(s1 >= 0.60 && (s1 - s2) >= 0.15)) return null;
    return { ids: order[0].ids, version: order[0].v, score: s1, margin: s1 - s2 };
  }
  // combined version tiebreak: subtitle first (direct evidence), then body.
  function rankVersion(charName, lines){
    var vs = null;
    try { vs = rankVersionsBySubtitle(charName, lines); } catch(e){}
    if(vs){ vs.by = "subtitle"; return vs; }
    var vb = null;
    try { vb = rankVersionsByBody(charName, lines); } catch(e){}
    if(vb){ vb.by = "body"; return vb; }
    return null;
  }

  // ---- FLAVOR-ATTRIBUTION HIJACK RESCUE --------------------------------------
  // A card QUOTING character X in its flavor text ("—Monterey Jack") hijacks
  // the name match when the real card's NAME doesn't OCR but its rules/flavor
  // lines DO — X wins the name score while every other line belongs to the
  // quoting card. Detector: trigram containment of the full OCR text against
  // (a) X's own card bodies vs (b) the bodies of cards that MENTION X. Fire
  // only when the quoter DOMINATES — margin rule calibrated on the full
  // 315-row field corpus (2026-07-19): best>=0.35, own<=0.45, margin>=0.30,
  // >=25 query trigrams → fires on exactly the 2 image-verified hijacks
  // (Merlin->Develop Your Brain, Monterey Jack->Dale - Ready for His Shot)
  // and on ZERO verified-correct rows. A real scan OF the quoted character is
  // own-dominant (0.76 on a true Monterey Jack) and never fires. Quoters are
  // found per-character on demand (one pass over text.cards, cached) — a full
  // char->quoters index would cost seconds at load for no benefit.
  var quotersCache = Object.create(null);
  function quotersFor(charName){
    var key = nmNorm(charName);
    var hit = quotersCache[key];
    if(hit) return hit;
    var cn = nmCanon(charName).replace(/ /g, "");
    var out = [];
    if(text.loaded && cn.length >= 5){
      for(var i=0;i<text.cards.length;i++){
        var c = text.cards[i];
        if(nmNorm(c.n || "") === key) continue;
        var bc = nmCanon(c.b || "").replace(/ /g, "");
        if(bc.indexOf(cn) >= 0) out.push(c);
      }
    }
    quotersCache[key] = out;
    return out;
  }
  function rescueByQuote(charName, lines){
    if(!text.loaded || !charName || !lines || !lines.length) return null;
    var quoters = quotersFor(charName);
    if(!quoters.length) return null;
    var q = nmCanon(lines.join(" ")).replace(/ /g, "");
    var Q = bodyTriSet(q), nQ = setSize(Q);
    if(nQ < 25) return null;
    var contain = function(card){
      var T = bodyTri(card.id, card.b), inter = 0, k;
      for(k in Q) if(T[k]) inter++;
      return inter / nQ;
    };
    var key = nmNorm(charName), own = 0, i;
    for(i=0;i<text.cards.length;i++){
      var oc = text.cards[i];
      if(nmNorm(oc.n || "") !== key) continue;
      var so = contain(oc);
      if(so > own) own = so;
    }
    var best = 0, bc = null;
    for(i=0;i<quoters.length;i++){
      var sc = contain(quoters[i]);
      if(sc > best){ best = sc; bc = quoters[i]; }
    }
    if(!(bc && best >= 0.35 && own <= 0.45 && (best - own) >= 0.30)) return null;
    var ids = [], bn = nmNorm(bc.n || ""), bv = bc.v || "";
    for(i=0;i<text.cards.length;i++){
      var c2 = text.cards[i];
      if(nmNorm(c2.n || "") === bn && (c2.v || "") === bv) ids.push(c2.id);
    }
    return { ids: ids.length ? ids : [bc.id], name: bc.n || "", version: bv,
             score: Math.round(best * 1000) / 1000, margin: Math.round((best - own) * 1000) / 1000 };
  }

  // Same-(name,version) reprint HEAD GUARD (v16, reworked v18). Text is IDENTICAL
  // between a base printing and its Enchanted/Iconic/Epic/Promo reprints, so a
  // chase card at the head of the candidate list can only be there via colour rank
  // or list order — never via text evidence. Base printings outnumber chase pulls
  // heavily in real scans, so a chase head must EARN the slot: an exact collector
  // number (branch 1 returns before this) or a colour win over its OWN base sibling.
  //
  // v16 asked the wrong question. It granted the slot on a TOP-5 GLOBAL colour
  // rank, on the theory that "a real Enchanted's full-art is visually distinctive".
  // Measured over all 491 base<->chase pairs in the shipped index, that theory
  // holds for Enchanted (median cosine to its own base 0.31) and Iconic (0.16) —
  // and fails completely for Epic (0.850) and Promo (0.855), which are the SAME
  // artwork re-framed. Random card pairs sit at 0.537 median / 0.822 at p99, so an
  // Epic is closer to its base than 99% of random pairs: whichever wins is decided
  // by noise, and the free pass then rubber-stamps it. 70% of Epic and 55% of Promo
  // pairs are blind this way. Field cost (Aaron's 405-snap v16 batch): 9 of the 13
  // confirmed silent-confident errors were a base card answered as its chase twin.
  //
  // So: measure the pair. If the two reference vectors are near-twins, colour
  // cannot possibly be the evidence and the base wins outright. If they really are
  // separable, colour keeps its say (a genuine Enchanted scan still resolves).
  var CHASE_RARITY = { E: 1, I: 1, X: 1, P: 1 };  // Enchanted / Iconic / Epic / Promo
  var COLOUR_TWIN_COS = 0.80;  // above this, colour cannot separate the pair
  function reprintDemote(m){
    if(!m) return 0;
    return (CHASE_RARITY[m.r] ? 2 : 0) + (String(m.id).lastIndexOf("crd_custom_", 0) === 0 ? 1 : 0);
  }
  // cosine between two REFERENCE colour vectors (both unit-norm * a constant
  // scale, so a plain dot product / scale^2 is the cosine). Index-only, no query
  // involved — this is a property of the two printings' art, computed lazily and
  // memoised. Returns null when either id is missing from the colour index.
  var twinCosCache = Object.create(null);
  function refColourCos(idA, idB){
    if(!state.loaded || !state.color) return null;
    var key = idA < idB ? idA + "|" + idB : idB + "|" + idA;
    var hit = twinCosCache[key];
    if(hit !== undefined) return hit;
    if(!state.rowById){
      state.rowById = Object.create(null);
      for(var i=0;i<state.cards.length;i++) state.rowById[state.cards[i].id] = i;
    }
    var ra = state.rowById[idA], rb = state.rowById[idB], out = null;
    if(ra != null && rb != null){
      var dims = state.dims, col = state.color, ba = ra * dims, bb = rb * dims;
      var dot = 0, na = 0, nb = 0, d, va, vb;
      for(d=0;d<dims;d++){ va = col[ba+d]; vb = col[bb+d]; dot += va*vb; na += va*va; nb += vb*vb; }
      out = (na && nb) ? dot / Math.sqrt(na * nb) : null;
    }
    twinCosCache[key] = out;
    return out;
  }
  // Is `chaseId` distinguishable from `baseId` by colour at all?  Unknown (no
  // vectors) counts as NOT separable: absence of evidence must not read as
  // evidence for the rarer card.
  function colourCanSeparate(chaseId, baseId){
    var c = refColourCos(chaseId, baseId);
    return c != null && c < COLOUR_TWIN_COS;
  }
  function baseGuard(ids, colour){
    if(!nameDB || !ids || ids.length < 2) return ids;
    var head = nameDB.byId[ids[0]];
    if(!head || !reprintDemote(head)) return ids;
    // find the head's best base sibling (same name+version, less demoted)
    var j, sibAt = -1;
    for(j=1;j<ids.length;j++){
      var m = nameDB.byId[ids[j]];
      if(m && m.nName === head.nName && (m.version || "") === (head.version || "") && reprintDemote(m) < reprintDemote(head)){ sibAt = j; break; }
    }
    if(sibAt < 0) return ids;   // nothing better to fall back to
    // colour may only keep the chase at the head when it can actually TELL THE
    // TWO APART, and then only on a top-5 rank.
    if(colourCanSeparate(ids[0], ids[sibAt])){
      for(j=0;j<(colour||[]).length && j<5;j++) if(colour[j] === ids[0]) return ids;
    }
    var out = ids.slice(); out.splice(sibAt, 1); out.unshift(ids[sibAt]);
    return out;
  }
  // Are the top two candidates same-(name,version) printings?  Then the pick was
  // NOT made on text — the text is byte-identical between a base printing and its
  // reprint — so it rests on colour or list order, and the row must say so (amber
  // ≈ + the sibling one tap away in the alternates) instead of showing a confident
  // ✓. Unconditional on purpose: the v16 field batch had 185 labelled rows with
  // ZERO Enchanted/Iconic/Epic truths and 9 confirmed base-answered-as-its-chase
  // errors, i.e. the colour-promotion path produced no confirmed right answers and
  // several confident wrong ones. It is kept alive (a real Enchanted scan has no
  // other signal — its text is its base's text) but it no longer gets to look
  // certain. The collector number is the only true discriminator here (base #6 vs
  // Epic #206), and the idle cn finisher upgrades the row once it reads — which it
  // now does more often, the cn det having gotten 2.1x cheaper.
  function reprintUnsure(ids){
    if(!nameDB || !ids || ids.length < 2) return false;
    var a = nameDB.byId[ids[0]], b = nameDB.byId[ids[1]];
    if(!a || !b) return false;
    return a.nName === b.nName && (a.version || "") === (b.version || "");
  }

  // Reorder a candidate id list so the BODY-decided version of the top card's
  // character comes first. The body-text version tiebreak used to run ONLY in
  // the name-high branch; when a slightly mis-OCR'd name ("AJAH"/"RAJAM") fell
  // to fusion/cn, colour picked the version and its shortest-name bias won —
  // Rajah "Ghostly Tiger" over "Devoted Protector", Rapunzel "Sunshine" over
  // "Gifted with Healing" (v11 field: 5 such misses). Safe by construction: it
  // only reorders when the TOP card's OWN character has a body-matching version,
  // so a wrong-character fusion pick (garbled name → "Merlin") abstains and is
  // left untouched — never made worse.
  function bodyVersionReorder(ids, lines){
    if(!ids || !ids.length || !nameDB) return { ids: ids, vb: null };
    var m0 = nameDB.byId[ids[0]];
    if(!m0) return { ids: ids, vb: null };
    var vb = rankVersion(m0.name, lines || []);
    if(!vb || !vb.ids || !vb.ids.length) return { ids: ids, vb: null };
    return { ids: dedupeIds(vb.ids.concat(ids)), vb: vb };
  }

  // IDENTITY — PARALLEL fusion (vote, don't gate). The collector NUMBER is the
  // backbone: set+number → ~1 card (near-unique primary key). Name-OCR + colour
  // are independent voters that order the narrowed field. Falls back to
  // name-primary, then colour, when the number doesn't read.
  // opts = { lines:[ocr strings], cnNum:"116"|null, cnSet:"12"|null, colourRanked:[ids] }.
  //
  // Wrapper: flags `printUnsure` when the answer is an unresolvable same-(name,
  // version) reprint coin flip, so the row shows ≈ instead of a confident ✓.
  // Single point on purpose — every branch returns through here, so a new branch
  // can't silently ship a confident coin flip. Skipped for "cn+name": an exact
  // collector number DID resolve the printing, which is the whole point of it.
  function identify(opts){
    var r = identifyCore(opts);
    if(r && r.source !== "cn+name" && r.top3 && r.top3.length > 1 &&
       reprintUnsure(r.top3)) r.printUnsure = true;
    return r;
  }
  function identifyCore(opts){
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
    // 2. confident NAME alone → name wins (number absent or misread). But
    //    FIRST check the flavor-attribution hijack: if the body evidence
    //    overwhelmingly belongs to a card that merely QUOTES this character,
    //    the "confident" name is the quote line, not the card — return the
    //    quoter at medium conf (amber ≈, alternates kept) so the UI stays
    //    honest about the override. Never reached when the collector number
    //    corroborated the name (branch 1 returns first).
    if(nm.conf === "high" && nameIds.length){
      var rz = null;
      try { rz = rescueByQuote(nm.top[0].name, opts.lines || []); } catch(e){}
      if(rz && rz.ids.length){
        return { top3: dedupeIds(orderByColour(rz.ids).concat(orderByColour(nameIds), colour)).slice(0, 3),
                 conf: "medium", source: "rescue", verBy: null,
                 rescue: { from: nm.top[0].name, score: rz.score, margin: rz.margin },
                 nameConf: nm.conf, nameMargin: nm.marginChar, names: nm.top };
      }
      var vb = rankVersion(nm.top[0].name, opts.lines || []);
      if(vb && vb.ids.length){
        return { top3: baseGuard(dedupeIds(orderByColour(vb.ids).concat(orderByColour(nameIds), colour)), colour).slice(0, 3),
                 conf: "high", source: "name", verBy: vb.by || "body", verMargin: Math.round(vb.margin * 1000) / 1000,
                 nameConf: nm.conf, nameMargin: nm.marginChar, names: nm.top };
      }
      // colour is a PRINTING tie-breaker, not a character vote: with a
      // high-conf name, only the top character's own printings may be
      // colour-reordered. A visually-similar DIFFERENT card must not outrank
      // the read name (v15 #566: "EHURLEHISTHUNDERROL" ranked He Hurled His
      // Thunderbolt 0.477/high, but colour promoted The Thunderquack — a
      // mid-list 0.25 name candidate with lookalike lightning art).
      var n0m = nameDB.byId[nameIds[0]], sameChar = [], restIds = [], ci;
      for(ci = 0; ci < nameIds.length; ci++){
        var mc = nameDB.byId[nameIds[ci]];
        if(n0m && mc && mc.nName === n0m.nName) sameChar.push(nameIds[ci]); else restIds.push(nameIds[ci]);
      }
      return { top3: baseGuard(dedupeIds(orderByColour(sameChar).concat(restIds, colour)), colour).slice(0, 3), conf: "high", source: "name", nameConf: nm.conf, nameMargin: nm.marginChar, names: nm.top };
    }
    // 3. number read but name weak → the numbered cards, ordered by name then colour (needs a tap)
    if(numIds.length){
      var ranked = rankCnCandidates(numIds, nm.top, colour);
      var frc = bodyVersionReorder(ranked, opts.lines);
      return { top3: baseGuard(dedupeIds(frc.ids.concat(nameIds, colour)), colour).slice(0, 3), conf: numIds.length <= 2 ? "medium" : "low", source: "cn", verBy: frc.vb ? "body" : undefined, verMargin: frc.vb ? Math.round(frc.vb.margin * 1000) / 1000 : undefined, nameConf: nm.conf, nameMargin: nm.marginChar, names: nm.top };
    }
    // 4. fallback: name + colour vote. Same hijack check — the field case
    //    that motivated the rescue (Monterey Jack over Dale) landed HERE
    //    (medium fusion), not in branch 2.
    if(nm.top.length){
      var rz2 = null;
      try { rz2 = rescueByQuote(nm.top[0].name, opts.lines || []); } catch(e){}
      if(rz2 && rz2.ids.length){
        return { top3: dedupeIds(orderByColour(rz2.ids).concat(nameIds, colour)).slice(0, 3),
                 conf: "medium", source: "rescue",
                 rescue: { from: nm.top[0].name, score: rz2.score, margin: rz2.margin },
                 nameConf: nm.conf, nameMargin: nm.marginChar, names: nm.top };
      }
    }
    var fused = rrf([nameIds, colour], [3, 1]);
    var frf = bodyVersionReorder(fused, opts.lines);
    return { top3: baseGuard(dedupeIds(frf.ids), colour).slice(0, 3), conf: nm.conf === "medium" ? "medium" : "low", source: "fusion", verBy: frf.vb ? "body" : undefined, verMargin: frf.vb ? Math.round(frf.vb.margin * 1000) / 1000 : undefined, nameConf: nm.conf, nameMargin: nm.marginChar, names: nm.top };
  }

  window.CardScanner = {
    load: load,
    searchCrop: searchCrop,
    colorSig: colorSig,
    dhash64: dhash64,
    rankNames: rankNames,
    rankVersionsByBody: rankVersionsByBody,
    rankVersionsBySubtitle: rankVersionsBySubtitle,
    rescueByQuote: rescueByQuote,
    lookupCN: lookupCN,
    identify: identify,
    loadText: loadText,
    textMatch: textMatch,
    get state() { return state; },
    get textState() { return text; },
  };
})();
