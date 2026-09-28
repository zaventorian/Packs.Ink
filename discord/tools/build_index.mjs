// build_index.mjs — the card index the bot searches.
//
//     node discord/tools/build_index.mjs            # writes discord/src/card-index.json
//     node discord/tools/build_index.mjs --fixture  # also refreshes discord/test/fixture-index.json
//
// Reads the same tables the site's first page load reads, then runs the SITE'S
// OWN catalog transform over them (see sitecode.mjs), so every name, set label,
// printing and foil badge in the bot is the one the site shows. Adds the one
// thing the site does not have in one place: how much each card is PLAYED.
//
// ⚠ "The main one that's played" is measured, not guessed: every tournament
// top-cut deck we hold (tournament_decks -> deck_cards; those decks are
// ownerless and stored in plaintext), weighted by how recent the event was.
// User-built decks are deliberately NOT counted — their card ids are
// obfuscated at rest and decoding them server-side for a popularity number is
// not a trade worth making.
//
// The output is bundled INTO the worker at deploy time: parsing it at isolate
// startup costs nothing against the per-request CPU limit, where fetching and
// parsing it on a cold request would eat most of the 10 ms free-plan budget.
// Prices here are only a build-time snapshot for autocomplete labels — every
// card lookup fetches live prices.
import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { loadSite } from "./sitecode.mjs";
import { fileURLToPath } from "node:url";
import { bakeArt, SAFE_IMG } from "./bake_art.mjs";

const SB_URL = process.env.SUPABASE_URL || "https://umwqowkiatjjltologrd.supabase.co";
// Public publishable key — the same one Index.html and worker/index.js ship.
const SB_KEY = process.env.SUPABASE_ANON_KEY || "sb_publishable_B2qq0Dsfij-7X2CZSxl2uQ_7PWc6Ob0";
const OUT = new URL("../src/card-index.json", import.meta.url);
const FIXTURE = new URL("../test/fixture-index.json", import.meta.url);

// Recency half-life for play counts. The competitive pool rotates every set
// (~quarterly), so a deck from two sets ago should count for about a quarter.
const PLAY_HALF_LIFE_DAYS = 120;

async function sbAll(table, params, { pageSize = 1000 } = {}) {
  const out = [];
  for (let from = 0; ; from += pageSize) {
    const qs = new URLSearchParams(params).toString();
    const res = await fetch(`${SB_URL}/rest/v1/${table}?${qs}`, {
      headers: { apikey: SB_KEY, Range: `${from}-${from + pageSize - 1}`, "Range-Unit": "items" },
    });
    if (!res.ok) throw new Error(`${table}: HTTP ${res.status} ${await res.text()}`);
    const rows = await res.json();
    out.push(...rows);
    if (rows.length < pageSize) break;
  }
  return out;
}

const chunk = (arr, n) => Array.from({ length: Math.ceil(arr.length / n) }, (_, i) => arr.slice(i * n, i * n + n));

const site = loadSite([
  "transformSupabaseData", "setPrintingBadges", "printingBadge",
  "deriveSealedDisplayType", "isHiddenSealedListing", "isUnpricedSealed", "cleanSealedName",
  "SET_NICKNAMES", "MAINLINE_SETS", "SET_ORDER", "SET_RELEASE_DATES", "UPCOMING_SET_NAMES",
  "SPLIT_BY_PRINTING_SETS_GLOBAL", "SET_DISPLAY_NAMES", "INK_COLORS", "RARITY_ALIASES", "cardFamilyKey",
  // /set's box EV and /movers' sealed movers: the site's own maths, run here
  // once a day so the Worker answers from the index with no database read.
  "processData", "calcEV", "computeSealedDeltas", "SEALED_MOVER_KIND_OF_TYPE", "lorcanaSetArt",
]);

const CARDS_COLS = "id,set_id,name,version,rarity,ink,inks,collector_number,cost,inkable,card_type,"
  + "classifications,text,image_small,image_normal,image_large,tcgplayer_product_id,inserted_at";
const PRICE_COLS = "tcgplayer_product_id,printing,low_price,market_price,price_date";
const SEALED_COLS = "tcgplayer_product_id,set_id,product_type,name,clean_name,low_price,market_price,image_url,printing,price_date,is_stale";

