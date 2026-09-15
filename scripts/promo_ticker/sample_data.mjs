/* Sample price_movers rows for the promo videos.
 *
 * The recorder normally plays the REAL ticker against the REAL Supabase feed
 * (`--live`). This module exists for the offline case: the agent sandbox has no
 * egress to Supabase or to the card-art CDN, so the video would otherwise record
 * a bar reading "couldn't load prices".
 *
 * ⚠ The numbers here are SAMPLE numbers, not a snapshot of any real market day.
 * The card NAMES / VERSIONS / RARITIES are real — read out of the scanner index
 * that already ships in this repo — so the bar renders the same shapes it will
 * in production (long names, version subtitles, the chase-rarity foil rule).
 * Nothing in the videos dates the numbers or calls them today's prices.
 *
 * Deterministic: same seed in, same rows out, so a re-record is byte-comparable.
 */
import fs from "node:fs";
import path from "node:path";

const mulberry32 = (a) => () => {
  a |= 0; a = (a + 0x6D2B79F5) | 0;
  let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

/* Price + move bands per rarity. Chosen to look like a real board: Iconics are
 * the four-figure end, Rares are the $5 floor the ticker defaults to. */
const BANDS = {
  Iconic:       {px: [150, 780], pct1d: [3.0, 19], pct1w: [7, 46]},
  Enchanted:    {px: [32, 340],  pct1d: [2.4, 24], pct1w: [6, 58]},
  Epic:         {px: [18, 130],  pct1d: [2.6, 21], pct1w: [6, 49]},
  Legendary:    {px: [11, 58],   pct1d: [2.2, 17], pct1w: [5, 38]},
  "Super Rare": {px: [6, 26],    pct1d: [2.0, 15], pct1w: [4.5, 33]},
  Rare:         {px: [5, 15],    pct1d: [1.8, 13], pct1w: [4, 27]},
};

const between = (rnd, [lo, hi]) => lo + rnd() * (hi - lo);
/* Skew toward the cheap end so a section isn't all four-figure cards. */
const skewed = (rnd, [lo, hi]) => lo + Math.pow(rnd(), 1.9) * (hi - lo);

export function loadCardPool(repoRoot) {
  const idx = JSON.parse(fs.readFileSync(path.join(repoRoot, "scanner", "index.json"), "utf8"));
  return idx.cards.filter((c) => BANDS[c.rarity] && c.name && c.version);
}

/* One section's worth of rows, ranked biggest move first — the same ordering
 * PostgREST applies server-side, so the bar receives what it expects. */
export function sampleRows({pool, rarities, window: win, limit, seed}) {
  const rnd = mulberry32(seed);
  const eligible = pool.filter((c) => rarities.includes(c.rarity));
  // Deterministic shuffle, then take the head — different seeds per section
  // mean the four sections in the reel don't repeat the same cards.
  const picked = eligible
    .map((c) => ({c, k: rnd()}))
    .sort((a, b) => a.k - b.k)
    .slice(0, limit)
    .map(({c}) => c);

  return picked
    .map((c) => {
      const band = BANDS[c.rarity];
      const px = skewed(rnd, band.px);
      const pct = between(rnd, win === "1d" ? band.pct1d : band.pct1w);
      // Chase rarities exist in one printing and are cold foil by definition;
      // base rarities split, and tickerRarityLine only says "· Foil" for those.
      const chase = ["Enchanted", "Epic", "Iconic", "Promo"].includes(c.rarity);
      return {
        card_id: c.id,
        name: c.name,
        version: c.version,
        rarity: c.rarity,
        printing: chase ? "Cold Foil" : rnd() < 0.42 ? "Cold Foil" : "Normal",
        image_small: null,
        price: px < 100 ? Math.round(px * 100) / 100 : Math.round(px),
        pct: Math.round(pct * 10) / 10,
      };
    })
    .sort((a, b) => b.pct - a.pct);
}
