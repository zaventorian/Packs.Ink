// resolver.js — plain English in, one card (or sealed product) out.
//
// "mowgli", "mogli", "how much is the enchanted elsa", "stitch foil",
// "elsa psa 10", "azurite sea box", "peter pan text error", "blt mickey".
// The job is not to FILTER a catalog (the site's matchesCardFilter does that,
// and a filter's contract is exactness) but to decide which ONE card a person
// meant, forgive the spelling, and say so when it had to guess.
//
// Decisions that carry the design:
//
//  1. ⚠ "The main one" is MEASURED. When a name alone matches several versions
//     ("mowgli", "elsa", "mickey"), the tie is broken by how often each version
//     appears in tournament top-cut decks (`pl`, from build_index.mjs,
//     recency-weighted). When the query shows COLLECTOR intent instead — a
//     chase rarity or a grade — it is broken by graded sale volume (`gs`),
//     because "elsa enchanted" means the famous one, not the playable one.
//  2. ⚠ The popularity prior is SMALL (≤0.12) against the text score (0..~1.2),
//     so it only ever decides between versions the words cannot tell apart. A
//     query that names the version wins on the words, never on popularity.
//  3. ⚠ A word can be a dimension AND a name word ("enchanted" is a rarity and
//     part of "Mrs. Potts - Enchanted Teapot"; "box" is sealed product and part
//     of "Hand-in-the-Box"). Those are resolved BOTH ways and the better
//     reading wins — never by a fixed rule, which would make one of the two
//     cards unfindable by its own name.
//  4. Each query word counts toward ONE part of a card's name (its best match),
//     so a fuzzy near-miss on the version can't add a bonus on top of an exact
//     hit on the character.
import { norm, tokens, dl, FILLER, STOP } from "./text.js";
import { statParts, fitParts } from "./stats.js";

export const RARITIES = ["Common", "Uncommon", "Rare", "Super Rare", "Legendary", "Enchanted", "Epic", "Iconic", "Promo"];
const CHASE = new Set(["Enchanted", "Epic", "Iconic"]);
const BASE_RARITY = new Set(["Common", "Uncommon", "Rare", "Super Rare", "Legendary"]);
const INKS = ["Amber", "Amethyst", "Emerald", "Ruby", "Sapphire", "Steel"];

const RARITY_WORDS = {
  common: "Common", commons: "Common",
  uncommon: "Uncommon", uncommons: "Uncommon",
  rare: "Rare", rares: "Rare",
  "super rare": "Super Rare", superrare: "Super Rare", sr: "Super Rare",
  legendary: "Legendary", legend: "Legendary", legendaries: "Legendary",
  enchanted: "Enchanted", ench: "Enchanted",
  epic: "Epic", epics: "Epic",
  iconic: "Iconic", iconics: "Iconic",
  promo: "Promo", promos: "Promo",
};
// A misspelt rarity is caught by edit distance against these — long enough
// that a slip cannot land on some other ordinary word.
const RARITY_FUZZ = ["enchanted", "legendary", "uncommon", "iconic"];

const FINISH_WORDS = {
  foil: "foil", foils: "foil", "cold foil": "foil", holo: "foil", holofoil: "foil", rainbow: "foil", shiny: "foil",
  "top prize": "foil",
  "non foil": "nonfoil", nonfoil: "nonfoil", nf: "nonfoil", normal: "nonfoil", regular: "nonfoil",
  "not foil": "nonfoil", "no foil": "nonfoil", "prize wall": "nonfoil",
};

const GRADERS = { psa: "PSA", cgc: "CGC", bgs: "BGS", beckett: "BGS", tag: "TAG", sgc: "SGC", ace: "ACE" };

// Sealed words -> the site's display type (deriveSealedDisplayType).
const SEALED_WORDS = [
  ["booster box case", "Cases"], ["box case", "Cases"], ["case", "Cases"], ["cases", "Cases"],
  ["booster box", "Booster Boxes"], ["box", "Booster Boxes"], ["boxes", "Booster Boxes"], ["display", "Booster Boxes"],
  ["sleeved booster pack", "Sleeved Booster Packs"], ["sleeved pack", "Sleeved Booster Packs"],
  ["booster pack", "Booster Packs"], ["booster", "Booster Packs"], ["pack", "Booster Packs"], ["packs", "Booster Packs"],
  ["illumineers trove", "Illumineer's Troves"], ["illumineer trove", "Illumineer's Troves"], ["trove", "Illumineer's Troves"], ["troves", "Illumineer's Troves"],
  ["starter deck", "Starter Decks"], ["starter decks", "Starter Decks"], ["starter", "Starter Decks"],
  ["gift set", "Gift Sets"], ["gift box", "Gift Sets"], ["gift", "Gift Sets"],
  ["collectors edition", "Collector's Edition"], ["collector edition", "Collector's Edition"],
  ["prerelease pack", "Prerelease Packs"], ["prerelease kit", "Prerelease Packs"],
  ["bundle", "Bundles"], ["quest", "Quests"], ["puzzle", "Puzzles"],
];

const RANGE_WORDS = {
  "1 month": "1m", "one month": "1m", "30 days": "1m", "1m": "1m", "last month": "1m",
  "3 months": "3m", "three months": "3m", "90 days": "3m", "3m": "3m",
  "6 months": "6m", "six months": "6m", "6m": "6m", "half year": "6m",
  "1 year": "1y", "one year": "1y", "12 months": "1y", "1y": "1y", "last year": "1y", "past year": "1y",
  "all time": "all", alltime: "all", "since release": "all",
};

const NEW_WORDS = ["new", "newest", "latest", "recent", "upcoming"];

// Words in a variant label that do not identify it: "Two Swords Variant" is
// named by "two swords", "Japanese Exclusive" by "japanese".
const GENERIC_VAR = new Set(["variant", "version", "exclusive", "edition", "serial", "numbered"]);
const varWords = (label) => tokens(label).filter((t) => !STOP.has(t) && !GENERIC_VAR.has(t));

