// data.js — what the bot asks the database, shaped the way the site shapes it.
import {
  computeSeriesDeltas, priceStanding, seriesPricedOn, gradedSlotBucket, rawSaleMatch,
  calendarMergeEvents, calendarSetEntries, calendarEstimatedSetEntries, calendarSetEstimates,
  calendarProductEntries, calendarUpcoming, SET_RELEASE_DATES, UPCOMING_SET_NAMES,
  PRODUCT_RELEASE_DATES, calTodayYmd, calAddDays, calRegionOf,
  scPostalCandidates, scNormalizePostal, scZippo, scRankPlaces,
} from "./site.generated.js";

export const FIN_PRINTING = { N: "Normal", C: "Cold Foil", H: "Holofoil", F: "Foil" };
export const RANGES = { "1m": { days: 30, label: "1M" }, "3m": { days: 90, label: "3M" },
  "6m": { days: 180, label: "6M" }, "1y": { days: 365, label: "1Y" }, "all": { days: null, label: "All" } };
export const DEFAULT_RANGE = "3m";
const DAY = 86400000;
const ymd = (ms) => new Date(ms).toISOString().slice(0, 10);

// ── prices ────────────────────────────────────────────────────────────────
export async function latestPriceDate(db) {
  const rows = await db.get("card_prices_latest", { select: "price_date", order: "price_date.desc", limit: 1 });
  return rows && rows[0] ? String(rows[0].price_date).slice(0, 10) : null;
}

// The same query the site's fetchCardHistory runs (source=tcgcsv, grade=raw),
// bounded to what is actually needed: a year and a bit covers every delta
// window and the 12-month price standing; "all" asks for everything.
export async function priceHistory(db, pid, printing, { sinceDays = 400 } = {}) {
  if (!pid) return [];
  const params = {
    select: "date,low_price,market_price",
    source: "eq.tcgcsv", grade: "eq.raw",
    tcgplayer_product_id: "eq." + pid, printing: "eq." + printing,
    order: "date.asc",
  };
  if (sinceDays) params.date = "gte." + ymd(Date.now() - sinceDays * DAY);
  return db.all("prices_daily", params);
}

// Everything the card view says about a price, from one history fetch.
// asOf is the card index's price date — the newest day the catalog was built
// from, the bot's copy of the site's catalogPriceDate(). With it a printing
// that stopped being listed gets no move for a window that doesn't contain its
// last price (migration 172's rule), where it used to report the last change it
// ever had as today's; and no "Cheapest in 12 months" for a price nobody can
// buy today. The site's card page does exactly this.
export function priceSummary(rows, asOf) {
  const mkt = computeSeriesDeltas(rows, "market_price", asOf);
  const low = computeSeriesDeltas(rows, "low_price", asOf);
  const last = rows.length ? rows[rows.length - 1] : null;
  return {
    date: last ? String(last.date).slice(0, 10) : null,
    market: mkt.now, low: low.now,
    mktDelta: mkt.byWin, lowDelta: low.byWin,
    standing: seriesPricedOn(rows, "market_price", asOf) ? priceStanding(rows) : null,
  };
}

// ── graded + raw eBay sales ──────────────────────────────────────────────
// A named variant (Text Error, Two Swords) is a PRINTING of the base card on
// the graded side, never a card_id of its own — see CLAUDE.md "A named VARIANT
// is a printing, not a card_id".
export function gradedTarget(printing, finish) {
  const id = String(printing.id);
  const cut = id.indexOf("::variant::");
  if (cut > 0) {
    return { cardId: id.slice(0, cut), bucket: gradedSlotBucket(String(printing.var || "").replace(/\s+variant$/i, "")) };
  }
  return { cardId: id, bucket: gradedSlotBucket(FIN_PRINTING[finish] || "Normal") };
}

export async function gradedRollup(db, cardId) {
  return db.get("graded_sales_rollup", {
    select: "card_id,printing,grader,grade,last_sold_price,avg_last_5,sale_count,last_sold_date",
    card_id: "eq." + cardId,
    order: "grader.asc,grade.desc,printing.asc",
  });
}