console.log("fetching catalog…");
const [sets, prices, cards, sealed, tournaments, tdecks, gradedRoll, rawRoll] = await Promise.all([
  sbAll("sets", { select: "id,name,code,released_at", order: "id.asc" }),
  sbAll("card_prices_latest", { select: PRICE_COLS, order: "tcgplayer_product_id.asc,printing.asc" }),
  sbAll("cards", { select: CARDS_COLS, order: "id.asc" }),
  sbAll("sealed_prices_latest", { select: SEALED_COLS, order: "tcgplayer_product_id.asc,printing.asc" }),
  sbAll("tournaments", { select: "id,event_date,format", order: "id.asc" }),
  sbAll("tournament_decks", { select: "tournament_id,deck_id,place_rank", order: "deck_id.asc" }),
  sbAll("graded_sales_rollup", { select: "card_id,sale_count", order: "card_id.asc,grader.asc,grade.asc,printing.asc" }),
  sbAll("raw_sales_rollup", { select: "card_id", order: "card_id.asc" }).catch(() => []),
]);
// TCGplayer's own spelling of a product where it differs from ours (migration
// 169): mass entry matches names exactly, so /deck's one-cart link needs them.
const tcgNames = await sbAll("tcgplayer_names", { select: "product_id,name", order: "product_id.asc" }).catch(() => []);
console.log(`  ${cards.length} cards, ${prices.length} prices, ${sets.length} sets, ${sealed.length} sealed, `
  + `${tournaments.length} tournaments / ${tdecks.length} top decks`);

// ── Run the site's transform ────────────────────────────────────────────
const setNameById = Object.fromEntries(sets.map((s) => [s.id, s.name]));
const rows = site.transformSupabaseData(prices, cards, setNameById);
site.setPrintingBadges(rows);
const priceDate = prices.reduce((m, p) => (p.price_date && p.price_date > m ? p.price_date : m), "");
console.log(`  transform -> ${rows.length} catalog rows, newest price ${priceDate}`);

// ── Sets ────────────────────────────────────────────────────────────────
// Display names come from the transform (SET_DISPLAY_NAMES applied), so the
// set list is rebuilt from what the rows actually say.
const setMeta = new Map();   // display name -> {id, code, date}
for (const s of sets) {
  const disp = site.SET_DISPLAY_NAMES[s.name] || s.name;
  if (!setMeta.has(disp)) setMeta.set(disp, { id: s.id, code: s.code || null, date: s.released_at || null });
}
const releaseOf = (name) => {
  const d = site.SET_RELEASE_DATES[name];
  return (d && (d.lgs || d.retail || d.prerelease)) || (setMeta.get(name) || {}).date || null;
};
const setNames = [...new Set(rows.map((r) => r.Set).filter(Boolean))];
// Mainline sets in release order first, then everything else by date.
const mainOrder = new Map(site.MAINLINE_SETS.map((n, i) => [n, i]));
setNames.sort((a, b) => {
  const ma = mainOrder.has(a), mb = mainOrder.has(b);
  if (ma && mb) return mainOrder.get(a) - mainOrder.get(b);
  if (ma !== mb) return ma ? -1 : 1;
  return String(releaseOf(a) || "9999").localeCompare(String(releaseOf(b) || "9999")) || a.localeCompare(b);
});
const aliasesBySet = new Map();
for (const [nick, target] of Object.entries(site.SET_NICKNAMES)) {
  if (!aliasesBySet.has(target)) aliasesBySet.set(target, []);
  aliasesBySet.get(target).push(nick);
}
// A set with nothing searchable in it (Format Coconut: leaders only) is left
// out, or its name would become a set alias that can match nothing.
const liveSets = new Set(rows.filter((r) => !r.isCoconut).map((r) => r.Set));
for (const p of sealed) if (p.set_id != null) liveSets.add(site.SET_DISPLAY_NAMES[setNameById[p.set_id]] || setNameById[p.set_id]);
for (let i = setNames.length - 1; i >= 0; i--) if (!liveSets.has(setNames[i])) setNames.splice(i, 1);
const setIdx = new Map(setNames.map((n, i) => [n, i]));
// Box EV per booster set, exactly as Analytics » Expected Value computes it:
// the average price of each rarity slot times how many a box holds. Nothing
// excluded and every card counted (the site's defaults), at Low and at NM
// Market; `nc` is the "cards under $1 count as $0" reading beside each.
const { avgs } = site.processData(rows);
const cents = (v) => (v == null || !Number.isFinite(v) || v <= 0 ? null : Math.round(v * 100) / 100);
const evOf = (name) => {
  if (!avgs[name]) return null;
  const none = new Set();
  return {
    low: cents(site.calcEV(avgs, name, false, none, "low")), mkt: cents(site.calcEV(avgs, name, false, none, "market")),
    lowNC: cents(site.calcEV(avgs, name, true, none, "low")), mktNC: cents(site.calcEV(avgs, name, true, none, "market")),
  };
};
// Logos Discord can show: the WebP wordmarks (The First Chapter's is an SVG,
// and Discord shows no SVG).
const logoOf = (name) => {
  const art = site.lorcanaSetArt(name);
  return art && /\.(?:webp|png|jpe?g)$/i.test(art.src) ? "https://packs.ink/" + art.src : null;
};
const setsOut = setNames.map((name) => {
  const m = setMeta.get(name) || {};
  const main = mainOrder.has(name);
  const alias = new Set(aliasesBySet.get(name) || []);
  if (main) {
    const n = mainOrder.get(name) + 1;
    for (const a of [`set ${n}`, `s${n}`, `set${n}`, `chapter ${n}`, `ch${n}`, `ch ${n}`]) alias.add(a);
  }
  const rd = site.SET_RELEASE_DATES[name] || {};
  return {
    n: name, id: m.id || null, code: m.code || null, date: releaseOf(name),
    main: main ? mainOrder.get(name) + 1 : 0, alias: [...alias],
    ...(rd.prerelease || rd.lgs || rd.retail ? { rel: { pre: rd.prerelease || null, lgs: rd.lgs || null, retail: rd.retail || null } } : {}),
    ...(main && evOf(name) ? { ev: evOf(name) } : {}),
    ...(logoOf(name) ? { logo: logoOf(name) } : {}),
    // Foil and non-foil share one card_id but are two markets (and two tiles
    // on the site): Challenge Promo (C1).
    ...(site.SPLIT_BY_PRINTING_SETS_GLOBAL.has(name) ? { sp: 1 } : {}),
  };
});

