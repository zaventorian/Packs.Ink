// stats.js — a card at a glance, for the one-line places a picker has.
//
// Zaven, on /card's suggestions: "a small sub line under each option saying
// the stats … like demona: amethyst 6c inkable 5/6 2lore and any keywords".
// The same parts feed two shapes, because Discord gives them different room:
//
//  - A select menu option has a real sub-line (its `description`, ≤100
//    characters), so it gets the words: "Amethyst · 6c · inkable · 5/6 ·
//    2 lore · Evasive".
//  - ⚠ An autocomplete suggestion has NO sub-line — Discord shows one line of
//    ≤100 characters and nothing else — so the stats go ON that line, after
//    the name, with the ink as its coloured square to save room. When the line
//    is too long the least useful parts go first (the set name, "inkable",
//    the last keywords, "uninkable", the word "Location"); the name, cost,
//    numbers, lore, rarity and price stay.

// The six inks as Discord's coloured squares.
export const INK_MARK = { Amber: "🟨", Amethyst: "🟪", Emerald: "🟩", Ruby: "🟥", Sapphire: "🟦", Steel: "⬜" };
export const inkMarks = (inks) => (inks || []).map((k) => INK_MARK[k] || "").join("");

const reEsc = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Each keyword the card has, with its number from the rules text: "Shift 6",
// "Resist +1", "Singer 5", "Evasive". In the order the card prints them.
export function keywordTags(c) {
  const lines = String((c && c.x) || "").split(/\r?\n/).map((l) => l.trim());
  const text = lines.join("\n").toLowerCase();
  return ((c && c.w) || []).map((w) => {
    const re = new RegExp("^" + reEsc(w) + "\\s+([+-]?\\d+)(?!\\w)", "i");
    const hit = lines.map((l) => re.exec(l)).find(Boolean);
    return { w, t: hit ? `${w} ${hit[1]}` : w, at: text.indexOf(w.toLowerCase()) };
  }).sort((a, b) => (a.at < 0 ? 1e9 : a.at) - (b.at < 0 ? 1e9 : b.at)).map((x) => x.t);
}

// [{k, t}] in reading order: ink, cost, inkable, the numbers, lore, keywords.
// `marks` puts the ink as its square next to the cost ("🟪 6c").
export function statParts(c, { marks = false } = {}) {
  if (!c) return [];
  const parts = [];
  const inks = (c.i || []).filter(Boolean);
  const cost = c.cost != null ? `${c.cost}c` : null;
  if (marks) {
    const t = [inkMarks(inks), cost].filter(Boolean).join(" ");
    if (t) parts.push({ k: "ink", t });
  } else {
    if (inks.length) parts.push({ k: "ink", t: inks.join("/") });
    if (cost) parts.push({ k: "cost", t: cost });
  }
  // "inkable" is true of most cards, so it is the first word to give way;
  // "uninkable" is the notable one and outlives the keywords.
  if (c.ik === 1) parts.push({ k: "inkable", t: "inkable" });
  if (c.ik === 0) parts.push({ k: "uninkable", t: "uninkable" });
  const [str, wil, lore, move] = c.st || [];
  const type = String(c.t || "");
  if (/Location/i.test(type)) {
    parts.push({ k: "type", t: "Location" });
    if (move != null) parts.push({ k: "num", t: `move ${move}` });
    if (wil != null) parts.push({ k: "num", t: `${wil} willpower`, short: `${wil} wp` });
  } else if (str != null || wil != null) {
    parts.push({ k: "num", t: `${str ?? "–"}/${wil ?? "–"}` });
  } else if (type) {
    parts.push({ k: "type", t: /Song/i.test(type) ? "Song" : type.replace(/\s*-.*$/, "") });
  }
  if (lore != null) parts.push({ k: "lore", t: `${lore} lore` });
  for (const t of keywordTags(c)) parts.push({ k: "kw", t });
  return parts;
}

// Groups of parts joined by " · ", the groups by `between`, no longer than
// `max`. In order: parts are dropped by kind in `drop` order (a kind's LAST
// part first, so the first keyword outlives the rest); parts with a `short`
// form take it; then, if `trim` names a group, that group loses its tail
// parts behind a "…", so the groups after it (a price) survive whole. Only
// then is the text cut.
export function fitParts(groups, max = 100, drop = [], between = " · ", trim = null) {
  const gs = groups.map((g) => g.filter((p) => p && p.t));
  const text = () => gs.map((g) => g.map((p) => p.t).join(" · ")).filter(Boolean).join(between);
  for (const k of drop) {
    while (text().length > max) {
      let gi = -1, pi = -1;
      gs.forEach((g, a) => g.forEach((p, b) => { if (p.k === k) { gi = a; pi = b; } }));
      if (gi < 0) break;
      gs[gi].splice(pi, 1);
    }
  }
  if (text().length > max) for (const g of gs) for (const p of g) if (p.short) p.t = p.short;
  if (trim != null && gs[trim]) {
    let cut = false;
    while (text().length > max && gs[trim].length > 1) { gs[trim].pop(); cut = true; }
    if (cut) gs[trim].push({ k: "more", t: "…" });
    while (text().length > max && gs[trim].length > 1) gs[trim].splice(gs[trim].length - 2, 1);
  }
  const s = text();
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

// A select option's sub-line: the stats in words, then whatever the menu
// already said about the option (rank, rarity, price). An extra may be
// {k: "set", t} so a set name gives way before anything else does.
export function statsLineFor(c, extra = [], max = 100) {
  const more = extra.filter((e) => e && (typeof e === "string" || e.t)).map((e) => (typeof e === "string" ? { k: "extra", t: e } : e));
  return fitParts([statParts(c), more], max, ["set", "inkable", "kw", "uninkable", "type", "extra"]);
}