// The rollup rows that describe THIS printing. One bucket ("") means the card
// has no printing axis; otherwise only the matching bucket counts — a Top
// Prize foil and a Prize Wall non-foil are two markets ~50x apart, and
// "Unknown" can never be read as either.
export function gradedRowsFor(rows, bucket) {
  const list = (rows || []).filter((r) => r.last_sold_price != null);
  if (!list.length) return [];
  if (list.some((r) => !r.printing)) return list.filter((r) => !r.printing);
  return bucket ? list.filter((r) => gradedSlotBucket(r.printing) === bucket) : [];
}

const GRADER_RANK = { PSA: 0, BGS: 1, CGC: 2, TAG: 3, SGC: 4, ACE: 5 };
export function topGradedTiers(rows, n = 4) {
  return rows.slice().sort((a, b) =>
    (b.sale_count || 0) - (a.sale_count || 0) ||
    (GRADER_RANK[a.grader] ?? 9) - (GRADER_RANK[b.grader] ?? 9) ||
    Number(b.grade) - Number(a.grade)).slice(0, n)
    .sort((a, b) => (GRADER_RANK[a.grader] ?? 9) - (GRADER_RANK[b.grader] ?? 9) || Number(b.grade) - Number(a.grade));
}

export async function gradedSales(db, cardId, grader, grade) {
  return db.all("graded_sales", {
    select: "sold_date,sale_price,printing",
    card_id: "eq." + cardId, grader: "eq." + grader, grade: "eq." + grade,
    excluded: "is.false", order: "sold_date.asc,item_id.asc",
  });
}

export async function rawRollup(db, cardId) {
  return db.get("raw_sales_rollup", {
    select: "card_id,printing,sale_count,last_sold_date,last_sold_price,avg_last_5,last_5_count",
    card_id: "eq." + cardId,
  });
}
export const rawRowFor = (rows, printingStr) => rawSaleMatch(rows, printingStr);

// ⚠ excluded=is.false is not optional: the table KEEPS every row it rejected
// (a slab, a pin, a poster), and plotting them would put a $16,406 PSA 10 and
// an $8 pin on one card's chart. Same filter as the site's fetchRawSales.
export async function rawSales(db, cardId) {
  return db.all("raw_sales", {
    select: "sold_date,sale_price,printing",
    card_id: "eq." + cardId, excluded: "is.false",
    order: "sold_date.asc,item_id.asc",
  });
}

// ── the meta ─────────────────────────────────────────────────────────────
// Every top-8 deck since the newest booster set reached stores, grouped by INK
// PAIR. deck_name is empty on most tournament decks (nobody names an archetype
// the same way twice), and the inks are exact. One read covers both halves of
// /meta: the breakdown and the pick of recent events.
export const META_TOP = 8;
export const META_MIN_EVENTS = 3;      // fewer than this since the set: widen
export const META_FALLBACK_DAYS = 45;
export const META_RECENT_DAYS = 21;    // "latest big events" look back this far
export const META_EVENTS = 3;
export const META_EVENT_MIN_DECKS = 4; // an event with fewer recorded is a stub
const INK_ORDER = ["Amber", "Amethyst", "Emerald", "Ruby", "Sapphire", "Steel"];

// The newest booster set already on shelves (a set with a future date is only
// announced, and its window would be empty).
export function metaSet(sets, today) {
  let best = null;
  for (const s of sets || []) if (s.main && s.date && s.date <= today && (!best || s.date > best.date)) best = s;
  return best;
}

export async function fetchMetaRows(db, { since }) {
  return db.all("tournament_results_v", {
    select: "tournament_id,tournament_name,event_date,tournament_format,num_players,place,place_rank,player_name,deck_id,deck_name,deck_inks,deck_share_token,deck_visibility",
    event_date: "gte." + since, place_rank: "lte." + META_TOP,
    order: "event_date.desc,tournament_id.asc,place_rank.asc,player_name.asc",
  }, { maxRows: 4000 });
}

