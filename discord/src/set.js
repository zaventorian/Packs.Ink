// set.js — /set (a set at a glance), /open (a simulated pack or box) and /new
// (the site's reveal reel, below).
//
// /set and /open answer from the card index alone: the build runs the site's own EV
// maths each day (build_index.mjs), and a pack is the site's own simPack with
// the site's own pull rates (site.generated.js). So "Box EV" here is the number
// Analytics » Expected Value shows, and a simulated Enchanted turns up exactly
// as often as it does in the site's simulator.
import {
  simPack, getPull, tcgUrl, INKS,
  revealRotation, revealSetLabel, REVEAL_WINDOW_HOURS, REVEAL_MAX_CARDS, REVEAL_EXCLUDED_SETS,
  SET_DISPLAY_NAMES, SET_ORDER, PROMO_RARITY_SETS, normalizeRarity,
  SUPPRESSED_CARD_IDS, TCG_PID_OVERRIDES, COLLECTOR_NUMBER_OVERRIDES, EXTRAS_MAP, CONNECTING_FOILS,
} from "./site.generated.js";
import { money, shortDate, BRAND_COLOR, cardImage, buyUrl, AFFILIATE_NOTE, openId, inkMarks, packId } from "./embeds.js";
import { FIN_PRINTING } from "./data.js";
import { statsLineFor } from "./stats.js";

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
    const v = f[4] ?? f[5];
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
  const box = cheapest("Booster Boxes", "low") || cheapest("Booster Boxes", "mkt");
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
    // Low leads, as it does on the site.
    fields.push({ name: "Booster box", inline: true, value: [
      box.low != null ? `**${money(box.low)}** Low` : null,
      box.mkt != null ? (box.low != null ? `${money(box.mkt)} Market` : `**${money(box.mkt)}** Market`) : null,
    ].filter(Boolean).join("\n") || "no price" });
  }
  if (ev && !o.upcoming) {
    fields.push({ name: "Box EV", inline: true, value: [
      ev.low != null ? `**${money(ev.low)}** at Low` : null,
      ev.mkt != null ? (ev.low != null ? `${money(ev.mkt)} at NM Market` : `**${money(ev.mkt)}** at NM Market`) : null,
    ].filter(Boolean).join("\n") });
    const evLead = ev.low ?? ev.mkt;
    const boxLead = box ? (ev.low != null ? (box.low ?? box.mkt) : (box.mkt ?? box.low)) : null;
    if (box && boxLead && evLead) {
      const ratio = evLead / boxLead;
      fields.push({ name: "Open or hold?", inline: true, value:
        `The cards in a box are worth about **${Math.round(ratio * 100)}%** of its price` +
        (ratio >= 1 ? " — more than the box." : ".") });
    }
  }
  const sealedLines = [];
  for (const ty of TYPE_ORDER) {
    const s = o.sealed.filter((x) => x.ty === ty).sort((a, b) => (a.low ?? a.mkt) - (b.low ?? b.mkt))[0];
    if (s) sealedLines.push(`[${TYPE_ONE[ty] || ty}](${tcgUrl(s.pid, "Normal")}) ${money(s.low ?? s.mkt)}`);
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
        description: statsLineFor(R.cards[x.i], [x.p.r, money(x.v)]) })) }] });
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
// The site's reveal reel, worked out when someone asks. The daily build hands
// over the reel's INPUTS rather than its answer — every card that reached the
// catalog inside the window, and when each card's NAME was first seen — and
// this runs the site's own revealRotation over them plus any card that has
// landed since the build.
//
// ⚠ Two reasons it cannot be answered at build time. Reveals land all day
// (prestaged art through the afternoon, Lorcast's load in the evening) and the
// index is built once, so a reel frozen at build time ran up to a day behind the
// site's. And the site's reel moves on its own: a card leaves 96 hours after its
// NAME first appeared, so an Enchanted revealed on Wednesday goes with Monday's
// base card — which only a first-seen time can reproduce.
export const REVEAL_WINDOW_MS = REVEAL_WINDOW_HOURS * 36e5;
const isoOf = (ms) => new Date(ms).toISOString();

