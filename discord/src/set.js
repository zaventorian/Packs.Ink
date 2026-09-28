// set.js — /set (a set at a glance) and /open (a simulated pack or box).
//
// Both answer from the card index alone: the build runs the site's own EV
// maths each day (build_index.mjs), and a pack is the site's own simPack with
// the site's own pull rates (site.generated.js). So "Box EV" here is the number
// Analytics » Expected Value shows, and a simulated Enchanted turns up exactly
// as often as it does in the site's simulator.
import { simPack, getPull, tcgUrl, INKS } from "./site.generated.js";
import { money, shortDate, BRAND_COLOR, cardImage, buyUrl, AFFILIATE_NOTE, openId, inkMarks } from "./embeds.js";
import { FIN_PRINTING } from "./data.js";

const DAY = 86400000;
const clip = (s, n) => { s = String(s || ""); return s.length <= n ? s : s.slice(0, n - 1) + "…"; };
const unixOf = (ymd) => Math.floor(Date.parse(String(ymd) + "T12:00:00Z") / 1000);
export const setPageUrl = (name) => `https://packs.ink/cards?set=${encodeURIComponent(name)}`;
const CHASE = new Set(["Enchanted", "Epic", "Iconic"]);
const todayYmd = (now = Date.now()) => new Date(now).toISOString().slice(0, 10);

// The printing a line shows, its best finish and that finish's price.
function priced(R, p) {
  let best = null;
  p.f.forEach((f, fi) => {
    if (f[6]) return;
    const v = f[5] ?? f[4];
    if (v != null && (!best || v > best.v)) best = { f, fi, v };
  });
  return best;
}

// ── /set ─────────────────────────────────────────────────────────────────
export function setOverview(R, index, si, { now = Date.now() } = {}) {
  const set = R.sets[si];
  const printings = [];
  for (let i = 0; i < R.cards.length; i++) for (const p of R.cards[i].p) if (p.s === si) printings.push({ i, p });
  const weekAgo = todayYmd(now - 7 * DAY);
  const added = printings.filter((x) => x.p.ins && x.p.ins >= weekAgo).length;
  const chase = [];
  for (const x of printings) {
    const b = priced(R, x.p);
    if (b) chase.push({ ...x, ...b });
  }
  chase.sort((a, b) => b.v - a.v);
  const sealed = (index.sealed || []).filter((s) => s.s === si && (s.mkt != null || s.low != null));
  const cheapest = (ty, k) => sealed.filter((s) => s.ty === ty && s[k] != null).sort((a, b) => a[k] - b[k])[0] || null;
  const box = cheapest("Booster Boxes", "mkt") || cheapest("Booster Boxes", "low");
  const rel = set.rel || {};
  const out = rel.lgs && rel.lgs > todayYmd(now);
  return { R, priceDate: index.priceDate, set, si, count: printings.length, added, chase: chase.slice(0, 8), sealed, box, rel,
    upcoming: !!out, boxLow: (cheapest("Booster Boxes", "low") || {}).low ?? null };
}

const TYPE_ORDER = ["Booster Boxes", "Illumineer's Troves", "Booster Packs", "Sleeved Booster Packs", "Starter Decks", "Gift Sets", "Collector's Edition", "Bundles", "Quests", "Prerelease Packs", "Cases"];
const TYPE_ONE = { "Booster Boxes": "Booster box", "Illumineer's Troves": "Trove", "Booster Packs": "Pack", "Sleeved Booster Packs": "Sleeved pack",
  "Starter Decks": "Starter deck", "Gift Sets": "Gift set", "Collector's Edition": "Collector's edition", "Bundles": "Bundle", "Quests": "Quest",
  "Prerelease Packs": "Prerelease kit", "Cases": "Case" };