export function metaSince(sets, today) {
  const s = metaSet(sets, today);
  const back = calAddDays(today, -META_FALLBACK_DAYS);
  return s && s.date < back ? s.date : back;
}

// The whole /meta read. A failed read is an empty meta, not a failed reply:
// the most-played list comes from the index and still has something to say.
export async function fetchMeta(db, sets, { today = calTodayYmd(), log } = {}) {
  const rows = await fetchMetaRows(db, { since: metaSince(sets, today) })
    .catch((e) => { log && log("meta read failed", e && e.message); return []; });
  return buildMeta(rows, { sets, today });
}

export function buildMeta(rows, { sets, today }) {
  const byId = new Map();
  for (const r of rows || []) {
    if (!r || !r.tournament_id) continue;
    let e = byId.get(r.tournament_id);
    if (!e) byId.set(r.tournament_id, e = {
      id: r.tournament_id, name: r.tournament_name || "Tournament", date: String(r.event_date || "").slice(0, 10),
      format: r.tournament_format || null, players: r.num_players || null, top: [],
    });
    e.top.push(r);
  }
  const events = [...byId.values()];
  for (const e of events) e.top.sort((a, b) => (a.place_rank || 99) - (b.place_rank || 99));

  // The breakdown: Core only (Infinity is a different game), since the set.
  const set = metaSet(sets, today);
  const core = (from) => events.filter((e) => e.format === "core" && e.date >= from);
  let from = set ? set.date : null, sinceSet = set ? set.n : null;
  let pool = from ? core(from) : [];
  if (pool.length < META_MIN_EVENTS) {
    from = calAddDays(today, -META_FALLBACK_DAYS); sinceSet = null; pool = core(from);
  }
  const pairs = new Map();
  let decks = 0;
  for (const e of pool) for (const r of e.top) {
    const inks = [...new Set((r.deck_inks || []).filter(Boolean))]
      .sort((a, b) => INK_ORDER.indexOf(a) - INK_ORDER.indexOf(b));
    if (!inks.length) continue;
    const key = inks.join("/");
    let p = pairs.get(key);
    if (!p) pairs.set(key, p = { key, inks, n: 0, t4: 0, wins: 0 });
    p.n++; decks++;
    if (r.place_rank <= 4) p.t4++;
    if (r.place_rank === 1) p.wins++;
  }
  const breakdown = [...pairs.values()].sort((a, b) => b.n - a.n || b.wins - a.wins || (a.key < b.key ? -1 : 1));

  // Latest big events: the biggest few of the last three weeks, shown newest
  // first. An event with only a winner recorded says nothing about a meta.
  const full = events.filter((e) => e.top.length >= META_EVENT_MIN_DECKS);
  let cands = full.filter((e) => e.date >= calAddDays(today, -META_RECENT_DAYS));
  if (cands.length < META_EVENTS) cands = full.filter((e) => e.date >= calAddDays(today, -META_FALLBACK_DAYS));
  const recent = cands.sort((a, b) => (b.players || 0) - (a.players || 0) || (a.date < b.date ? 1 : -1))
    .slice(0, META_EVENTS).sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));

  return { from, sinceSet, events: pool.length, decks, breakdown, recent };
}

