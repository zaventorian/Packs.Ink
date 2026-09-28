// trade.js — "what is this trade worth?"
//
// Two lists of cards (and sealed product, and cash) in, both sides priced and
// compared out. Two ways in: /trade (a box with a side each, or two options),
// and Price check on a message that is a trade post ("H: … / W: …") — which is
// how trades are actually written in a store's Discord.
//
// Decisions that carry the design:
//
//  1. ⚠ Each card is priced at the VERSION the words name — not at its
//     cheapest printing, which is the right question for a deck (what does it
//     cost to build) and the wrong one here: "enchanted elsa" in a trade is the
//     Enchanted, and pricing it as the $5 Legendary would call a $950 trade even.
//     With no version words it is the printing people play, the resolver's rule,
//     and every line names what it matched so a wrong guess is visible.
//  2. Prices come from the card index, which is rebuilt every day after the
//     price ETL — so the reply needs no database read and answers at once.
//  3. ⚠ The resolver is capped per trade (TRADE_MAX_LOOKUPS). It is well under
//     a millisecond a name, but a trade post can list fifty cards and the free
//     Workers plan gives a request 10 ms of CPU. Exact full names never touch it.
//  4. ⚠ Commas separate items EXCEPT between the word pairs real card names
//     hold ("Fix-It Felix, Jr.", "Wake Up, Alice!") — splitting there would turn
//     one card into two wrong guesses. "and", "&" and "for" never split: 55
//     card names contain "and" or "&", and 20 contain "for".
import { norm } from "./text.js";
import { FIN_PRINTING } from "./data.js";
import { money, pct as fmtPct, shortDate, BRAND_COLOR, openId } from "./embeds.js";

export const TRADE_MAX_ITEMS = 15;       // per side
export const TRADE_MAX_LOOKUPS = 24;     // resolver calls per trade
export const EVEN_WITHIN = 0.05;         // |difference| / bigger side

// ── reading a trade post ─────────────────────────────────────────────────
// A marker word opens a side: "H:", "Have -", "LF:", "ISO". With a ":" or a
// spaced dash it counts anywhere ("H: elsa, tipo W: mickey" is one line); a
// bare word only at the start of a line, and only the abbreviations nobody
// writes in an ordinary sentence ("LF mowgli", "ISO elsa") — "I have 2 elsa"
// is not a trade post.
const HAVE_WORDS = ["h", "have", "haves", "has", "ft", "uft", "for trade", "up for trade", "trading", "offering", "giving", "my side"];
const WANT_WORDS = ["w", "want", "wants", "lf", "looking for", "iso", "need", "needs", "seeking", "their side"];
const markerRe = (() => {
  const words = [...HAVE_WORDS, ...WANT_WORDS].sort((a, b) => b.length - a.length).map((w) => w.replace(/ /g, "\\s+")).join("|");
  return new RegExp(
    `(?:^|(?<=[\\s.;!?,(*_>~\`]))(${words})\\s*(?::|[-–—](?=\\s))` +
    `|(?:^|(?<=\\n))[\\s*_>~\`-]*(lf|iso|ft|uft)\\s+(?=\\S)`, "gi");
})();

// → { has: "text", wants: "text" } when the message reads as a trade, else null.
export function parseTradePost(text) {
  const t = String(text || "").replace(/\r\n/g, "\n");
  const marks = [];
  for (const m of t.matchAll(markerRe)) {
    const word = (m[1] || m[2]).toLowerCase().replace(/\s+/g, " ");
    const side = HAVE_WORDS.includes(word) ? "has" : "wants";
    marks.push({ side, start: m.index + m[0].length, at: m.index });
  }
  if (!marks.length) return null;
  const out = { has: [], wants: [] };
  marks.forEach((mk, i) => {
    const end = i + 1 < marks.length ? marks[i + 1].at : t.length;
    const body = t.slice(mk.start, end).trim();
    if (body) out[mk.side].push(body);
  });
  if (!out.has.length || !out.wants.length) return null;
  return { has: out.has.join("\n"), wants: out.wants.join("\n") };
}

// ── items ────────────────────────────────────────────────────────────────
// Word pairs a comma sits between INSIDE a card name, so it is not a
// separator there. Built from the index at first use, not hand-kept.
const COMMA_PAIRS = new WeakMap();
function commaPairs(R) {
  let set = COMMA_PAIRS.get(R);
  if (set) return set;
  set = new Set();
  for (const c of R.cards) {
    if (!c.n.includes(",")) continue;
    const parts = c.n.split(",");
    for (let i = 0; i + 1 < parts.length; i++) {
      const a = norm(parts[i]).split(" ").pop(), b = norm(parts[i + 1]).split(" ")[0];
      if (a && b) set.add(a + "|" + b);
    }
  }
  COMMA_PAIRS.set(R, set);
  return set;
}

