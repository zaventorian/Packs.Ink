// The card tile a /card reply shows: the site's own tile (card art, name,
// rarity, Low / Market and the 1D / 1W / 1M changes, packs.ink and the date),
// drawn once a day for every priced finish by tools/bake_tiles.mjs and served
// as a static asset. One naming rule for both sides, so the file the build
// writes is the file the Worker asks for.

export const tileFile = (id, code) =>
  String(id).toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") + "-" + String(code).toLowerCase() + ".webp";

// The tile for one finish of a printing, or null when none was drawn (the
// reply then shows the card picture it always did). ?d= is the price date:
// Discord caches an image by its URL, and every tile changes daily.
export function tileUrl(printing, code, origin, date) {
  if (!origin || !code || !printing || !printing.tl || !printing.tl.includes(code)) return null;
  return `${origin}/tile/${tileFile(printing.id, code)}${date ? "?d=" + encodeURIComponent(date) : ""}`;
}