// ── events near a place ──────────────────────────────────────────────────
// The site's own walk: postal code first (zippopotam, with the site's per-
// country normalisation), then a town we actually hold events in.
export async function resolvePlace(db, query, home = "US") {
  const raw = String(query || "").trim();
  if (!raw) return null;
  const cands = scPostalCandidates(raw, home);
  if (cands && cands.length) {
    for (const cc of cands) {
      const code = scNormalizePostal(raw, cc);
      if (!code) continue;
      const hit = await scZippo(cc, code);
      if (hit) return hit;
    }
  }
  // "elgin il" / "Elgin, IL": a trailing two-letter code is the state or
  // province, which is the only way to say WHICH Elgin — there are several,
  // and on the name alone the pick is whichever sorts first.
  const m = /^(.*?)[,\s]+([A-Za-z]{2})$/.exec(raw);
  const town = m && m[1].trim().length >= 2 ? m[1].trim() : raw;
  const st = m && m[1].trim().length >= 2 ? m[2].toUpperCase() : null;
  const rows = await db.get("lorcana_events", {
    select: "city,state,country,latitude,longitude",
    city: "ilike." + town.replace(/[%_*,]/g, "") + "%",
    latitude: "not.is.null", order: "city.asc", limit: 400,
  }).catch(() => []);
  // …or a country: "london gb" is not London, Kentucky.
  const inState = st ? (rows || []).filter((r) => String(r.state || "").toUpperCase() === st
    || String(r.country || "").toUpperCase() === st) : [];
  const places = scRankPlaces(inState.length ? inState : rows || [], town, home);
  return places[0] || null;
}

export async function nearbyEvents(db, place, { radius = 50, kind = null, maxSeries = 60, maxOcc = 4 } = {}) {
  return db.rpc("get_nearby_lorcana_events", {
    p_lat: place.lat, p_lng: place.lng, p_radius_mi: radius,
    p_kind: kind && kind !== "all" ? kind : null, p_max_series: maxSeries, p_max_occurrences: maxOcc,
  });
}

// ⚠ One query PER KIND, never one query for everything. The RPC returns the
// soonest series first, capped — so in a busy metro "everything" is sixty
// weekly league nights and the Set Championship three weeks out never makes
// the list, which is the one event the person asking most wanted. One
// occurrence per series: the next date is all a list needs, and each
// occurrence carries a description of up to 1,000 characters.
export const EVENT_KINDS = ["sc", "prerelease", "other"];
export async function nearbyByKind(db, place, { radius = 50, kind = "all" } = {}) {
  const want = kind === "all" ? EVENT_KINDS : EVENT_KINDS.filter((k) => k === kind);
  const out = { sc: [], prerelease: [], other: [] };
  const got = await Promise.all(want.map((k) => nearbyEvents(db, place, {
    radius, kind: k, maxSeries: k === "other" ? 40 : 15, maxOcc: 1,
  }).then((rows) => [k, rows || []], () => [k, null])));
  for (const [k, rows] of got) out[k] = rows;
  return out;
}

// ── the release + competitive calendar ───────────────────────────────────
const CAL_COLS = "id,kind,title,subtitle,starts_on,ends_on,location,url,set_name,country";
export async function calendarEvents(db) {
  let rows = [];
  try {
    rows = await db.get("calendar_events", {
      select: CAL_COLS, confirmed: "eq.true",
      starts_on: "gte." + calAddDays(calTodayYmd(), -7),
      order: "starts_on.asc", limit: 500,
    });
  } catch { rows = []; }
  const derived = [
    ...calendarSetEntries(SET_RELEASE_DATES),
    ...calendarEstimatedSetEntries(calendarSetEstimates(SET_RELEASE_DATES, UPCOMING_SET_NAMES)),
    ...calendarProductEntries(PRODUCT_RELEASE_DATES),
  ];
  return calendarMergeEvents(derived, rows || []);
}
export const upcoming = (events, n) => calendarUpcoming(events, calTodayYmd(), n);

// /calendar's filters. A set or product release is in no place — it comes
// out everywhere — so a region filter never drops one (the site's
// calRegionless rule); it narrows the Challenges and qualifiers.
export const CAL_FILTERS = { all: null, release: ["set", "product"], dlc: ["dlc"], ccq: ["ccq"] };
export function upcomingFiltered(events, { kind = "all", region = "all", n = 12 } = {}) {
  const kinds = CAL_FILTERS[kind] || null;
  const list = (events || []).filter((e) => (!kinds || kinds.includes(e.kind)) &&
    (region === "all" || e.kind === "set" || e.kind === "product" || calRegionOf(e.country) === region));
  return calendarUpcoming(list, calTodayYmd(), n);
}