// ── Play counts from tournament top decks ──────────────────────────────
const tById = new Map(tournaments.map((t) => [t.id, t]));
const now = Date.now();
const deckWeight = new Map();
for (const td of tdecks) {
  const t = tById.get(td.tournament_id);
  if (!t || !td.deck_id) continue;
  const ageDays = Math.max(0, (now - Date.parse(t.event_date)) / 86400000);
  deckWeight.set(td.deck_id, Math.pow(0.5, ageDays / PLAY_HALF_LIFE_DAYS));
}
const deckCards = [];
for (const ids of chunk([...deckWeight.keys()], 60)) {
  deckCards.push(...await sbAll("deck_cards", { select: "deck_id,card_id", deck_id: `in.(${ids.join(",")})`, order: "deck_id.asc,card_id.asc" }));
}
const nameByCardId = new Map();
for (const r of rows) if (r.card_id && r["Product Name"]) nameByCardId.set(r.card_id, r["Product Name"]);
for (const c of cards) {
  if (!nameByCardId.has(c.id)) nameByCardId.set(c.id, c.version ? `${c.name} - ${c.version}` : c.name);
}
// Keyed by the site's cardFamilyKey, never the raw name: Lorcast spells some
// cards differently across printings ("Miserable As Usual" / "Miserable as
// Usual", "HeiHei" / "Heihei"), and one card must count as one card.
const famOf = (name) => site.cardFamilyKey(name);
const plays = new Map();       // family key -> weighted deck count
const seenDeckName = new Set();
for (const dc of deckCards) {
  const name = nameByCardId.get(dc.card_id);
  if (!name) continue;
  const fam = famOf(name);
  const key = dc.deck_id + "|" + fam;    // a playset of two printings is one deck
  if (seenDeckName.has(key)) continue;
  seenDeckName.add(key);
  plays.set(fam, (plays.get(fam) || 0) + (deckWeight.get(dc.deck_id) || 0));
}
console.log(`  plays: ${deckCards.length} deck rows across ${deckWeight.size} decks -> ${plays.size} played cards`);
// The same weights summed over every deck that has cards: a card's `pl` over
// this is the share of recent top-cut decks that play it ("in 38% of decks").
const decksWithCards = new Set(deckCards.map((d) => d.deck_id));
const playDecks = Math.round([...decksWithCards].reduce((s, id) => s + (deckWeight.get(id) || 0), 0) * 1000) / 1000;

