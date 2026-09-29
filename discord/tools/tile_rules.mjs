// tile_rules.mjs — the pure half of bake_tiles.mjs: which finishes get a
// tile, how much price history each needs, and the words drawn on it. Kept
// apart from the drawing (which needs a native canvas) so the offline guard,
// scripts/test_discord_bot.mjs, can check it with nothing installed.

// "2026-09-28" -> "Sep 28, 2026", the site's toLocaleDateString in en-US.
export function tileDate(ymd) {
  const d = new Date(String(ymd).slice(0, 10) + "T12:00:00Z");
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

// meta: "Super Rare", "Rare · Foil", "Promo · Top Prize" — the finish word only
// where the site's printingBadge says the card has one to name.
export const tileMeta = (rarity, badge) => (rarity || "") + (badge ? " · " + badge : "");

// Which finishes get a tile: a TCGplayer listing of its own (a named variant
// with no SKU shows no price on the site either), a price to show, and a card
// whose price IS TCGplayer's. A promo on the raw-eBay watchlist leads with its
// eBay sales everywhere, so a tile announcing TCGplayer's fossil there would
// contradict the reply it sits in; those keep the plain card picture.
export function tileJobs(identities) {
  const jobs = [];
  for (const c of identities) {
    for (const p of c.p) {
      delete p.tl;
      if (p.raw) continue;
      for (const f of p.f || []) {
        const [code, pid, printing, badge, low, mkt, noListing] = f;
        if (!pid || noListing || (low == null && mkt == null)) continue;
        jobs.push({ c, p, code, pid, printing, badge });
      }
    }
  }
  return jobs;
}

const DAY = 86400000;
export const ymdBack = (ymd, days) => new Date(Date.parse(ymd + "T00:00:00Z") - days * DAY).toISOString().slice(0, 10);

// Enough history for computeSeriesDeltas to answer 1D / 1W / 1M exactly as the
// site's card page does. A daily series needs a little over a month; a series
// with holes (a card nobody listed for weeks) can need its 1M reference, or
// its latest price, from further back, so those are fetched again over a year.
export const SHORT_DAYS = 45, LONG_DAYS = 400;
export function needsLonger(rows, priceDate, catalog) {
  const cut = Date.parse(ymdBack(priceDate, 30) + "T00:00:00Z");
  for (const [field, have] of [["low_price", catalog[0]], ["market_price", catalog[1]]]) {
    if (have == null) continue;
    const seen = rows.filter((r) => r[field] != null && Number.isFinite(parseFloat(r[field])));
    if (!seen.length || Date.parse(seen[0].date) > cut) return true;
  }
  return false;
}