export function splitItems(R, text) {
  const pairs = commaPairs(R);
  const out = [];
  for (const line of String(text || "").split(/\r?\n|;|\s\+\s|\s\|\s|\s\/\s|•/)) {
    const pieces = line.split(",");
    let cur = pieces[0];
    for (let i = 1; i < pieces.length; i++) {
      const a = norm(cur).split(" ").pop(), b = norm(pieces[i]).split(" ")[0];
      if (a && b && pairs.has(a + "|" + b)) cur += "," + pieces[i];
      else { out.push(cur); cur = pieces[i]; }
    }
    out.push(cur);
  }
  return out.map((s) => s.replace(/^[\s*_>`~•-]+|[\s*_`~.]+$/g, "").trim()).filter((s) => s && /[a-z0-9$]/i.test(s));
}

const CASH = /^(?:\+\s*)?(?:\$\s*(\d{1,6}(?:[.,]\d{1,2})?)(?:\s*(?:usd|cash|dollars?|bucks|paypal|pp|venmo))?|(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:\$|usd|cash|dollars?|bucks|in cash|paypal|pp|venmo))(?:\s+cash)?$/i;
const QTY_LEAD = /^(\d{1,2})\s*[x×*]?\s+(.+)$/i;
const QTY_LEAD_X = /^[x×](\d{1,2})\s+(.+)$/i;
const QTY_TRAIL = /^(.+?)\s*(?:[x×*]\s*(\d{1,2})|\((\d{1,2})\)|(\d{1,2})\s*[x×])$/i;

export function parseItem(s) {
  const t = String(s || "").trim();
  const cash = CASH.exec(t);
  if (cash) return { cash: Number(String(cash[1] || cash[2]).replace(",", ".")) };
  let m = QTY_LEAD.exec(t);
  if (m) return { qty: Math.min(20, Number(m[1])) || 1, name: m[2].trim(), whole: t };
  m = QTY_LEAD_X.exec(t);
  if (m) return { qty: Math.min(20, Number(m[1])) || 1, name: m[2].trim(), whole: t };
  m = QTY_TRAIL.exec(t);
  if (m) return { qty: Math.min(20, Number(m[2] || m[3] || m[4])) || 1, name: m[1].trim(), whole: t };
  return { qty: 1, name: t, whole: t };
}

// ── pricing ──────────────────────────────────────────────────────────────
const EXACT = new WeakMap();
function exactNames(R) {
  let m = EXACT.get(R);
  if (m) return m;
  m = new Map();
  R.cards.forEach((c, i) => { const k = norm(c.n); if (!m.has(k)) m.set(k, i); });
  EXACT.set(R, m);
  return m;
}

const finishPrinting = (f) => (f && f[2]) || FIN_PRINTING[f && f[0]] || "Normal";

// One side's text -> priced lines. `budget` is shared across both sides.
function priceSide(R, text, budget) {
  const exact = exactNames(R);
  const raw = splitItems(R, text);
  const lines = [], unmatched = [];
  let cash = 0, more = 0;
  for (const s of raw) {
    const it = parseItem(s);
    if (it.cash != null) { cash += it.cash; continue; }
    if (lines.length >= TRADE_MAX_ITEMS) { more++; continue; }
    // "99 Puppies" is a card, not 99 of "Puppies": a whole line that is an
    // exact card name wins over reading its first number as a count.
    let i = exact.get(norm(it.whole));
    let qty = it.qty;
    if (i != null) qty = 1;
    else i = exact.get(norm(it.name));
    if (i != null) {
      const { printing, fi } = R.pickPrinting(i);
      lines.push(cardLine(R, i, printing, fi, qty, false));
      continue;
    }
    if (budget.left <= 0) { unmatched.push({ text: s, why: "limit" }); continue; }
    budget.left--;
    const r = R.resolve(it.name);
    if (r.kind === "card") {
      lines.push(cardLine(R, r.index, r.printing, r.fi, qty, r.corrected || r.score < 0.9, r.notes));
    } else if (r.kind === "sealed") {
      const x = r.item;
      lines.push({ kind: "sealed", qty, name: x.n, label: x.n, item: x, key: R.sealedKey(x), low: x.low, mkt: x.mkt, guessed: false });
    } else {
      unmatched.push({ text: s, why: "none" });
    }
  }
  const sum = (k) => lines.reduce((t, l) => t + (l[k] != null ? l[k] * l.qty : 0), 0) + cash;
  return { lines, unmatched, cash, more, totalLow: sum("low"), totalMkt: sum("mkt"), unpriced: lines.filter((l) => l.mkt == null && l.low == null).length };
}