const gradedCount = new Map();
for (const g of gradedRoll) gradedCount.set(g.card_id, (gradedCount.get(g.card_id) || 0) + (g.sale_count || 0));
const rawSales = new Set(rawRoll.map((r) => r.card_id));

// ── Identities ──────────────────────────────────────────────────────────
// One per Product Name ("Mowgli - Man Cub"): the thing a player means. Each
// holds its printings (a card_id in a set), each printing its finishes.
const FIN = { "Normal": "N", "Cold Foil": "C", "Holofoil": "H", "Foil": "F" };
const num = (v) => (v == null || v === "" || !Number.isFinite(Number(v)) ? null : Math.round(Number(v) * 100) / 100);
// Card art is DERIVED at runtime whenever it can be (TCGplayer's JPG from the
// pid, else Lorcast's AVIF from the card id), so the index only stores the
// exceptions: prestaged art in our own storage, regional-exclusive scans and
// TCGplayer-only custom cards. That is ~100 URLs instead of ~3,400.
const LORCAST_ART = /^https:\/\/cards\.lorcast\.io\/card\/digital\/(?:large|normal|small)\/(crd_[0-9a-f]{32})\.avif(?:\?\d+)?$/;
const artUrl = (r) => {
  let u = r.img_large || r.img_normal || null;
  if (!u) return null;
  if (u.startsWith("/img-proxy/")) u = "https://cards.lorcast.io/" + u.slice("/img-proxy/".length);
  else if (u.startsWith("/")) u = "https://packs.ink" + u;
  // "Logos/cards/…": a regional scan or a promo photo, served by the site.
  else if (!/^(?:https?:|data:)/.test(u)) u = "https://packs.ink/" + u;
  const m = u.match(LORCAST_ART);
  return m && m[1] === r.card_id ? null : u;
};
// The day each card first reached our catalog — for a card from a set not out
// yet, the day it was revealed (prestaged from the reveal, within a day or so).
// A variant clone ("<base>::variant::…") carries its base card's date.
const insertedOn = new Map(cards.map((c) => [c.id, c.inserted_at ? String(c.inserted_at).slice(0, 10) : null]));
const insOf = (id) => insertedOn.get(id) || insertedOn.get(String(id).split("::")[0]) || null;
const byName = new Map();
let skipped = 0;
for (const r of rows) {
  if (r.isCoconut || !r["Product Name"] || !r.card_id) { skipped++; continue; }
  if (!setIdx.has(r.Set)) { skipped++; continue; }
  const name = r["Product Name"];
  const fam = famOf(name);
  let ident = byName.get(fam);
  if (ident && !ident.spellMain && site.MAINLINE_SETS.includes(r.Set) && ident.n !== name) {
    // Prefer the booster printing's spelling for the display name.
    const dash = name.indexOf(" - ");
    ident.n = name; ident.c = dash > 0 ? name.slice(0, dash) : name; ident.v = dash > 0 ? name.slice(dash + 3) : "";
    ident.spellMain = true;
  }
  if (!ident) {
    const dash = name.indexOf(" - ");
    ident = {
      n: name,
      c: dash > 0 ? name.slice(0, dash) : name,
      v: dash > 0 ? name.slice(dash + 3) : "",
      t: r.card_type || null,
      k: r.classifications || [],
      w: r.keywords || [],
      i: r.inks || (r.ink ? [r.ink] : []),
      cost: r.cost ?? null,
      pl: 0, gs: 0,
      p: new Map(),
      spellMain: site.MAINLINE_SETS.includes(r.Set),
    };
    byName.set(fam, ident);
  }
  let pr = ident.p.get(r.card_id);
  if (!pr) {
    pr = {
      id: r.card_id,
      s: setIdx.get(r.Set),
      no: r.Number || "",
      r: r.Rarity || null,
      var: r.variant_label || null,
      img: artUrl(r),
      raw: rawSales.has(r.card_id) ? 1 : 0,
      g: gradedCount.get(String(r.card_id).split("::")[0]) || 0,
      ins: insOf(r.card_id),
      f: [],
    };
    ident.p.set(r.card_id, pr);
  }
  const printing = r.tcg_printing || r.Printing || "Normal";
  const code = FIN[printing] || "N";
  // One finish per (card, printing) — a duplicate row would be the transform
  // emitting the same slot twice, which the site would also dedupe.
  if (pr.f.some((f) => f[0] === code)) continue;
  const badge = site.printingBadge(printing, r.card_id);
  // [code, pid, tcg printing, badge, low, market, no-own-listing]
  pr.f.push([code, r.tcgplayer_product_id ?? null, printing, badge || null,
    num(r["Low Price"]), num(r["TCGPlayer Market"]), r.isCustomVariant ? 1 : 0]);
}