// Two embeds: the set at a glance (dates, box price against box EV, the
// verdict, the logo), then its chase cards. ⚠ The chase list is a
// DESCRIPTION, not a field: every name is an affiliate link of ~220
// characters, and a field's 1,024 would clip the list mid-link — which
// Discord then shows as raw markdown.
const linkLines = (lines, budget) => {
  const out = [];
  let used = 0;
  for (const l of lines) {
    if (used + l.length + 1 > budget) break;
    out.push(l);
    used += l.length + 1;
  }
  return out;
};

export function setMessage(o, { origin } = {}) {
  const { set, box, R } = o;
  const title = set.main ? `${set.n} · Set ${set.main}` : set.n;
  const lines = [];
  const r = o.rel;
  if (r.lgs) {
    const lgs = unixOf(r.lgs), retail = r.retail ? unixOf(r.retail) : null;
    lines.push(o.upcoming
      ? `**In stores <t:${lgs}:D>** (<t:${lgs}:R>)${retail ? ` · wide retail <t:${retail}:D>` : ""}`
      : `Released <t:${lgs}:D>${retail ? ` · wide retail <t:${retail}:D>` : ""}`);
  } else if (set.date) lines.push(`Released ${shortDate(set.date)}`);
  // For a set not out yet the count is what has been REVEALED, and "this
  // week" is only worth saying while reveals are still arriving.
  if (o.upcoming) {
    lines.push(`**${o.count} cards revealed so far**` + (o.added && o.added < o.count ? ` · ${o.added} in the last week` : ""));
    lines.push("*Not out yet: these are pre-sale prices, which usually run well above where a card settles.*");
  } else {
    lines.push(`${o.count} cards`);
  }

  const fields = [];
  const ev = set.ev;
  if (box) {
    fields.push({ name: "Booster box", inline: true, value: [
      box.mkt != null ? `**${money(box.mkt)}** Market` : null,
      o.boxLow != null && o.boxLow !== box.mkt ? `${money(o.boxLow)} Low` : null,
    ].filter(Boolean).join("\n") || "no price" });
  }
  if (ev && !o.upcoming) {
    fields.push({ name: "Box EV", inline: true, value: [
      ev.mkt != null ? `**${money(ev.mkt)}** at NM Market` : null,
      ev.low != null ? `${money(ev.low)} at Low` : null,
    ].filter(Boolean).join("\n") });
    if (box && box.mkt && ev.mkt) {
      const ratio = ev.mkt / box.mkt;
      fields.push({ name: "Open or hold?", inline: true, value:
        `The cards in a box are worth about **${Math.round(ratio * 100)}%** of its price` +
        (ratio >= 1 ? " — more than the box." : ".") });
    }
  }
  const sealedLines = [];
  for (const ty of TYPE_ORDER) {
    const s = o.sealed.filter((x) => x.ty === ty).sort((a, b) => (a.mkt ?? a.low) - (b.mkt ?? b.low))[0];
    if (s) sealedLines.push(`[${TYPE_ONE[ty] || ty}](${tcgUrl(s.pid, "Normal")}) ${money(s.mkt ?? s.low)}`);
  }
  if (sealedLines.length) fields.push({ name: "Sealed", value: linkLines(sealedLines, 1000).join(" · ") });

  const overview = {
    title: clip(title, 256), url: setPageUrl(set.n), color: BRAND_COLOR,
    description: lines.join("\n"), fields,
  };
  if (set.logo) overview.image = { url: set.logo };
  if (box && box.img) overview.thumbnail = { url: box.img };
  const embeds = [overview];

  if (o.chase.length) {
    const cl = o.chase.map((x, k) => {
      const c = R.cards[x.i];
      const fin = x.f[0] !== "N" && !CHASE.has(x.p.r) && x.p.r !== "Promo" ? " foil" : "";
      return `\`${k + 1}\` [${clip(c.n, 48)}](${buyUrl(c.n, x.f[1], x.f[2] || FIN_PRINTING[x.f[0]])}) · ${x.p.r}${fin} · **${money(x.v)}**`;
    });
    const top = o.chase[0];
    const chase = {
      title: o.upcoming ? "Most expensive so far" : "Chase cards", color: BRAND_COLOR,
      description: linkLines(cl, 3900).join("\n"),
      footer: { text: `TCGplayer prices as of ${shortDate(o.priceDate || "")} · box EV as Analytics » Expected Value computes it · ${AFFILIATE_NOTE}` },
    };
    const img = top ? cardImage(top.p, origin) : null;
    if (img) chase.thumbnail = { url: img };
    embeds.push(chase);
  } else {
    overview.footer = { text: `TCGplayer prices as of ${shortDate(o.priceDate || "")} · ${AFFILIATE_NOTE}` };
  }

  const components = [];
  if (o.chase.length) {
    components.push({ type: 1, components: [{ type: 3, custom_id: openId("card"), placeholder: "Look at a chase card",
      options: o.chase.map((x) => ({ label: clip(R.cards[x.i].n, 100), value: R.cardKey(x.p, x.fi),
        description: clip(`${x.p.r} · ${money(x.v)}`, 100) })) }] });
  }
  const row = [];
  if (set.main && !o.upcoming) {
    row.push({ type: 2, style: 1, label: "Open a pack", custom_id: packId(o.si, 1) });
    row.push({ type: 2, style: 2, label: "Open a box", custom_id: packId(o.si, 24) });
  }
  if (box) row.push({ type: 2, style: 5, label: "Buy a box", url: tcgUrl(box.pid, "Normal") });
  row.push({ type: 2, style: 5, label: "All the cards", url: setPageUrl(set.n) });
  components.push({ type: 1, components: row });
  return { embeds, components };
}

