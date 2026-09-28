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

// ── movers ───────────────────────────────────────────────────────────────
export const MOVER_WINDOWS = {
  "1d": { col: "1d", prior: "prev", label: "1D" }, "1w": { col: "7d", prior: "7d", label: "1W" },
  "1m": { col: "30d", prior: "30d", label: "1M" }, "3m": { col: "90d", prior: "90d", label: "3M" },
  "6m": { col: "180d", prior: "180d", label: "6M" }, "1y": { col: "365d", prior: "365d", label: "1Y" },
};
export const MOVER_GROUPS = {
  all: { label: "All rarities", rarities: null },
  chase: { label: "Chase (Enchanted / Epic / Iconic)", rarities: ["Enchanted", "Epic", "Iconic"] },
  rareleg: { label: "Rare – Legendary", rarities: ["Rare", "Super Rare", "Legendary"] },
  promo: { label: "Promos", rarities: ["Promo"] },
  sealed: { label: "Sealed product (boxes, troves, gift sets)", sealed: true },
};

// Sealed movers need no query: the index build runs the site's
// computeSealedDeltas over a year of history each day (see build_index.mjs),
// and the candidates are the site's Sealed Movers row — boxes, troves and
// specials, never packs or cases. Same floor as the cards: the price a product
// STARTED the window at.
export function sealedMovers(index, { win = "1d", dir = "up", basis = "market", min = 5, limit = 10 } = {}) {
  const at = basis === "low" ? 0 : 1;
  const rows = [];
  for (const s of index.sealed || []) {
    const d = s.d && s.d[win];
    const pctv = d ? d[at] : null;
    const now = basis === "low" ? s.low : s.mkt;
    if (pctv == null || !Number.isFinite(pctv) || pctv === 0 || now == null) continue;
    if (dir === "down" ? pctv > 0 : pctv < 0) continue;
    const prior = now / (1 + pctv / 100);
    if (!(prior >= Number(min || 0))) continue;
    rows.push({ s, pct: pctv, now, prior });
  }
  rows.sort((a, b) => (dir === "down" ? a.pct - b.pct : b.pct - a.pct));
  return { latest: index.priceDate, rows: rows.slice(0, limit), sealed: true };
}

// ⚠ price_movers carries a SKU's LAST change forever: when a listing drops out,
// low_prev is "the Low before the last Low we saw", so an old move keeps being
// reported as today's 1D. A mover only counts when prices_daily has a row for
// it on the newest price date carrying the same value the matview calls
// "today" — checked in one query against the candidates, not the catalog.
export async function fetchMovers(db, { win = "1d", dir = "up", group = "all", basis = "low", min = 5, limit = 10 } = {}) {
  const w = MOVER_WINDOWS[win] || MOVER_WINDOWS["1d"];
  const g = MOVER_GROUPS[group] || MOVER_GROUPS.all;
  const pre = basis === "market" ? "mkt_pct_" : "pct_";
  const col = pre + w.col;
  const todayCol = basis === "market" ? "market_today" : "low_today";
  const priorCol = (basis === "market" ? "market_" : "low_") + w.prior;
  const params = {
    select: `card_id,name,version,rarity,printing,tcgplayer_product_id,image_normal,${todayCol},${priorCol},${col}`,
    [col]: dir === "down" ? "lt.0" : "gt.0",
    // The floor is on the price the card STARTED the window at — the home
    // banners' rule. On today's price a 10-cent card that became $22 leads
    // every board.
    [priorCol]: "gte." + Number(min || 0),
    order: `${col}.${dir === "down" ? "asc" : "desc"}`,
    limit: Math.max(limit * 4, 40),
  };
  if (g.rarities) params.rarity = `in.(${g.rarities.map((r) => `"${r}"`).join(",")})`;
  const [latest, rows] = await Promise.all([latestPriceDate(db), db.get("price_movers", params)]);
  if (!rows || !rows.length || !latest) return { latest, rows: [] };
  const pids = [...new Set(rows.map((r) => r.tcgplayer_product_id).filter(Boolean))];
  const today = await db.all("prices_daily", {
    select: "tcgplayer_product_id,printing,low_price,market_price",
    source: "eq.tcgcsv", grade: "eq.raw", date: "eq." + latest,
    tcgplayer_product_id: `in.(${pids.join(",")})`,
    order: "tcgplayer_product_id.asc,printing.asc",
  });
  const field = basis === "market" ? "market_price" : "low_price";
  const live = new Map(today.map((r) => [r.tcgplayer_product_id + "|" + r.printing, r[field]]));
  const fresh = rows.filter((r) => {
    const v = live.get(r.tcgplayer_product_id + "|" + r.printing);
    return v != null && Math.abs(Number(v) - Number(r[todayCol])) < 0.005;
  });
  return { latest, rows: fresh.slice(0, limit), col, todayCol, priorCol, dropped: rows.length - fresh.length };
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