// A name word matched in each part of a card's name. "A" = the version's
// initials ("sow" for Spirit of Winter, "blt" for Brave Little Tailor), which
// only ever match exactly.
const FIELD_W = { C: 1, J: 1, V: 0.92, A: 0.9, X: 0.36 };

// Which of a-z (lo) and 0-9 (hi) a token contains. One edit changes that set
// by at most two symbols (a substitution drops one and adds one; a
// transposition changes nothing), so two tokens whose sets differ by more
// than 2k symbols cannot be within k edits — a test that costs two XORs,
// where the edit distance it saves costs a table. It only ever skips words
// dl() would have rejected, so no answer changes.
export function letterMask(t) {
  let lo = 0, hi = 0;
  for (let i = 0; i < t.length; i++) {
    const c = t.charCodeAt(i);
    if (c >= 97 && c <= 122) lo |= 1 << (c - 97);
    else if (c >= 48 && c <= 57) hi |= 1 << (c - 48);
  }
  return [lo, hi];
}
export function popcount(x) {
  x -= (x >>> 1) & 0x55555555;
  x = (x & 0x33333333) + ((x >>> 2) & 0x33333333);
  return (((x + (x >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
}

export function createResolver(index) {
  const sets = index.sets || [];
  const cards = index.cards || [];
  const sealed = index.sealed || [];
  const N = Math.max(1, cards.length);

  // ── vocabulary ─────────────────────────────────────────────────────────
  // Built once per isolate, so it is written for speed: postings are deduped
  // per card with a Set (a scan of every posting for "mickey" was quadratic),
  // and document frequency is counted as the postings arrive.
  const vocab = new Map();                // token -> [{i, f}]
  const df = new Map();                   // token -> cards whose NAME has it
  const nameVocab = new Set();            // tokens that occur in some card name
  const meta = new Array(cards.length);
  for (let i = 0; i < cards.length; i++) {
    const c = cards[i];
    const seen = new Set();
    const counted = new Set();
    const add = (tok, f) => {
      if (!tok) return;
      const k = f + tok;
      if (seen.has(k)) return;
      seen.add(k);
      let arr = vocab.get(tok);
      if (!arr) { arr = []; vocab.set(tok, arr); }
      arr.push({ i, f });
      if (f !== "X") {
        if (!counted.has(tok)) { counted.add(tok); df.set(tok, (df.get(tok) || 0) + 1); }
        if (f !== "A") nameVocab.add(tok);
      }
    };
    const ct = tokens(c.c);
    const vt = tokens(c.v);
    for (const t of ct) add(t, "C");
    if (ct.length > 1) add(ct.join(""), "J");
    for (const t of vt) add(t, "V");
    if (vt.length > 1) add(vt.join(""), "V");
    const sigV = vt.filter((t) => !STOP.has(t));
    // Initials, with and without the little words: Spirit of Winter -> "sow"
    // and "sw"; Brave Little Tailor -> "blt". Three letters minimum, or two
    // letters of initials collide with every short word in English.
    for (const src of [vt, sigV]) {
      if (src.length >= 2) { const ini = src.map((t) => t[0]).join(""); if (ini.length >= 3) add(ini, "A"); }
    }
    // Variant labels ("Text Error", "Two Swords") are how people name those
    // printings, so they rank with the version words.
    const rar = new Set(), setsOf = new Set(), nums = new Set();
    for (const p of c.p || []) {
      rar.add(p.r); setsOf.add(p.s); nums.add(numKey(p.no));
      if (p.var) for (const t of tokens(p.var)) add(t, "V");
    }
    for (const k of c.k || []) for (const t of tokens(k)) add(t, "X");
    for (const k of c.w || []) for (const t of tokens(k)) add(t, "X");
    for (const t of tokens(c.t)) add(t, "X");
    const charSig = ct.filter((t) => !STOP.has(t));
    meta[i] = {
      ct, vt, charSig: charSig.length ? charSig : ct, verSig: sigV,
      nameN: norm(c.n), charN: norm(c.c), rar, sets: setsOf, inks: new Set(c.i || []), nums,
    };
  }
  const idf = (tok) => Math.log(1 + N / (df.get(tok) || 1));

  // Fast candidate lookup: tokens sorted for prefix ranges, bucketed by length
  // for edit distance. Initials are exact-only, so they stay out of both.
  const fuzzToks = [];
  for (const [t, posts] of vocab) if (posts.some((p) => p.f !== "A")) fuzzToks.push(t);
  const sorted = fuzzToks.sort();
  const byLen = new Map();
  for (const t of sorted) {
    let b = byLen.get(t.length);
    if (!b) { b = { toks: [], lo: [], hi: [] }; byLen.set(t.length, b); }
    const [lo, hi] = letterMask(t);
    b.toks.push(t); b.lo.push(lo); b.hi.push(hi);
  }
  const lowerBound = (s) => { let lo = 0, hi = sorted.length; while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] < s) lo = m + 1; else hi = m; } return lo; };

  // Popularity never changes after startup, so the priors are computed once
  // here rather than for every candidate of every query.
  const maxPl = Math.max(1, ...cards.map((c) => c.pl || 0));
  const maxGs = Math.max(1, ...cards.map((c) => c.gs || 0));
  const playP = cards.map((c) => Math.log1p(c.pl || 0) / Math.log1p(maxPl));
  const collP = cards.map((c) => Math.log1p(c.gs || 0) / Math.log1p(maxGs));

  // Every version of a character, most-played first — what "the other
  // versions" menu lists. Sorted once (stable, so ties keep index order);
  // leaving one card out of a stably sorted list keeps everyone else's order.
  const byChar = new Map();
  meta.forEach((m, i) => { let g = byChar.get(m.charN); if (!g) { g = []; byChar.set(m.charN, g); } g.push(i); });
  for (const g of byChar.values()) g.sort((a, b) => (cards[b].pl || 0) - (cards[a].pl || 0) || (cards[b].gs || 0) - (cards[a].gs || 0));

  // ── dimension phrase table ────────────────────────────────────────────
  // phrase (normalised) -> {type, value, soft}. A single word that is also a
  // word of some card's name is SOFT: parse() hands back both readings.
  const phrases = new Map();
  const put = (p, type, value) => {
    const n = norm(p);
    if (!n || phrases.has(n)) return;
    const soft = !n.includes(" ") && nameVocab.has(n);
    phrases.set(n, { type, value, soft });
  };
  for (const [w, r] of Object.entries(RARITY_WORDS)) put(w, "rarity", r);
  for (const [w, f] of Object.entries(FINISH_WORDS)) put(w, "finish", f);
  for (const [w, t] of SEALED_WORDS) put(w, "sealed", t);
  for (const [w, r] of Object.entries(RANGE_WORDS)) put(w, "range", r);
  for (const ink of INKS) put(ink, "ink", ink);
  sets.forEach((s, si) => {
    put(s.n, "set", si);
    for (const a of s.alias || []) put(a, "set", si);
  });
  for (const w of NEW_WORDS) put(w, "new", true);
  const maxPhrase = Math.max(1, ...[...phrases.keys()].map((p) => p.split(" ").length));

  const newestMainIdx = (() => {
    let best = -1, bestMain = 0;
    sets.forEach((s, i) => {
      if (s.main > bestMain && sealed.some((p) => p.s === i)) { best = i; bestMain = s.main; }
    });
    return best;
  })();

  // ── parse ─────────────────────────────────────────────────────────────
  function blankDims() {
    return { rarity: null, finish: null, set: null, ink: null, sealed: null, range: null, number: null, grade: null, graded: false, newest: false };
  }
  function applyPhrase(dims, ph) {
    if (ph.type === "rarity") dims.rarity = ph.value;
    else if (ph.type === "finish") dims.finish = ph.value;
    else if (ph.type === "set") dims.set = ph.value;
    else if (ph.type === "ink") dims.ink = ph.value;
    else if (ph.type === "sealed") dims.sealed = ph.value;
    else if (ph.type === "range") dims.range = ph.value;
    else if (ph.type === "new") dims.newest = true;
  }
  // Returns two readings: A consumes every dimension word; B keeps the soft
  // ones (words that are also card-name words) as name words.
  function parse(raw) {
    const base = blankDims();
    let s = String(raw || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
    // Grades first, on the lightly-normalised text: "9.5" has to survive.
    s = s.replace(/\b(psa|cgc|bgs|beckett|tag|sgc|ace)\s*-?\s*(10|[1-9](?:\.5)?)\b/g, (_, g, n) => {
      base.grade = { grader: GRADERS[g], grade: n };
      return " ";
    });
    s = s.replace(/\b(psa|cgc|bgs|beckett|sgc)\b/g, (_, g) => {
      if (!base.grade) base.grade = { grader: GRADERS[g], grade: null };
      return " ";
    });
    if (/\bblack\s*label\b/.test(s)) { base.grade = { grader: "BGS", grade: "10" }; s = s.replace(/\bblack\s*label\b/g, " "); }
    if (/\bgem\s*mint\b/.test(s)) { if (!base.grade) base.grade = { grader: "PSA", grade: "10" }; s = s.replace(/\bgem\s*mint\b/g, " "); }
    if (/\b(graded|slab|slabs|slabbed)\b/.test(s)) { base.graded = true; s = s.replace(/\b(graded|slab|slabs|slabbed)\b/g, " "); }
    if (base.grade) base.graded = true;
    // Collector numbers: "#42", "42/204", "no. 42", "#215 error".
    s = s.replace(/(?:#|\bno\.?\s*)(\d{1,3}[a-z]?)\b|\b(\d{1,3}[a-z]?)\s*\/\s*(?:\d{1,3}|[a-z]{1,3}\d?)\b/g, (_, a, b) => {
      base.number = String(a || b).toLowerCase();
      return " ";
    });
    const toks = tokens(s);
    const A = { dims: { ...base }, name: [] };
    const B = { dims: { ...base }, name: [] };
    let soft = false;
    for (let i = 0; i < toks.length;) {
      let hit = null, len = 0;
      for (let L = Math.min(maxPhrase, toks.length - i); L >= 1; L--) {
        const ph = phrases.get(toks.slice(i, i + L).join(" "));
        if (ph) { hit = ph; len = L; break; }
      }
      if (!hit) {
        const t = toks[i];
        const fz = t.length >= 6 && !nameVocab.has(t) ? RARITY_FUZZ.find((w) => dl(t, w, 2) <= (w.length >= 8 ? 2 : 1)) : null;
        if (fz) { A.dims.rarity = B.dims.rarity = RARITY_WORDS[fz]; i++; continue; }
        A.name.push(t); B.name.push(t); i++; continue;
      }
      const span = toks.slice(i, i + len);
      applyPhrase(A.dims, hit);
      if (hit.soft) { soft = true; B.name.push(...span); }
      else applyPhrase(B.dims, hit);
      i += len;
    }
    return { A, B: soft ? B : null };
  }

  // ── name matching ─────────────────────────────────────────────────────
  function expand(t, partialLast, cache) {
    const key = t + (partialLast ? "|p" : "");
    if (cache && cache.has(key)) return cache.get(key);
    const out = new Map();
    const put2 = (tok, q) => { if ((out.get(tok) || 0) < q) out.set(tok, q); };
    if (vocab.has(t)) put2(t, 1);
    // Prefix: while typing ("mow"), or a clipped word ("tink").
    if ((partialLast && t.length >= 2) || t.length >= 4) {
      for (let k = lowerBound(t); k < sorted.length && sorted[k].startsWith(t); k++) {
        if (sorted[k] !== t) put2(sorted[k], 0.72 + 0.2 * (t.length / sorted[k].length));
      }
    }
    // Typos: 1 edit from 4 letters, 2 from 6.
    const maxD = t.length >= 6 ? 2 : t.length >= 4 ? 1 : 0;
    if (maxD) {
      const [tlo, thi] = letterMask(t);
      const lim = 2 * maxD;
      for (let L = t.length - maxD; L <= t.length + maxD; L++) {
        const b = byLen.get(L);
        if (!b) continue;
        const { toks, lo, hi } = b;
        for (let k = 0; k < toks.length; k++) {
          if (popcount(lo[k] ^ tlo) + popcount(hi[k] ^ thi) > lim) continue;
          const v = toks[k];
          const d = dl(t, v, maxD);
          if (d >= 1 && d <= maxD) put2(v, d === 1 ? 0.8 : t.length >= 8 ? 0.6 : 0.55);
        }
      }
    }
    // Still typing AND already mistyped: "mogl" against "mowgli". Same first
    // letter only — a typo almost never changes the first letter, and without
    // this bound it is a scan of the whole vocabulary per keystroke.
    if (partialLast && t.length >= 3) {
      for (let k = lowerBound(t[0]); k < sorted.length && sorted[k][0] === t[0]; k++) {
        const v = sorted[k];
        if (v.length > t.length && !out.has(v) && dl(t, v.slice(0, t.length), 1) === 1) put2(v, 0.64);
      }
    }
    if (cache) cache.set(key, out);
    return out;
  }

  // Adjacent words that were really one: "hei hei" -> "heihei".
  function joinPairs(name) {
    const out = [];
    for (let i = 0; i < name.length; i++) {
      const a = name[i], b = name[i + 1];
      if (b && vocab.has(a + b) && !(vocab.has(a) && vocab.has(b))) { out.push(a + b); i++; continue; }
      out.push(a);
    }
    return out;
  }

  function scoreName(name, { partial = false, cache } = {}) {
    const words = joinPairs(name);
    if (!words.length) return [];
    const exps = words.map((t, wi) => expand(t, partial && wi === words.length - 1, cache));
    // A word weighs what the card word it most likely MEANS weighs: "mogli" is
    // as specific as "mowgli", and "the" is nearly free.
    const W = words.map((t, wi) => {
      if (STOP.has(t)) return 0.12;
      let best = null, bq = 0;
      for (const [tok, q] of exps[wi]) if (q > bq) { bq = q; best = tok; }
      return best ? Math.min(3, idf(best)) : 1.2;
    });
    const total = W.reduce((a, b) => a + b, 0) || 1;
    const acc = new Map();   // i -> per-word best {s, tok, f, q}
    words.forEach((t, wi) => {
      for (const [tok, q] of exps[wi]) {
        for (const post of vocab.get(tok) || []) {
          const s = q * FIELD_W[post.f];
          let a = acc.get(post.i);
          if (!a) { a = new Array(words.length).fill(null); acc.set(post.i, a); }
          const cur = a[wi];
          if (!cur || s > cur.s) a[wi] = { s, tok, f: post.f, q };
        }
      }
    });
    const joined = words.join(" ");
    const res = [];
    for (const [i, a] of acc) {
      const m = meta[i];
      let got = 0;
      const charHit = new Set(), verHit = new Set();
      let fuzzy = false, looseShort = false;
      a.forEach((b, wi) => {
        if (!b) return;
        got += W[wi] * b.s;
        // A short word matched loosely ("good" for Food, "deck" for Duck) is
        // how ordinary chat turns into a card; findInText refuses those.
        if (b.q < 1) { fuzzy = true; if (words[wi].length < 6) looseShort = true; }
        if (b.f === "C") charHit.add(b.tok);
        else if (b.f === "J") for (const ct of m.ct) charHit.add(ct);
        else if (b.f === "V" || b.f === "A") {
          if (b.f === "A") for (const vt of m.verSig) verHit.add(vt);
          else if (b.tok.length > 3 && !m.vt.includes(b.tok)) for (const vt of m.verSig) { if (b.tok.includes(vt)) verHit.add(vt); }
          else verHit.add(b.tok);
        }
      });
      const coverage = got / total;
      const charCov = m.charSig.filter((t) => charHit.has(t)).length / m.charSig.length;
      const verCov = m.verSig.length ? m.verSig.filter((t) => verHit.has(t)).length / m.verSig.length : 0;
      let score = coverage * (0.72 + 0.28 * charCov) + 0.1 * verCov;
      if (m.nameN === joined) score += 0.08;
      res.push({ i, score, coverage, charCov, verCov, fuzzy, looseShort });
    }
    return res;
  }

  // ── identity + printing choice ────────────────────────────────────────
  function numKey(no) { return String(no || "").split("/")[0].toLowerCase().replace(/error$/, ""); }
  const printingOk = (p, dims) =>
    (dims.rarity == null || p.r === dims.rarity) &&
    (dims.set == null || p.s === dims.set) &&
    (dims.number == null || numKey(p.no) === dims.number);

  const isCollector = (dims) => !!(dims.rarity && CHASE.has(dims.rarity)) || !!dims.graded;

  function pickPrinting(c, dims, notes, words = []) {
    let ps = c.p;
    const narrow = (pred, what) => {
      const f = ps.filter(pred);
      if (f.length) ps = f; else if (what) notes.push(what);
    };
    if (dims.number != null) narrow((p) => numKey(p.no) === dims.number, `No #${dims.number} printing of ${c.n}.`);
    if (dims.set != null) narrow((p) => p.s === dims.set, `${c.n} isn't in ${sets[dims.set]?.n}.`);
    if (dims.rarity) narrow((p) => p.r === dims.rarity, `No ${dims.rarity} version of ${c.n}.`);
    // A variant named in the query ("text error", "two swords") picks it.
    const wordSet = new Set(words);
    const varHit = (p) => { if (!p.var) return false; const w = varWords(p.var); return w.length > 0 && w.every((t) => wordSet.has(t)); };
    const collector = isCollector(dims);
    const rank = (p) => {
      let r = 0;
      const set = sets[p.s] || {};
      if (varHit(p)) r += 20;
      else if (p.var) r -= 3;
      if (set.main) r += 4;
      if (!collector && BASE_RARITY.has(p.r)) r += 2;
      if (collector) r += Math.log1p(p.g || 0);
      if (p.f.some((f) => f[4] != null || f[5] != null)) r += 1.5;
      return r;
    };
    // On a tie the ORIGINAL printing wins: sets are ordered oldest mainline
    // first, and the original carries the longer history and the slab market.
    const best = [...ps].sort((a, b) => rank(b) - rank(a) || a.s - b.s)[0];
    let fi = 0;
    if (dims.finish) {
      const want = dims.finish === "foil" ? (f) => f[0] !== "N" : (f) => f[0] === "N";
      const k = best.f.findIndex(want);
      if (k >= 0) fi = k;
      else notes.push(dims.finish === "foil" ? "No foil printing of this one." : "This one only comes in foil.");
    }
    return { printing: best, fi };
  }

  function rankAll(name, dims, opts = {}) {
    const scored = scoreName(name, opts);
    const collector = isCollector(dims);
    for (const r of scored) {
      r.prior = collector ? 0.03 * playP[r.i] + 0.1 * collP[r.i] : 0.12 * playP[r.i] + 0.03 * collP[r.i];
      r.rank = r.score + r.prior;
    }
    return scored;
  }
  function rankCards(name, dims, opts = {}) {
    return rankAll(name, dims, opts).sort((a, b) => b.rank - a.rank);
  }
  // rankCards(...)[0] without sorting every candidate: the FIRST of the
  // highest rank, which is what a stable sort puts first.
  function topCard(name, dims, opts = {}) {
    let best = null;
    for (const r of rankAll(name, dims, opts)) if (!best || r.rank > best.rank) best = r;
    return best;
  }

  function applyDims(list, dims, notes) {
    let out = list, failed = 0;
    const tryFilter = (pred, note) => {
      const f = out.filter(pred);
      if (f.length) out = f; else { failed++; if (note) notes.push(note); }
    };
    // No notes here: when a filter matches nothing, pickPrinting says so about
    // the card actually shown, which is the sentence worth reading.
    if (dims.number != null) tryFilter((r) => meta[r.i].nums.has(dims.number));
    if (dims.set != null) tryFilter((r) => meta[r.i].sets.has(dims.set));
    if (dims.rarity) tryFilter((r) => meta[r.i].rar.has(dims.rarity));
    if (dims.ink) tryFilter((r) => meta[r.i].inks.has(dims.ink), `No ${dims.ink} card by that name.`);
    return { list: out, failed };
  }

  // ── sealed ────────────────────────────────────────────────────────────
  const sealedMeta = sealed.map((p) => ({ toks: new Set([...tokens(p.n), ...tokens(p.ty), ...tokens(p.sn)]) }));
  const TYPE_PREF = ["Booster Boxes", "Illumineer's Troves", "Booster Packs", "Gift Sets", "Starter Decks", "Collector's Edition"];
  function rankSealed(name, dims) {
    let pool = sealed.map((p, k) => ({ p, k }));
    if (dims.sealed) {
      const t = pool.filter((x) => x.p.ty === dims.sealed);
      if (t.length) pool = t;
    }
    const setIdx = dims.set != null ? dims.set : (dims.newest ? newestMainIdx : null);
    if (setIdx != null) {
      const t = pool.filter((x) => x.p.s === setIdx);
      if (t.length) pool = t;
    }
    const words = name.filter((t) => !STOP.has(t) && !FILLER.has(t));
    const scored = pool.map((x) => {
      let hit = 0;
      for (const w of words) {
        if (sealedMeta[x.k].toks.has(w)) { hit++; continue; }
        for (const tok of sealedMeta[x.k].toks) if (tok.length >= 4 && (tok.startsWith(w) || (w.length >= 4 && dl(w, tok, 1) <= 1))) { hit += 0.8; break; }
      }
      const cov = words.length ? hit / words.length : 1;
      const set = sets[x.p.s];
      const recency = set && set.main ? set.main / 20 : 0;
      const tr = TYPE_PREF.indexOf(x.p.ty);
      return { ...x, cov, rank: cov + 0.05 * recency + (tr >= 0 ? (TYPE_PREF.length - tr) * 0.004 : 0) };
    });
    scored.sort((a, b) => b.rank - a.rank);
    return scored;
  }

  // ── public: resolve ───────────────────────────────────────────────────
  function evaluate(reading, cache) {
    const { dims, name } = reading;
    const notes = [];
    const filtered = name.filter((t) => !FILLER.has(t));
    const hasName = filtered.length > 0;
    let card = null;
    if (hasName) {
      const A = rankCards(filtered, dims, { cache });
      const B = filtered.length !== name.length ? rankCards(name, dims, { cache }) : [];
      let ranked = (B.length && B[0].score > (A[0]?.score || 0) + 0.05) ? B : A;
      const top = ranked[0]?.score || 0;
      ranked = ranked.filter((r) => r.score >= Math.max(0.3, top * 0.55));
      const ad = applyDims(ranked, dims, notes);
      if (ad.list.length) {
        const best = ad.list[0];
        card = { kind: "card", r: best, ranked: ad.list, notes, dims, words: filtered, q: best.score - 0.25 * ad.failed };
      }
    } else if (dims.number != null) {
      const cand = cards.map((c, i) => ({ i, score: 0.9, coverage: 1, charCov: 1, verCov: 0 })).filter((r) => meta[r.i].nums.has(dims.number));
      const ad = applyDims(cand, dims, notes);
      if (ad.list.length === 1) card = { kind: "card", r: ad.list[0], ranked: ad.list, notes, dims, words: [], q: 0.9 - 0.25 * ad.failed };
    }
    let sealedHit = null;
    const explicit = !!dims.sealed;
    if (explicit || (!hasName && (dims.set != null || dims.newest))) {
      const sr = rankSealed(filtered, dims);
      const top = sr[0];
      if (top && top.cov >= 0.5) {
        sealedHit = { kind: "sealed", top, sr, notes: [], dims, q: (explicit ? 0.5 : 0.45) + 0.55 * top.cov };
      }
    }
    if (sealedHit && (!card || sealedHit.q > card.q)) return sealedHit;
    return card;
  }

  function resolve(raw) {
    const q = String(raw || "").trim();
    const direct = resolveKey(q);
    if (direct) return direct;
    const { A, B } = parse(q);
    const cache = new Map();
    const a = evaluate(A, cache);
    let b = B ? evaluate(B, cache) : null;
    // "enchanted" or "foil" on its own is a filter with nothing to filter. The
    // name reading ("Mrs. Potts - Enchanted Teapot") only wins it if it is a
    // genuinely good match, not a one-word brush against a longer name.
    const aWords = A.name.filter((t) => !FILLER.has(t) && !STOP.has(t));
    if (b && !a && !aWords.length && b.kind === "card" && b.r.score < 0.9) b = null;
    const pick = (b && (!a || b.q > a.q + 0.02)) ? b : a;
    const onlyStop = [...A.name, ...(B ? B.name : [])].every((t) => STOP.has(t) || FILLER.has(t));
    if (!pick || (pick.kind === "card" && (pick.r.score < 0.45 || (onlyStop && pick.r.score < 1.05)))) {
      const dimsOnly = !aWords.length && (A.dims.rarity || A.dims.finish || A.dims.grade || A.dims.ink || A.dims.number != null);
      return { kind: "none", dims: (pick || A).dims, notes: [], query: q, dimsOnly: !!dimsOnly, suggestions: suggest(q, 5) };
    }
    if (pick.kind === "sealed") {
      const { top, sr } = pick;
      return { kind: "sealed", item: top.p, index: top.k, dims: pick.dims, notes: pick.notes,
        alts: sr.slice(1).filter((x) => x.cov >= Math.min(0.5, top.cov)).slice(0, 24).map((x) => x.k) };
    }
    const best = pick.r;
    const c = cards[best.i];
    const notes = pick.notes;
    const { printing, fi } = pickPrinting(c, pick.dims, notes, pick.words);
    for (let k = notes.length - 1; k >= 0; k--) if (notes.indexOf(notes[k]) !== k) notes.splice(k, 1);
    // Other versions of the same character first (by popularity), then other
    // close matches; the card's own other printings are offered separately.
    const charN = meta[best.i].charN;
    const sameChar = pick.ranked.filter((r) => r.i !== best.i && meta[r.i].charN === charN);
    const others = pick.ranked.filter((r) => r.i !== best.i && meta[r.i].charN !== charN && r.score >= best.score * 0.8);
    const ambiguous = sameChar.length > 0 && best.verCov === 0 && sameChar.some((r) => Math.abs(r.score - best.score) < 0.05);
    return {
      kind: "card", card: c, index: best.i, printing, fi, dims: pick.dims, notes,
      score: best.score, corrected: !!best.fuzzy, ambiguous,
      basis: isCollector(pick.dims) ? "collector" : "play",
      alts: [...sameChar, ...others].slice(0, 24).map((r) => r.i),
    };
  }

  // A value handed back by autocomplete or a component: "c|<card_id>|<fin>" or
  // "s|<pid>". Exact, no guessing. A pasted packs.ink card link works too.
  // "|" rather than ":" because card ids carry colons ("extras:647652",
  // "<base>::variant::text-error").
  const byCardId = new Map();
  cards.forEach((c, i) => c.p.forEach((p) => byCardId.set(p.id, { i, p })));
  const sealedByPid = new Map(sealed.map((p, k) => [String(p.pid), k]));
  function sameCharAlts(i) {
    return (byChar.get(meta[i].charN) || []).filter((j) => j !== i).slice(0, 24);
  }
  const cardKey = (p, fi) => "c|" + p.id + "|" + ((p.f[fi] || p.f[0] || ["N"])[0]);
  const sealedKey = (it) => "s|" + it.pid;
  function resolveKey(q) {
    let m = q.match(/^c\|([^|\s]+)(?:\|([NCHF]))?$/);
    if (m && byCardId.has(m[1])) {
      const { i, p } = byCardId.get(m[1]);
      const fi = m[2] ? Math.max(0, p.f.findIndex((f) => f[0] === m[2])) : 0;
      return { kind: "card", card: cards[i], index: i, printing: p, fi, dims: {}, notes: [], score: 1, exact: true, alts: sameCharAlts(i), basis: "play" };
    }
    m = q.match(/^s\|(\d+)$/);
    if (m && sealedByPid.has(m[1])) {
      const k = sealedByPid.get(m[1]);
      const it = sealed[k];
      const alts = sealed.map((x, j) => j).filter((j) => j !== k && sealed[j].s === it.s).slice(0, 24);
      return { kind: "sealed", item: it, index: k, dims: {}, notes: [], exact: true, alts };
    }
    m = q.match(/[?&]card=(crd_[0-9a-f]{32})/i);
    if (m && byCardId.has(m[1])) return resolveKey("c|" + m[1]);
    return null;
  }

  // ── public: suggest (autocomplete) ────────────────────────────────────
  function suggest(raw, limit = 25) {
    const q = String(raw || "").trim();
    const out = [];
    const seen = new Set();
    const pushCard = (i, p, fi) => {
      const f = p.f[fi] || p.f[0];
      const key = cardKey(p, fi);
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ kind: "card", i, p, fi, value: key, label: suggestLabel(cards[i], p, fi), plain: cardLabel(cards[i], p, fi) });
    };
    const pushSealed = (x, front) => {
      const key = sealedKey(x.p);
      if (seen.has(key)) return;
      seen.add(key);
      const item = { kind: "sealed", k: x.k, value: key, label: sealedLabel(x.p) };
      if (front) out.unshift(item); else out.push(item);
    };
    if (!q) {
      // Nothing typed yet: the most-played cards right now.
      const top = cards.map((c, i) => ({ c, i })).filter((x) => x.c.pl > 0).sort((a, b) => b.c.pl - a.c.pl).slice(0, limit);
      for (const { c, i } of top) { const { printing, fi } = pickPrinting(c, {}, []); pushCard(i, printing, fi); }
      return out.slice(0, limit);
    }
    const partial = /[a-z0-9]$/i.test(q);
    const { A, B } = parse(q);
    const cache = new Map();
    const readings = B ? [A, B] : [A];
    const pool = [];
    for (const rd of readings) {
      const filtered = rd.name.filter((t) => !FILLER.has(t));
      if (!filtered.length) continue;
      let ranked = rankCards(filtered, rd.dims, { partial, cache });
      const top = ranked[0]?.score || 0;
      ranked = ranked.filter((r) => r.score >= Math.max(0.28, top * 0.5));
      ranked = applyDims(ranked, rd.dims, []).list;
      pool.push({ rd, ranked, top });
    }
    pool.sort((a, b) => b.top - a.top);
    for (const { rd, ranked } of pool) {
      const dims = rd.dims;
      const specific = dims.rarity || dims.set != null || dims.number != null || dims.finish;
      for (const r of ranked) {
        if (out.length >= limit) break;
        const c = cards[r.i];
        if (specific) {
          for (const p of c.p) {
            if (!printingOk(p, dims)) continue;
            const fi = dims.finish ? p.f.findIndex(dims.finish === "foil" ? (f) => f[0] !== "N" : (f) => f[0] === "N") : 0;
            pushCard(r.i, p, fi >= 0 ? fi : 0);
            if (out.length >= limit) break;
          }
        } else {
          const { printing, fi } = pickPrinting(c, dims, [], rd.name);
          pushCard(r.i, printing, fi);
        }
      }
    }
    // Sealed rows where the words point there.
    for (const rd of readings) {
      const filtered = rd.name.filter((t) => !FILLER.has(t));
      const explicit = !!rd.dims.sealed;
      if (!(explicit || (!filtered.length && (rd.dims.set != null || rd.dims.newest)) || out.length < 5)) continue;
      const sr = rankSealed(filtered, rd.dims).filter((x) => x.cov >= (explicit || !filtered.length ? 0.5 : 0.99));
      for (const x of sr.slice(0, explicit ? limit : 5).reverse()) pushSealed(x, explicit);
    }
    return out.slice(0, limit);
  }

  // ── public: find cards named in a chat message ────────────────────────
  // "anyone know what mowgli goes for?" / "trading my enchanted elsa for your
  // stitch". Windows of the message are scored against the index; a window must
  // be a clean, complete name match to count, because false positives here are
  // ordinary English words that happen to be card-name words.
  function findInText(raw, max = 3) {
    const direct = resolveKey(String(raw || "").trim());
    if (direct) return [direct];
    const { A } = parse(raw);
    const toks = A.name;
    const cache = new Map();
    // What each word can contribute to ANY card's coverage: its weight when
    // it can match cleanly, 0 when it can't. A word with no match at all
    // adds nothing to any card; a short word that only matches loosely makes
    // whichever card it matches "looseShort", which is rejected below — so a
    // winning card must leave it out. Summed over a window, that is a ceiling
    // on the coverage any card can reach, and a window whose ceiling is under
    // the 0.9 a clean match needs is skipped before it is scored. Ordinary
    // chat is mostly such windows. Same weights scoreName uses.
    const wordCache = new Map();
    const wordInfo = (t) => {
      let w = wordCache.get(t);
      if (w) return w;
      const exps = expand(t, false, cache);
      let best = null, bq = 0, exact = false;
      for (const [tok, q] of exps) { if (q > bq) { bq = q; best = tok; } if (q >= 1) exact = true; }
      const weight = STOP.has(t) ? 0.12 : best ? Math.min(3, idf(best)) : 1.2;
      const usable = exps.size > 0 && (exact || t.length >= 6);
      w = { weight, usable };
      wordCache.set(t, w);
      return w;
    };
    const couldBeClean = (words) => {
      let total = 0, possible = 0;
      for (const t of joinPairs(words)) {
        const w = wordInfo(t);
        total += w.weight;
        if (w.usable) possible += w.weight;
      }
      return total > 0 && possible / total >= 0.9 - 1e-9;
    };
    const hits = [];
    for (let len = Math.min(6, toks.length); len >= 1; len--) {
      for (let s = 0; s + len <= toks.length; s++) {
        const win = toks.slice(s, s + len);
        const words = win.filter((t) => !FILLER.has(t));
        if (!words.length || words.every((t) => STOP.has(t))) continue;
        if (STOP.has(words[0]) && len > 1) continue;   // let the shorter window own it
        if (!couldBeClean(words)) continue;
        const top = topCard(words, A.dims, { cache });
        if (!top) continue;
        const m = meta[top.i];
        const strong = top.coverage >= 0.9 && (top.charCov >= 0.99 || top.verCov >= 0.99);
        const sig = words.filter((t) => !STOP.has(t));
        const oneWord = sig.length === 1;
        // A lone word has to be a character's whole name and not a word so
        // common in card names that it is probably just English.
        const common = oneWord && (df.get(sig[0]) || 0) > 45;
        if (!strong || top.looseShort || (oneWord && (m.charSig.length !== 1 || common || top.fuzzy))) continue;
        hits.push({ s, e: s + len, r: top, score: top.score + len * 0.03 });
      }
    }
    hits.sort((a, b) => b.score - a.score);
    const taken = [];
    for (const h of hits) {
      if (taken.some((t) => !(h.e <= t.s || h.s >= t.e))) continue;
      if (taken.some((t) => t.r.i === h.r.i)) continue;
      taken.push(h);
      if (taken.length >= max) break;
    }
    taken.sort((a, b) => a.s - b.s);
    // No clean name in the message. A SHORT message is probably just a name
    // typed loosely ("moglie?"), so the forgiving resolver gets a turn; a long
    // one is a sentence, and fuzzy-matching a whole sentence finds some card
    // in almost anything — a price check naming a card nobody mentioned.
    if (!taken.length) {
      const words = toks.filter((t) => !FILLER.has(t) && !STOP.has(t));
      if (words.length > 4) return [];
      const r = resolve(raw);
      if (r.kind === "sealed") return [r];
      if (r.kind !== "card") return [];
      // And the whole character name has to be IN the message, typos allowed:
      // "moglie?" is Mowgli, "pulled 2 enchanteds" is not The Islands I Pulled
      // From the Sea.
      const said = (ct) => toks.some((t) => t === ct || (t[0] === ct[0] && dl(t, ct, ct.length >= 6 ? 2 : 1) <= (ct.length >= 6 ? 2 : 1)));
      const sig = meta[r.index].charSig;
      return sig.every(said) || (sig.length > 1 && said(sig.join(""))) ? [r] : [];   // "tinkerbel" is Tinker Bell
    }
    return taken.map((h) => {
      const notes = [];
      const c = cards[h.r.i];
      const { printing, fi } = pickPrinting(c, A.dims, notes, toks.slice(h.s, h.e));
      return { kind: "card", card: c, index: h.r.i, printing, fi, dims: A.dims, notes, score: h.r.score,
        corrected: !!h.r.fuzzy, alts: sameCharAlts(h.r.i), basis: isCollector(A.dims) ? "collector" : "play" };
    });
  }

  // ── sets ──────────────────────────────────────────────────────────────
  // "/set hyperia", "set 5", "azurite", "rotf", "ursulas return": the set's
  // index, or -1. The names and nicknames are the same phrase table the card
  // lookup filters with, so a set is called the same thing in both places.
  function setScore(q, p) {
    if (p === q) return 2;
    if (p.startsWith(q)) return 1 + q.length / p.length / 10;
    if (q.length >= 4 && p.includes(q)) return 0.7 + q.length / p.length / 10;
    const d = dl(q, p, q.length >= 8 ? 2 : 1);
    return d <= (q.length >= 8 ? 2 : 1) && q.length >= 4 ? 0.8 - d * 0.1 : 0;
  }
  function resolveSet(raw) {
    const q = norm(String(raw || "").replace(/^set\s+(?=\D)/i, ""));
    if (!q) return -1;
    let best = -1, bestScore = 0;
    for (const [p, ph] of phrases) {
      if (ph.type !== "set") continue;
      const s = setScore(q, p);
      if (s > bestScore) { bestScore = s; best = ph.value; }
    }
    return best;
  }
  // Autocomplete for a set option: booster sets newest first when nothing is
  // typed, otherwise the best matches.
  function suggestSets(raw, limit = 25) {
    const q = norm(raw);
    const order = sets.map((s, i) => i).sort((a, b) => (sets[b].main || 0) - (sets[a].main || 0) || a - b);
    if (!q) return order.slice(0, limit);
    const scored = new Map();
    for (const [p, ph] of phrases) {
      if (ph.type !== "set") continue;
      const s = setScore(q, p);
      if (s > 0 && s > (scored.get(ph.value) || 0)) scored.set(ph.value, s);
    }
    return [...scored.entries()].sort((a, b) => b[1] - a[1] || (sets[b[0]].main || 0) - (sets[a[0]].main || 0)).map((e) => e[0]).slice(0, limit);
  }

  // ── labels ────────────────────────────────────────────────────────────
  const money = (v) => (v == null ? null : v >= 1000 ? "$" + Math.round(v).toLocaleString("en-US") : "$" + Number(v).toFixed(2));
  function finishLabel(p, fi) {
    const f = p.f[fi];
    if (!f) return null;
    if (f[3]) return f[3];                      // Foil / Top Prize / Prize Wall / Text Error…
    if (p.f.length > 1) return f[0] === "N" ? "Non-foil" : "Foil";
    return null;
  }
  function cardLabel(c, p, fi) {
    const set = sets[p.s] || {};
    const fl = finishLabel(p, fi);
    const bits = [set.n, p.r, p.var, fl && fl !== p.var ? fl : null].filter(Boolean).join(" · ");
    const f = p.f[fi] || [];
    const px = money(f[5] ?? f[4]);
    let label = c.n + (bits ? " — " + bits : "") + (px ? " · " + px : "");
    if (label.length > 100) label = label.slice(0, 99) + "…";
    return label;
  }
  // What a /card suggestion says: the name, then the card's stats (Discord's
  // autocomplete has no sub-line, so they share the line), then which
  // printing. Too long for Discord's 100, the set name goes first, then
  // "inkable", the last keywords, "uninkable" and the word "Location" (stats.js);
  // the finish and the price stay, because two suggestions for one card are
  // told apart by them.
  function suggestLabel(c, p, fi) {
    const set = sets[p.s] || {};
    const fl = finishLabel(p, fi);
    const f = p.f[fi] || [];
    const printing = [{ k: "rar", t: p.r }, { k: "var", t: p.var }, { k: "fin", t: fl && fl !== p.var ? fl : null },
      { k: "set", t: set.n }, { k: "px", t: money(f[5] ?? f[4]) }];
    const room = 100 - c.n.length - 3;
    if (room < 12) return cardLabel(c, p, fi);
    return c.n + " — " + fitParts([statParts(c, { marks: true }), printing], room, ["set", "inkable", "kw", "uninkable", "type"], " | ", 0);
  }
  function sealedLabel(p) {
    const px = money(p.mkt ?? p.low);
    let label = p.n + (px ? " · " + px : "");
    if (label.length > 100) label = label.slice(0, 99) + "…";
    return label;
  }

  return {
    resolve, suggest, findInText, parse, cardLabel, suggestLabel, sealedLabel, finishLabel, sameCharAlts, resolveSet, suggestSets,
    pickPrinting: (i, dims = {}, words = []) => pickPrinting(cards[i], dims, [], words),
    cardKey, sealedKey, cards, sets, sealed, byCardId, sealedByPid, newestMainIdx, meta,
  };
}