// ── /new ─────────────────────────────────────────────────────────────────
// The site's reveal reel, as a message: every card that first reached the
// catalog in the last 96 hours (reprints and Extras excluded — the build ran
// the site's own revealRotation), newest first. A card that has aged out of
// the window since the build is dropped here, so a late index never presents
// last week's reveals as news.
export const REVEAL_WINDOW_MS = 96 * 3600 * 1000;
export function newCards(R, index, now = Date.now()) {
  const out = [];
  for (const r of index.reveals || []) {
    if (!(r.t <= now && r.t >= now - REVEAL_WINDOW_MS)) continue;
    const hit = R.byCardId.get(r.id);
    if (hit) out.push({ ...hit, t: r.t });
  }
  return out;
}
// A card of a set still being revealed has no TCGplayer listing, and a search
// for it finds nothing — so a name is linked only when it has its own listing.
// Unlinked, every reveal fits: linked, a 250-character search URL per line
// left room for 13 of 36.
// RANK is declared further down; read it at call time, never at import.
const newRank = (r) => (r === "Promo" ? 3 : RANK[r] || 0);
const NEW_BOLD = new Set(["Legendary", "Enchanted", "Epic", "Iconic"]);
export function newCardsMessage(R, index, cards, { origin } = {}) {
  const label = index.revealSet && cards.some((c) => R.sets[c.p.s] && R.sets[c.p.s].n === index.revealSet) ? index.revealSet : null;
  const url = label ? setPageUrl(label) : "https://packs.ink/cards";
  if (!cards.length) {
    return { embeds: [{ title: "Nothing new this week", color: BRAND_COLOR,
      description: "No new cards have reached packs.ink in the last four days. While a set is being revealed they land daily — try again soon, or see what's coming with `/calendar`.",
      footer: { text: "packs.ink" } }],
      components: [{ type: 1, components: [{ type: 2, style: 5, label: "Release calendar", url: "https://packs.ink/calendar" }] }] };
  }
  const line = (c) => {
    const card = R.cards[c.i];
    const set = R.sets[c.p.s] || {};
    const f = c.p.f[0] || [];
    const name = clip(card.n, 60);
    const shown = f[1] && !f[6] ? `[${name}](${buyUrl(card.n, f[1], f[2] || FIN_PRINTING[f[0]])})` : name;
    const rar = c.p.r ? (NEW_BOLD.has(c.p.r) ? ` · **${c.p.r}**` : ` · ${c.p.r}`) : "";
    const where = set.n && set.n !== label ? ` · ${set.n}` : "";
    return `${inkMarks(card.i)} ${shown}${rar}${where}`.trim();
  };
  // One heading per catalog load: a day's reveals share one timestamp.
  const groups = [];
  for (const c of cards) {
    const g = groups[groups.length - 1];
    if (g && g.t === c.t) g.cards.push(c); else groups.push({ t: c.t, cards: [c] });
  }
  const body = [];
  let used = 0, left = cards.length;
  const budget = 3500;
  for (const g of groups) {
    const head = `**Added <t:${Math.floor(g.t / 1000)}:R>**`;
    if (used + head.length + 1 > budget) break;
    body.push(head);
    used += head.length + 1;
    for (const c of g.cards) {
      const l = line(c);
      if (used + l.length + 1 > budget) break;
      body.push(l);
      used += l.length + 1;
      left--;
    }
    if (used >= budget - 40) break;
  }
  if (left > 0) body.push(`*…and ${left} more*`);
  const capped = index.revealCap && cards.length >= index.revealCap;
  const intro = capped
    ? `The **${cards.length}** newest cards, from the last four days.`
    : `**${cards.length} new card${cards.length === 1 ? "" : "s"}** in the last four days.`;
  const linked = body.some((l) => l.includes("]("));
  const main = {
    title: label ? `Just revealed: ${label}` : "Just revealed", url, color: BRAND_COLOR,
    description: intro + "\n\n" + body.join("\n"),
    footer: { text: "Added to packs.ink as they're revealed" + (linked ? ` · ${AFFILIATE_NOTE}` : "") },
  };
  // Pictures: the biggest reveals first, newest among equals.
  const byRank = cards.slice().sort((a, b) => newRank(b.p.r) - newRank(a.p.r) || b.t - a.t);
  const pics = [];
  for (const c of byRank) {
    if (pics.length >= 4) break;
    const img = cardImage(c.p, origin);
    if (img && !pics.includes(img)) pics.push(img);
  }
  const embeds = [{ ...main, ...(pics[0] ? { image: { url: pics[0] } } : {}) }, ...pics.slice(1).map((u) => ({ url, image: { url: u } }))];
  // Every card reachable from a menu: a select holds 25, and a reel holds up
  // to 36, so a second menu takes the rest (each with its own custom_id).
  const options = [];
  const seen = new Set();
  for (const c of cards) {
    const key = R.cardKey(c.p, 0);
    if (seen.has(key) || options.length >= 50) continue;
    seen.add(key);
    options.push({ label: clip(R.cards[c.i].n, 100), value: key, description: clip([c.p.r, (R.sets[c.p.s] || {}).n].filter(Boolean).join(" · "), 100) });
  }
  const menus = [options.slice(0, 25), options.slice(25, 50)].filter((o) => o.length).map((o, k) => ({ type: 1, components: [{
    type: 3, custom_id: openId("card", k), placeholder: k ? "More new cards" : "Look at a new card", options: o }] }));
  return {
    embeds,
    components: [...menus, { type: 1, components: [{ type: 2, style: 5, label: label ? `All of ${clip(label, 60)}` : "Browse the cards", url }] }],
  };
}