const RARITY_RANK = { Common: 0, Uncommon: 1, Rare: 2, "Super Rare": 3, Legendary: 4, Enchanted: 5, Epic: 6, Iconic: 7, Promo: 8 };
const identities = [...byName.values()].map((ident) => {
  const printings = [...ident.p.values()];
  for (const pr of printings) {
    ident.gs += pr.id.includes("::") ? 0 : (pr.g || 0);
    // Non-foil first, then the foil, so index 0 is the default finish.
    pr.f.sort((a, b) => (a[0] === "N" ? 0 : 1) - (b[0] === "N" ? 0 : 1));
  }
  printings.sort((a, b) => (a.s - b.s) || ((RARITY_RANK[a.r] ?? 9) - (RARITY_RANK[b.r] ?? 9)) || String(a.no).localeCompare(String(b.no)));
  const { spellMain, ...rest } = ident;
  return { ...rest, pl: Math.round((plays.get(famOf(ident.n)) || 0) * 1000) / 1000, p: printings };
});
identities.sort((a, b) => a.n.localeCompare(b.n));

// ── Sealed ──────────────────────────────────────────────────────────────
// Same admission rule as the site's searchSealedProducts: priced rows only,
// never a promo single or a hidden multi-unit listing.
const sealedOut = [];
for (const p of sealed) {
  if (p.printing !== "Normal" || p.product_type === "Promo Single") continue;
  if (site.isUnpricedSealed(p) || site.isHiddenSealedListing(p)) continue;
  if (p.low_price == null && p.market_price == null) continue;
  const setName = p.set_id != null ? (site.SET_DISPLAY_NAMES[setNameById[p.set_id]] || setNameById[p.set_id] || null) : null;
  const ty = site.deriveSealedDisplayType(p);
  sealedOut.push({
    n: site.cleanSealedName(p.name || ""),
    s: setName != null && setIdx.has(setName) ? setIdx.get(setName) : -1,
    sn: setName,
    ty,
    pid: p.tcgplayer_product_id,
    low: num(p.low_price), mkt: num(p.market_price),
    img: p.image_url ? p.image_url.replace(/_200w\.jpg$/, "_in_1000x1000.jpg") : null,
    // Boxes / troves / specials — the site's Sealed Movers row. A stale row
    // (gone from today's snapshot) never moves: its "today" is whatever
    // TCGplayer last published.
    ...(site.SEALED_MOVER_KIND_OF_TYPE[ty] && !p.is_stale ? { k: site.SEALED_MOVER_KIND_OF_TYPE[ty] } : {}),
  });
}
sealedOut.sort((a, b) => a.n.localeCompare(b.n));

// ── Sealed price changes ────────────────────────────────────────────────
// computeSealedDeltas is the site's own (Screener sealed mode, Sealed Movers),
// run over a year of history for the mover candidates, as of the index's price
// date — so a product that stopped being listed reports no move (migration
// 172's rule). Stored as {window: [Low %, NM Market %]}.
{
  const movers = sealedOut.filter((s) => s.k);
  const since = new Date(Date.parse(priceDate + "T00:00:00Z") - 380 * 86400000).toISOString().slice(0, 10);
  const hist = [];
  for (const ids of chunk(movers.map((s) => s.pid), 40)) {
    hist.push(...await sbAll("prices_daily", {
      select: "tcgplayer_product_id,printing,date,low_price,low_price_smoothed,market_price",
      source: "eq.tcgcsv", grade: "eq.raw", printing: "eq.Normal",
      tcgplayer_product_id: `in.(${ids.join(",")})`, date: "gte." + since,
      order: "tcgplayer_product_id.asc,date.asc",
    }));
  }
  const byPid = new Map(site.computeSealedDeltas(hist, { asOf: priceDate }).map((d) => [d.tcgplayer_product_id, d]));
  const W = [["1d", "1d"], ["1w", "7d"], ["1m", "30d"], ["3m", "90d"], ["6m", "180d"], ["1y", "365d"]];
  const pct = (v) => (v == null || !Number.isFinite(v) ? null : Math.round(v * 10) / 10);
  let withMoves = 0;
  for (const s of movers) {
    const d = byPid.get(s.pid);
    if (!d) continue;
    const out = {};
    for (const [k, col] of W) {
      const lo = pct(d["pct_" + col]), mk = pct(d["mkt_pct_" + col]);
      if (lo != null || mk != null) out[k] = [lo, mk];
    }
    if (Object.keys(out).length) { s.d = out; withMoves++; }
  }
  console.log(`  sealed movers: ${withMoves} of ${movers.length} candidates carry price changes (${hist.length} history rows)`);
}

