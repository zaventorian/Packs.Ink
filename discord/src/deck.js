// deck.js — price a pasted decklist.
//
// Formats people actually paste: "4 Mowgli - Man Cub", "4x Mowgli", "4 × Elsa -
// Spirit of Winter (1-42)", section headers ("Characters (20)"), blank lines,
// comments. A decklist names each card in full, so an EXACT name match is
// tried first and the forgiving resolver only gets a line nobody spelled
// right — where it still has to be confident, because a deck total built on a
// guessed card is a wrong number that looks right.
import { norm } from "./text.js";

const LINE = /^\s*(\d{1,2})\s*[x×]?\s*[-–:.]?\s*(.+?)\s*$/i;
const HINT = /\s*\((?:[a-z0-9]{1,6}[- ]?\d{1,4}[a-z]?|[^)]*\bset\b[^)]*)\)\s*$/i;   // "(1-42)", "(TFC 42)", "(set 3)"

export function parseDeckList(text) {
  const out = [];
  for (const raw of String(text || "").split(/\r?\n/)) {
    const line = raw.replace(/[*_`]/g, "").trim();
    if (!line || /^(#|\/\/)/.test(line)) continue;
    const m = LINE.exec(line);
    if (!m) continue;
    const qty = Number(m[1]);
    const name = m[2].replace(HINT, "").trim();
    // "Characters (20)" / "Actions (8)" are headers, not cards
    if (!qty || qty > 99 || !name || /^(characters?|actions?|songs?|items?|locations?|total|deck|cards?)\b/i.test(name)) continue;
    out.push({ qty, name, line: raw.trim() });
  }
  return out;
}

// A message is a decklist when most of its non-empty lines are "N Name" —
// that is what lets Price check on a posted list total it instead of pricing
// three of its sixty cards.
export function looksLikeDeck(text) {
  const lines = String(text || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const hits = parseDeckList(text).length;
  return hits >= 5 && hits >= lines.length * 0.6;
}

// Cheapest printing of the card (any set, any finish) at NM Market and at Low
// — "what does it cost to build this", which is the question.
function cheapest(card) {
  let mkt = null, low = null, mktAt = null;
  for (const p of card.p) {
    for (const f of p.f) {
      if (f[6]) continue;   // no listing of its own
      if (f[5] != null && (mkt == null || f[5] < mkt)) { mkt = f[5]; mktAt = { p, f }; }
      if (f[4] != null && (low == null || f[4] < low)) low = f[4];
    }
  }
  return { mkt, low, mktAt };
}

// Built once per resolver: every card's normalized name (the exact tier) and
// its squashed name bucketed by length (the near-miss tier).
const NAME_INDEX = new WeakMap();
function nameIndex(R) {
  let ix = NAME_INDEX.get(R);
  if (ix) return ix;
  const exact = new Map(), byLen = new Map();
  R.cards.forEach((c, i) => {
    const n = norm(c.n);
    exact.set(n, i);
    const sq = n.replace(/[^a-z0-9]/g, "");
    if (!byLen.has(sq.length)) byLen.set(sq.length, []);
    byLen.get(sq.length).push([sq, i]);
  });
  ix = { exact, byLen };
  NAME_INDEX.set(R, ix);
  return ix;
}

// Call once at startup: builds the name index outside any request's CPU time.
export const prepareDeckIndex = (R) => { nameIndex(R); };

// Edit distance, giving up once it must exceed k.
function within(a, b, k) {
  if (Math.abs(a.length - b.length) > k) return k + 1;
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let best = i;
    for (let j = 1; j <= b.length; j++) {
      const v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      cur.push(v);
      if (v < best) best = v;
    }
    if (best > k) return k + 1;
    prev = cur;
  }
  return prev[b.length];
}

// A FULL name with a typo in it ("Be Prepard", "Tinker Bel - Giant Fairy") is
// one or two letters from exactly one card's full name. A name that is merely
// close to two cards is left alone.
function nearName(ix, name) {
  const sq = norm(name).replace(/[^a-z0-9]/g, "");
  if (sq.length < 6) return null;
  const k = sq.length <= 12 ? 1 : 2;
  let best = k + 1, hit = null, tie = false;
  for (let L = sq.length - k; L <= sq.length + k; L++) {
    for (const [cand, i] of ix.byLen.get(L) || []) {
      const d = within(sq, cand, k);
      if (d < best) { best = d; hit = i; tie = false; }
      else if (d === best && d <= k) tie = true;
    }
  }
  return best <= k && !tie ? hit : null;
}

// The resolver is the slow tier (~1ms a line). A real exported list names
// every card exactly, so a list needing this many guesses is not a Lorcana
// decklist, and the Worker's CPU budget is better spent saying so.
export const MAX_GUESSES = 8;

export function priceDeck(R, entries) {
  const ix = nameIndex(R);
  const rows = [], unmatched = [];
  let guesses = 0;
  for (const e of entries) {
    let i = ix.exact.get(norm(e.name));
    let guessed = false;
    if (i == null) {
      i = nearName(ix, e.name);
      guessed = i != null;
    }
    if (i == null && guesses < MAX_GUESSES) {
      guesses++;
      const r = R.resolve(e.name);
      // A clear match, or a typo with only one card it could be ("4x mogli").
      // A bare name ("4 mowgli") gets the version people play, the resolver's
      // whole point, and says so on the row.
      if (r.kind === "card" && !r.ambiguous && (r.score >= 0.9 || (r.corrected && r.score >= 0.75))) { i = r.index; guessed = true; }
    }
    if (i == null) { unmatched.push(e); continue; }
    const card = R.cards[i];
    const px = cheapest(card);
    rows.push({ ...e, i, card, guessed, ...px });
  }
  // One card on several lines (two printings listed separately) is one card.
  const merged = new Map();
  for (const r of rows) {
    const m = merged.get(r.i);
    if (m) { m.qty += r.qty; m.guessed = m.guessed || r.guessed; } else merged.set(r.i, { ...r });
  }
  const list = [...merged.values()];
  const count = list.reduce((s, r) => s + r.qty, 0) + unmatched.reduce((s, e) => s + e.qty, 0);
  const sum = (k) => list.reduce((s, r) => s + (r[k] != null ? r[k] * r.qty : 0), 0);
  const missing = (k) => list.filter((r) => r[k] == null).length;
  return {
    rows: list.sort((a, b) => (b.mkt ?? 0) * b.qty - (a.mkt ?? 0) * a.qty),
    unmatched, count,
    totalMarket: sum("mkt"), totalLow: sum("low"),
    unpricedMarket: missing("mkt"), unpricedLow: missing("low"),
  };
}