// ── /open ────────────────────────────────────────────────────────────────
// custom_id "k|<set index>|<packs>". The site's simPack takes the site's pool
// shape, built here from the index: commons by ink (one of each per pack),
// uncommons, the three rare tiers, their foils, and the three chase rarities.
export const packId = (si, n) => `k|${si}|${n}`;
export function parsePackId(id) {
  const m = /^k\|(\d{1,3})\|(1|24)$/.exec(String(id || ""));
  return m ? { si: Number(m[1]), n: Number(m[2]) } : null;
}

const POOLS = new WeakMap();
export function packPools(R, si) {
  let bySet = POOLS.get(R);
  if (!bySet) { bySet = new Map(); POOLS.set(R, bySet); }
  if (bySet.has(si)) return bySet.get(si);
  const p = { byInk: Object.fromEntries(INKS.map((k) => [k, []])), unc: [], rar: [], sr: [], leg: [], cF: [], uF: [], rF: [], srF: [], lF: [], enc: [], epi: [], ico: [] };
  const FOIL = { Common: "cF", Uncommon: "uF", Rare: "rF", "Super Rare": "srF", Legendary: "lF" };
  const NORM = { Uncommon: "unc", Rare: "rar", "Super Rare": "sr", Legendary: "leg" };
  const CH = { Enchanted: "enc", Epic: "epi", Iconic: "ico" };
  R.cards.forEach((c, i) => {
    for (const pr of c.p) {
      if (pr.s !== si || pr.var) continue;   // a named variant is not a pack slot
      pr.f.forEach((f, fi) => {
        const e = { i, p: pr, fi, price: f[6] ? null : (f[5] ?? f[4] ?? null) };
        if (CH[pr.r]) { if (fi === 0) p[CH[pr.r]].push(e); return; }
        if (f[0] === "N") {
          if (pr.r === "Common") { const ink = (c.i || [])[0]; if (p.byInk[ink]) p.byInk[ink].push(e); }
          else if (NORM[pr.r]) p[NORM[pr.r]].push(e);
        } else if (FOIL[pr.r]) p[FOIL[pr.r]].push(e);
      });
    }
  });
  bySet.set(si, p);
  return p;
}