// What a trade line calls a version: the rarity when it IS the version
// (Enchanted, Epic, Iconic, Promo), the finish when it's a foil, the variant
// label (Text Error, Top Prize…) when there is one.
function versionTag(R, p, fi) {
  const bits = [];
  if (p.var) bits.push(p.var);
  if (["Enchanted", "Epic", "Iconic", "Promo"].includes(p.r)) bits.push(p.r);
  const fin = R.finishLabel(p, fi);
  if (fin && fin !== p.var && fin !== "Non-foil" && !["Enchanted", "Epic", "Iconic"].includes(p.r)) bits.push(fin);
  return bits.join(", ");
}

function cardLine(R, i, p, fi, qty, guessed, notes) {
  const c = R.cards[i];
  const f = p.f[fi] || p.f[0] || [];
  const listed = !f[6];
  const tag = versionTag(R, p, fi);
  return {
    kind: "card", qty, name: c.n, label: c.n + (tag ? ` (${tag})` : ""),
    i, printing: p, fi, key: R.cardKey(p, fi), pid: listed ? f[1] : null, tcgPrinting: finishPrinting(f),
    low: listed ? f[4] ?? null : null, mkt: listed ? f[5] ?? null : null,
    guessed: !!guessed, notes: notes || [],
  };
}

export function priceTrade(R, giveText, getText) {
  const budget = { left: TRADE_MAX_LOOKUPS };
  const give = priceSide(R, giveText, budget);
  const get = priceSide(R, getText, budget);
  return { give, get, ...verdict(give.totalMkt, get.totalMkt), low: verdict(give.totalLow, get.totalLow) };
}

// Positive `diff` means the GET side is worth more.
export function verdict(giveTotal, getTotal) {
  const diff = getTotal - giveTotal;
  const big = Math.max(giveTotal, getTotal);
  const pct = big > 0 ? diff / big : 0;
  return { diff, pct, even: Math.abs(pct) <= EVEN_WITHIN || Math.abs(diff) < 0.5 };
}