// ── Art Discord can show ────────────────────────────────────────────────
// See bake_art.mjs. --no-art skips the download (a quick local build) and
// just drops the art Discord could not have shown anyway.
// wrangler.toml's [assets] directory must exist even then, or every deploy
// and `wrangler dev` refuses to start.
const artDir = fileURLToPath(new URL("../public/art/", import.meta.url));
if (process.argv.includes("--no-art")) {
  mkdirSync(artDir, { recursive: true });
  for (const c of identities) for (const p of c.p) if (p.img && !SAFE_IMG.test(p.img)) p.img = null;
} else {
  const art = await bakeArt(identities, artDir);
  console.log(`art: baked ${art.baked} of ${art.total} printings TCGplayer has no photo of`);
  for (const f of art.failed.slice(0, 10)) console.log(`::warning::card art not baked: ${f}`);
}

const inkColors = Object.fromEntries(Object.entries(site.INK_COLORS).map(([k, v]) => [k, v.border]));
const out = {
  v: 2,
  built: new Date().toISOString(),
  priceDate,
  playDecks,
  tcgNames: Object.fromEntries(tcgNames.map((r) => [String(r.product_id), r.name])),
  newestMain: site.MAINLINE_SETS[site.MAINLINE_SETS.length - 1],
  sets: setsOut,
  cards: identities,
  sealed: sealedOut,
  inkColors,
  rarityAliases: site.RARITY_ALIASES,
};
const json = JSON.stringify(out);
mkdirSync(new URL("../src/", import.meta.url), { recursive: true });
writeFileSync(OUT, json);
// The Worker imports src/command-ids.json (see src/index.js); registering the
// commands fills it in. Never overwrite a real one — only make sure it exists.
const IDS = new URL("../src/command-ids.json", import.meta.url);
if (!existsSync(IDS)) writeFileSync(IDS, "{}");
const played = identities.filter((i) => i.pl > 0).length;
console.log(`wrote ${OUT.pathname}: ${identities.length} cards (${played} played), ${sealedOut.length} sealed, `
  + `${(json.length / 1024).toFixed(0)} KB (skipped ${skipped} rows)`);

// A small committed subset for the offline guard test: every identity whose
// character name is one the test asks about, plus the sealed rows for two sets.
if (process.argv.includes("--fixture")) {
  const WANT = new Set(["Mowgli", "Elsa", "Stitch", "Mickey Mouse", "Tinker Bell", "Te Kā", "Rapunzel", "Cinderella",
    "Go Go Tomago", "Let It Go", "Be Prepared", "Tipo", "Peter Pan", "Genie", "Maleficent", "Hades", "Ariel",
    "Heart of Te Fiti", "A Whole New World", "Friends on the Other Side", "Moana", "Belle", "Gaston",
    "Cruella De Vil", "HeiHei", "Heihei", "Grandmother Willow", "Ursula", "Scar", "Flounder", "The Queen"]);
  const fxCards = identities.filter((i) => WANT.has(i.c));
  const fxPids = new Set(fxCards.flatMap((c) => c.p.flatMap((p) => p.f.map((f) => String(f[1])))));
  const fx = { ...out, cards: fxCards,
    sealed: sealedOut.filter((s) => s.sn === "Azurite Sea" || s.sn === out.newestMain),
    tcgNames: Object.fromEntries(Object.entries(out.tcgNames).filter(([pid]) => fxPids.has(pid))) };
  mkdirSync(new URL("../test/", import.meta.url), { recursive: true });
  writeFileSync(FIXTURE, JSON.stringify(fx));
  console.log(`wrote fixture: ${fx.cards.length} cards, ${fx.sealed.length} sealed`);
}