// n packs of a set: every pull, the total, the best pulls.
export function openPacks(R, si, n = 1, rnd) {
  const pools = packPools(R, si);
  const pull = getPull(R.sets[si].n);
  const pulls = [];
  for (let k = 0; k < n; k++) {
    const pack = rnd ? withRandom(rnd, () => simPack(pools, pull)) : simPack(pools, pull);
    for (const e of pack) pulls.push({ ...e, pack: k });
  }
  const total = pulls.reduce((s, e) => s + (e.price || 0), 0);
  return { pulls, total, n };
}
// simPack reads Math.random; a test hands it a seeded one for a repeatable pack.
function withRandom(rnd, fn) {
  const orig = Math.random;
  Math.random = rnd;
  try { return fn(); } finally { Math.random = orig; }
}

const RANK = { Iconic: 9, Enchanted: 8, Epic: 7, Legendary: 5, "Super Rare": 4, Rare: 3, Uncommon: 2, Common: 1 };
const isHit = (e) => CHASE.has(e.p.r);
function pullLabel(R, e) {
  const c = R.cards[e.i];
  const f = e.p.f[e.fi] || [];
  const foil = f[0] && f[0] !== "N" && !CHASE.has(e.p.r) ? " foil" : "";
  return `${c.n} · ${e.p.r}${foil}`;
}