// ── the site's Trade Compare, prefilled ──────────────────────────────────
// The site still reads its original inline form, ?trade=<base64url JSON>
// {a:[[key, nonFoilQty, foilQty]], b:[…], n:[nameA, nameB]}, so a checked
// trade opens there with no database write. `key` is the site's
// tradeGroupKey: the card_id, plus the printing for the Challenge Promo (C1)
// cards whose foil and non-foil share one card_id and are two tiles.
export function tradeSiteUrl(R, trade, names) {
  const side = (s) => {
    const byKey = new Map();
    for (const l of s.lines) {
      if (l.kind !== "card") continue;
      const p = l.printing, f = p.f[l.fi] || p.f[0] || ["N"];
      const split = !!(R.sets[p.s] || {}).sp;
      const key = p.id + (split ? "::" + (f[0] === "N" ? "Normal" : finishPrinting(f)) : "");
      const e = byKey.get(key) || [key, 0, 0];
      if (f[0] === "N") e[1] += l.qty; else e[2] += l.qty;
      byKey.set(key, e);
    }
    return [...byKey.values()];
  };
  const a = side(trade.give), b = side(trade.get);
  if (!a.length && !b.length) return null;
  const json = JSON.stringify({ a, b, n: names });
  const b64 = btoa(String.fromCharCode(...new TextEncoder().encode(json)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return "https://packs.ink/?trade=" + b64;
}

// ── the reply ────────────────────────────────────────────────────────────
// Two columns (Discord puts inline fields side by side on a desktop and
// stacks them on a phone), a verdict in words, and a menu that opens any card
// from the trade in a private reply. `mode` "you" is /trade (you give / you
// get); "post" is Price check on someone's trade post (has / wants), which is
// judged from the poster's side.
const GREEN = 0x5cc480, RED = 0xe86868;
const clip = (s, n) => { s = String(s || ""); return s.length <= n ? s : s.slice(0, n - 1) + "…"; };

function sideField(label, s) {
  const out = [];
  for (const l of s.lines) {
    const each = l.mkt != null ? money(l.mkt) : null;
    const price = each == null ? "*no price*" : l.qty > 1 ? `${each} ea` : each;
    out.push(`${l.qty > 1 ? `**${l.qty}×** ` : ""}${l.label} · ${price}${l.guessed ? " *(guess)*" : ""}`);
  }
  if (s.cash) out.push(`+ ${money(s.cash)} cash`);
  if (s.more) out.push(`*…and ${s.more} more, not counted*`);
  if (!out.length) out.push("*nothing I recognised*");
  let value = "";
  for (let k = 0; k < out.length; k++) {
    const next = (value ? value + "\n" : "") + out[k];
    if (next.length > 990) { value += `\n*…and ${out.length - k} more*`; break; }
    value = next;
  }
  return { name: clip(`${label} · ${money(s.totalMkt) || "$0.00"}`, 256), value, inline: true };
}

export function tradeMessage(t, { mode = "you", priceDate, siteUrl } = {}) {
  const labels = mode === "post" ? ["Has", "Wants"] : ["You give", "You get"];
  const [giveL, getL] = labels;
  // How far apart, as a share of the bigger side: "8% apart" is the number
  // that says whether a trade is close; past that the dollars say it better.
  const apart = `${fmtPct(Math.abs(t.pct) * 100).replace(/^[▲▼]/, "")} apart`;
  let head;
  if (t.even) head = `⚖️ **About even** — within ${Math.round(EVEN_WITHIN * 100)}% at NM Market.`;
  else if (mode === "post") {
    head = t.diff > 0
      ? `The **wants** are worth **${money(t.diff)} more** than the haves (${apart}, NM Market).`
      : `The **haves** are worth **${money(-t.diff)} more** than the wants (${apart}, NM Market).`;
  } else {
    head = t.diff > 0
      ? `✅ **You come out ${money(t.diff)} ahead** (${apart}, NM Market).`
      : `⚠️ **You give ${money(-t.diff)} more than you get** (${apart}, NM Market).`;
  }
  const lowLine = `At Low: ${giveL.toLowerCase()} ${money(t.give.totalLow) || "$0.00"} · ${getL.toLowerCase()} ${money(t.get.totalLow) || "$0.00"}`;
  const notes = [];
  const unpriced = t.give.unpriced + t.get.unpriced;
  if (unpriced) notes.push(`${unpriced} card${unpriced === 1 ? " has" : "s have"} no TCGplayer price of ${unpriced === 1 ? "its" : "their"} own and count${unpriced === 1 ? "s" : ""} as $0 — check ${unpriced === 1 ? "it" : "them"} before you agree.`);
  if (t.give.lines.some((l) => l.guessed) || t.get.lines.some((l) => l.guessed)) notes.push("*(guess)* means I matched a name loosely — make sure it's the card you meant.");
  const miss = [...t.give.unmatched, ...t.get.unmatched];
  if (miss.length) {
    const names = miss.slice(0, 6).map((u) => `“${clip(u.text, 40)}”`).join(", ");
    notes.push(`Couldn't find ${names}${miss.length > 6 ? ` and ${miss.length - 6} more` : ""} — not counted.`);
  }
  const description = [head, `*${lowLine}*`, ...(notes.length ? ["", ...notes] : [])];
  if (siteUrl && siteUrl.length > 512 && siteUrl.length <= 1800) description.push("", `[Open this trade on packs.ink](${siteUrl})`);
  const color = t.even || mode === "post" ? BRAND_COLOR : t.diff > 0 ? GREEN : RED;
  const embed = {
    title: mode === "post" ? "Trade check" : "Your trade",
    color,
    description: clip(description.join("\n"), 4000),
    fields: [sideField(giveL, t.give), sideField(getL, t.get)],
    footer: { text: `NM Market from TCGplayer${priceDate ? ", as of " + shortDate(priceDate) : ""} · each card at the version shown · packs.ink` },
  };
  const components = [];
  const seen = new Set(), options = [];
  for (const [label, s] of [[giveL, t.give], [getL, t.get]]) {
    for (const l of s.lines) {
      if (seen.has(l.key) || options.length >= 25) continue;
      seen.add(l.key);
      options.push({ label: clip(l.label, 100), value: l.key, description: clip(`${label} · ${l.mkt != null ? money(l.mkt) : "no price"}`, 100) });
    }
  }
  if (options.length) components.push({ type: 1, components: [{ type: 3, custom_id: openId("card"), placeholder: "Look at a card from this trade", options }] });
  if (siteUrl && siteUrl.length <= 512) components.push({ type: 1, components: [{ type: 2, style: 5, label: "Open in Trade Compare", url: siteUrl }] });
  return { embeds: [embed], components };
}

// /trade's box: a side each, prefilled with whatever the options held.
export const TRADE_MODAL_ID = (priv) => `trade|${priv ? "p" : "-"}`;
export function tradeModal(priv, give = "", get = "") {
  const input = (id, label, value, placeholder) => ({ type: 1, components: [{
    type: 4, custom_id: id, style: 2, label, required: true, min_length: 2, max_length: 1500,
    placeholder, ...(value ? { value: String(value).slice(0, 1500) } : {}),
  }] });
  return {
    custom_id: TRADE_MODAL_ID(priv), title: "Check a trade",
    components: [
      input("give", "What you give", give, "2x Mowgli\nenchanted elsa\n$20"),
      input("get", "What you get", get, "stitch rock star foil\nazurite sea box"),
    ],
  };
}