// The index's window, as the rows revealRotation reads. An entry from an index
// built before first-seen times were stored ({id, t} alone) takes its name,
// set and number from the card index and counts its own time as first seen.
export function indexRevealRows(R, index) {
  const rows = [];
  for (const e of index.reveals || []) {
    if (!e || !e.id || !Number.isFinite(e.t)) continue;
    const hit = R.byCardId.get(e.id);
    const name = e.n || (hit && R.cards[hit.i].n);
    if (!name) continue;
    rows.push({ card_id: e.id, "Product Name": name, added_at: isoOf(e.t), img_normal: "art",
      Set: e.s != null ? e.s : (hit && R.sets[hit.p.s] ? R.sets[hit.p.s].n : ""),
      Number: e.no != null ? e.no : (hit ? hit.p.no : "") });
    // When the name was first seen: the reel drops every card of a name once
    // that name is older than the window.
    if (Number.isFinite(e.f) && e.f < e.t) rows.push({ "Product Name": name, added_at: isoOf(e.f) });
  }
  return rows;
}

// What the daily build stores for the reel: every card inside the window at
// `now`, one per card_id, art only, never Extras, only cards the index holds —
// with when its NAME was first seen, when that is earlier than the card. A
// name first seen before the window is left out: it is a reprint now and stays
// one. These are revealRotation's own checks in its own order, so the stored
// entries give the site's reel at any later moment too (the guard proves it).
export function revealInputs(rows, { now = Date.now(), indexed = null } = {}) {
  const cut = now - REVEAL_WINDOW_MS;
  const firstSeen = new Map();
  for (const r of rows || []) {
    const nm = r && r["Product Name"];
    if (!nm) continue;
    const t = r.added_at ? Date.parse(r.added_at) : NaN;
    const v = Number.isFinite(t) ? t : -Infinity;
    if (!firstSeen.has(nm) || v < firstSeen.get(nm)) firstSeen.set(nm, v);
  }
  const win = new Map();
  for (const r of rows || []) {
    if (!r || !r.card_id || !r.added_at || win.has(r.card_id) || (indexed && !indexed.has(r.card_id))) continue;
    if (REVEAL_EXCLUDED_SETS.has(r.Set)) continue;
    const t = Date.parse(r.added_at);
    const f = firstSeen.get(r["Product Name"]);
    if (!Number.isFinite(t) || t < cut || !(f >= cut)) continue;
    if (!(r.img_normal || r.img_large || r.img_small)) continue;
    win.set(r.card_id, { id: r.card_id, t, n: r["Product Name"], s: r.Set || "", no: String(r.Number || ""),
      ...(f < t ? { f } : {}) });
  }
  return [...win.values()].sort((a, b) => b.t - a.t);
}

// Cards that reached the catalog after the build read it: a direct read of
// `cards`, put through the rules the site's catalog transform applies before
// its reel ever sees a row, so a card that landed an hour ago is judged the way
// tomorrow's index will judge it.
const FRESH_COLS = "id,name,version,set_id,rarity,ink,inks,collector_number,"
  + "image_small,image_normal,image_large,tcgplayer_product_id,inserted_at,sets(name)";
// Rows inserted a little before the read are asked for too — a row landing
// while the build paged through `cards` can miss it — and those the index did
// see are skipped by id, so the overlap costs nothing.
const FRESH_OVERLAP_MS = 2 * 36e5;
const FRESH_LIMIT = 250;
// The site's transform skips a connecting foil's companion product outright
// (Index.html: `new Set(Object.values(CONNECTING_FOILS))`).
const FOIL_COMPANION_PIDS = new Set(Object.values(CONNECTING_FOILS));
const pgQuote = (s) => '"' + String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
export async function freshRevealRows(db, R, index, now = Date.now()) {
  const cutoff = now - REVEAL_WINDOW_MS;
  const read = Date.parse(index.catalogAt || index.built || "");
  const since = Math.max(cutoff, (Number.isFinite(read) ? read : cutoff) - FRESH_OVERLAP_MS);
  if (since >= now) return [];
  const got = await db.get("cards", { select: FRESH_COLS, inserted_at: "gt." + isoOf(since),
    order: "inserted_at.desc,id.asc", limit: FRESH_LIMIT });
  const rows = [];
  for (const c of Array.isArray(got) ? got : []) {
    if (!c || !c.id || !c.name || R.byCardId.has(c.id) || SUPPRESSED_CARD_IDS.has(c.id)) continue;
    const raw = c.sets && c.sets.name;
    const set = SET_DISPLAY_NAMES[raw] || raw;
    if (!set) continue;
    const name = c.version ? c.name + " - " + c.version : c.name;
    const ov = TCG_PID_OVERRIDES[name + "|" + (c.collector_number || "")];
    const pid = ov != null ? ov : c.tcgplayer_product_id;
    if (pid != null && FOIL_COMPANION_PIDS.has(pid)) continue;
    if (pid != null && EXTRAS_MAP[pid] && EXTRAS_MAP[pid].excludeFromBaseSet) continue;
    let rarity = normalizeRarity(c.rarity);
    if (!SET_ORDER.includes(set)) rarity = "Promo";
    else if (PROMO_RARITY_SETS.has(set)) rarity = "Promo";
    const art = c.image_normal || c.image_large || c.image_small || null;
    rows.push({ card_id: c.id, "Product Name": name, _card: c.name, Set: set, added_at: c.inserted_at, img_normal: art,
      Number: COLLECTOR_NUMBER_OVERRIDES[(c.set_id || "") + "|" + (c.collector_number || "")] || c.collector_number || "",
      _fresh: { rarity, pid: pid ?? null, art: c.image_large || art,
        inks: Array.isArray(c.inks) && c.inks.length ? c.inks : (c.ink ? [c.ink] : []) } });
  }
  if (!rows.length) return [];
  // ⚠ A reprint is not a reveal: a new printing of a name the catalog held
  // before the window is left out, exactly as the site leaves it out. That is a
  // question about the WHOLE catalog, so it is asked of the database. If it
  // cannot be answered this throws, and the caller shows the index alone —
  // never a list that might present an old card as news.
  const old = await db.get("cards", { select: "id,name,version",
    name: "in.(" + [...new Set(rows.map((r) => r._card))].map(pgQuote).join(",") + ")",
    or: `(inserted_at.lt.${pgQuote(isoOf(cutoff))},inserted_at.is.null)`, limit: 2000 });
  for (const o of Array.isArray(old) ? old : []) {
    if (!o || !o.name || SUPPRESSED_CARD_IDS.has(o.id)) continue;
    rows.push({ "Product Name": o.version ? o.name + " - " + o.version : o.name, added_at: null });
  }
  return rows;
}