export function packMessage(R, index, si, result, { origin, who } = {}) {
  const set = R.sets[si];
  const { pulls, total, n } = result;
  const packPrice = (index.sealed || []).filter((s) => s.s === si && s.ty === "Booster Packs" && s.mkt != null).sort((a, b) => a.mkt - b.mkt)[0];
  const boxPrice = (index.sealed || []).filter((s) => s.s === si && s.ty === "Booster Boxes" && s.mkt != null).sort((a, b) => a.mkt - b.mkt)[0];
  const cost = n === 1 ? packPrice && packPrice.mkt : boxPrice && boxPrice.mkt;
  const byValue = pulls.slice().sort((a, b) => (b.price || 0) - (a.price || 0) || (RANK[b.p.r] || 0) - (RANK[a.p.r] || 0));
  const hits = pulls.filter(isHit);
  const lines = [];
  const pct = cost ? Math.round((total / cost) * 100) : null;
  lines.push(`**${money(total) || "$0.00"}** in cards at NM Market` +
    (cost ? ` — ${pct}% of the ${n === 1 ? "pack" : "box"}'s ${money(cost)}` : ""));
  if (hits.length) {
    lines.push(hits.map((e) => `✨ **${e.p.r}!** ${R.cards[e.i].n}${e.price != null ? ` — ${money(e.price)}` : ""}`).join("\n"));
  }
  lines.push("");
  if (n === 1) {
    // Grouped by what each card IS, not by its position in the pack: only the
    // foil slot yields a foil or a chase rarity, and a set whose pool is short
    // of a slot (a prestaged set, an ink with no commons yet) must not shift
    // every later group by one.
    const isFoil = (e) => CHASE.has(e.p.r) || ((e.p.f[e.fi] || [])[0] || "N") !== "N";
    const of = (pred) => pulls.filter((e) => !isFoil(e) && pred(e.p.r));
    const fmt = (arr) => arr.map((e) => `${clip(R.cards[e.i].n, 40)}${e.price != null && e.price >= 1 ? ` (${money(e.price)})` : ""}`).join(" · ") || "—";
    const withPrice = (e) => `${pullLabel(R, e)}${e.price != null ? ` · ${money(e.price)}` : ""}`;
    lines.push(`**Foil** — ${pulls.filter(isFoil).map(withPrice).join(" · ") || "—"}`);
    lines.push(`**Rares** — ${of((r) => r === "Rare" || r === "Super Rare" || r === "Legendary").map(withPrice).join(" · ") || "—"}`);
    lines.push(`**Uncommons** — ${fmt(of((r) => r === "Uncommon"))}`);
    lines.push(`**Commons** — ${fmt(of((r) => r === "Common"))}`);
  } else {
    const count = (r) => pulls.filter((e) => e.p.r === r).length;
    const tally = ["Iconic", "Enchanted", "Epic", "Legendary", "Super Rare"].map((r) => [r, count(r)]).filter((x) => x[1]).map(([r, k]) => `${k} ${r}`).join(" · ");
    if (tally) lines.push(tally);
    lines.push("**Best pulls**");
    for (const e of byValue.slice(0, 8)) lines.push(`${pullLabel(R, e)} — ${e.price != null ? money(e.price) : "no price"}`);
  }
  const url = setPageUrl(set.n);
  const title = `${who ? who + " opened" : "Opened"} ${/^[aeiou]/i.test(set.n) ? "an" : "a"} ${set.n} ${n === 1 ? "booster pack" : "booster box"}`;
  const main = {
    title: clip(title, 256), url, color: hits.length ? 0xc77dff : BRAND_COLOR,
    description: clip(lines.join("\n"), 4000),
    footer: { text: `Simulated with the site's pull rates · TCGplayer NM Market as of ${shortDate(index.priceDate)}` + (boxPrice ? ` · ${AFFILIATE_NOTE}` : "") },
  };
  // Up to four pictures as one gallery: embeds that share a url are drawn by
  // Discord as a single embed with an image grid.
  const pics = [];
  for (const e of byValue) {
    if (pics.length >= 4) break;
    const img = cardImage(e.p, origin);
    if (img && !pics.includes(img)) pics.push(img);
  }
  const embeds = [{ ...main, ...(pics[0] ? { image: { url: pics[0] } } : {}) }, ...pics.slice(1).map((u) => ({ url, image: { url: u } }))];
  const options = [];
  const seenKey = new Set();
  for (const e of byValue) {
    const key = R.cardKey(e.p, e.fi);
    if (seenKey.has(key) || options.length >= 25) continue;
    seenKey.add(key);
    options.push({ label: clip(R.cards[e.i].n, 100), value: key, description: clip(`${e.p.r} · ${e.price != null ? money(e.price) : "no price"}`, 100) });
  }
  return {
    embeds,
    components: [
      { type: 1, components: [{ type: 3, custom_id: openId("card"), placeholder: "Look at a card you pulled", options }] },
      { type: 1, components: [
        { type: 2, style: 1, label: "Open another pack", custom_id: packId(si, 1) },
        { type: 2, style: 2, label: "Open a box", custom_id: packId(si, 24) },
        ...(boxPrice ? [{ type: 2, style: 5, label: "Buy a real box", url: tcgUrl(boxPrice.pid, "Normal") }] : []),
      ] },
    ],
  };
}