// The reel: the site's revealRotation over the index's window and whatever
// freshRevealRows found. An index card keeps its printing (i, p); a card the
// index has not seen yet carries what the database said about it.
export function newCards(R, index, now = Date.now(), fresh = []) {
  const out = [];
  for (const c of revealRotation([...indexRevealRows(R, index), ...fresh], now)) {
    const hit = R.byCardId.get(c.card_id);
    if (hit) out.push({ i: hit.i, p: hit.p, t: c.t, set: c.set });
    else if (c.row && c.row._fresh) out.push({ t: c.t, set: c.set, name: c.name, fresh: c.row._fresh });
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
const rarityOf = (c) => (c.fresh ? c.fresh.rarity : c.p.r) || null;
// Headings are DAYS back from the moment of asking. Reveals trickle in one or
// two at a time (prestaged art is added through the day), so a heading per
// load timestamp was a heading per card, and Discord's relative times coarsen
// with age until two neighbouring headings both said "a day ago".
const DAY_MS = 24 * 36e5;
const ageHeading = (k) => (k === 0 ? "Added in the last 24 hours" : `Added ${k}–${k + 1} days ago`);
export function newCardsMessage(R, index, cards, { origin, now = Date.now() } = {}) {
  const label = revealSetLabel(cards);
  const url = label ? setPageUrl(label) : "https://packs.ink/cards";
  if (!cards.length) {
    return { embeds: [{ title: "Nothing new this week", color: BRAND_COLOR,
      description: "No new cards have reached packs.ink in the last four days. While a set is being revealed they land daily — try again soon, or see what's coming with `/calendar`.",
      footer: { text: "packs.ink" } }],
      components: [{ type: 1, components: [{ type: 2, style: 5, label: "Release calendar", url: "https://packs.ink/calendar" }] }] };
  }
  const line = (c) => {
    const rar = rarityOf(c);
    const rarTxt = rar ? (NEW_BOLD.has(rar) ? ` · **${rar}**` : ` · ${rar}`) : "";
    const where = c.set && c.set !== label ? ` · ${c.set}` : "";
    if (c.fresh) {
      const name = clip(c.name, 60);
      const shown = c.fresh.pid ? `[${name}](${buyUrl(c.name, c.fresh.pid, null)})` : name;
      return `${inkMarks(c.fresh.inks)} ${shown}${rarTxt}${where}`.trim();
    }
    const card = R.cards[c.i];
    const f = c.p.f[0] || [];
    const name = clip(card.n, 60);
    const shown = f[1] && !f[6] ? `[${name}](${buyUrl(card.n, f[1], f[2] || FIN_PRINTING[f[0]])})` : name;
    return `${inkMarks(card.i)} ${shown}${rarTxt}${where}`.trim();
  };
  const groups = [];
  for (const c of cards) {
    const k = Math.max(0, Math.floor((now - c.t) / DAY_MS));
    const g = groups[groups.length - 1];
    if (g && g.k === k) g.cards.push(c); else groups.push({ k, cards: [c] });
  }
  const body = [];
  let used = 0, left = cards.length;
  const budget = 3500;
  for (const g of groups) {
    const head = `**${ageHeading(g.k)}**`;
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
  const capped = cards.length >= REVEAL_MAX_CARDS;
  const intro = capped
    ? `The **${cards.length}** newest cards, from the last four days.`
    : `**${cards.length} new card${cards.length === 1 ? "" : "s"}** in the last four days.`;
  const linked = body.some((l) => l.includes("]("));
  const pending = cards.some((c) => c.fresh);
  const main = {
    title: label ? `Just revealed: ${label}` : "Just revealed", url, color: BRAND_COLOR,
    description: intro + "\n\n" + body.join("\n"),
    footer: { text: ["Added to packs.ink as they're revealed",
      // A card that landed since the daily build has no card page in the bot
      // yet, so it is listed but not in the menus.
      pending ? "The newest open from the menu after the daily update" : null,
      linked ? AFFILIATE_NOTE : null].filter(Boolean).join(" · ") },
  };
  // Pictures: the biggest reveals first, newest among equals.
  const byRank = cards.slice().sort((a, b) => newRank(rarityOf(b)) - newRank(rarityOf(a)) || b.t - a.t);
  const pics = [];
  for (const c of byRank) {
    if (pics.length >= 4) break;
    const img = c.fresh
      ? cardImage({ img: c.fresh.art, f: c.fresh.pid ? [["N", c.fresh.pid]] : [] }, origin)
      : cardImage(c.p, origin);
    if (img && !pics.includes(img)) pics.push(img);
  }
  const embeds = [{ ...main, ...(pics[0] ? { image: { url: pics[0] } } : {}) }, ...pics.slice(1).map((u) => ({ url, image: { url: u } }))];
  // Every index card reachable from a menu: a select holds 25, and a reel holds
  // up to 36, so a second menu takes the rest (each with its own custom_id).
  const options = [];
  const seen = new Set();
  for (const c of cards) {
    if (c.fresh) continue;
    const key = R.cardKey(c.p, 0);
    if (seen.has(key) || options.length >= 50) continue;
    seen.add(key);
    options.push({ label: clip(R.cards[c.i].n, 100), value: key, description: statsLineFor(R.cards[c.i], [c.p.r, { k: "set", t: (R.sets[c.p.s] || {}).n }]) });
  }
  const menus = [options.slice(0, 25), options.slice(25, 50)].filter((o) => o.length).map((o, k) => ({ type: 1, components: [{
    type: 3, custom_id: openId("card", k), placeholder: k ? "More new cards" : "Look at a new card", options: o }] }));
  return {
    embeds,
    components: [...menus, { type: 1, components: [{ type: 2, style: 5, label: label ? `All of ${clip(label, 60)}` : "Browse the cards", url }] }],
  };
}

// ── /open ────────────────────────────────────────────────────────────────
// custom_id "k|<set index>|<packs>" (packId, in embeds.js — a booster box's
// price reply offers "Open a box" too). The site's simPack takes the site's
// pool shape, built here from the index: commons by ink (one of each per
// pack), uncommons, the three rare tiers, their foils, and the three chase
// rarities.
export { packId, parsePackId } from "./embeds.js";

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
        const e = { i, p: pr, fi, price: f[6] ? null : (f[4] ?? f[5] ?? null) };
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
  const px = (s) => s.low ?? s.mkt;
  const packPrice = (index.sealed || []).filter((s) => s.s === si && s.ty === "Booster Packs" && px(s) != null).sort((a, b) => px(a) - px(b))[0];
  const boxPrice = (index.sealed || []).filter((s) => s.s === si && s.ty === "Booster Boxes" && px(s) != null).sort((a, b) => px(a) - px(b))[0];
  const cost = n === 1 ? packPrice && px(packPrice) : boxPrice && px(boxPrice);
  const byValue = pulls.slice().sort((a, b) => (b.price || 0) - (a.price || 0) || (RANK[b.p.r] || 0) - (RANK[a.p.r] || 0));
  const hits = pulls.filter(isHit);
  const lines = [];
  const pct = cost ? Math.round((total / cost) * 100) : null;
  lines.push(`**${money(total) || "$0.00"}** in cards at Low` +
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
    footer: { text: `Simulated with the site's pull rates · TCGplayer Low as of ${shortDate(index.priceDate)}` + (boxPrice ? ` · ${AFFILIATE_NOTE}` : "") },
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
    options.push({ label: clip(R.cards[e.i].n, 100), value: key, description: statsLineFor(R.cards[e.i], [e.p.r, e.price != null ? money(e.price) : "no price"]) });
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
