// bake_art.mjs — card art Discord can show, for the printings that have none.
//
// A reply's picture is TCGplayer's photo of the product. A printing TCGplayer
// doesn't list (a set before its release, a regional promo) has no such photo,
// and the art we hold for it is Lorcast's AVIF or a data: URI — Discord shows
// neither, and an embed carrying a data: URI is rejected outright. Those are
// converted to WebP here, at deploy time, into public/art/, which wrangler
// ships as the Worker's static assets: a reply points at <worker>/art/<id>.webp.
// WebP because Discord shows it and it is about a third smaller than a JPEG of
// the same quality: 84 printings bake to ~4.4 MB. Lorcast's AVIFs carry no
// alpha (the corners are the card's own dark border), so nothing is lost.
import sharp from "sharp";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

// Formats Discord displays, on an absolute https URL.
export const SAFE_IMG = /^https:\/\/[^?#]+\.(?:jpe?g|png|webp|gif)(?:[?#].*)?$/i;
export const lorcastArt = (id) =>
  /^crd_[0-9a-f]{32}$/.test(id) ? `https://cards.lorcast.io/card/digital/large/${id}.avif` : null;
export const artFile = (id) =>
  String(id).toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") + ".webp";

// TCGplayer's photo (any finish with a product id) or art we already host in a
// Discord-safe format covers a printing; otherwise it needs baking, if there is
// a source to bake from at all.
export function needsBake(p) {
  if (p.img && SAFE_IMG.test(p.img)) return false;
  if ((p.f || []).some((f) => f[1])) return false;
  return !!((p.img && !SAFE_IMG.test(p.img)) || lorcastArt(p.id));
}

async function fetchBytes(url) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 20000);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return Buffer.from(await r.arrayBuffer());
  } finally { clearTimeout(t); }
}

// Rewrites p.img on every printing it bakes to "/art/<file>?v=<hash>" (the
// Worker adds its own origin), and to null where baking failed, so the index
// never carries a URL Discord cannot show. The hash busts Discord's image cache
// when Lorcast re-renders a card.
export async function bakeArt(identities, outDir, { concurrency = 6 } = {}) {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  const jobs = [];
  for (const c of identities) for (const p of c.p) if (needsBake(p)) jobs.push(p);
  const failed = [];
  let next = 0, baked = 0;
  const work = async () => {
    while (next < jobs.length) {
      const p = jobs[next++];
      const src = p.img && !SAFE_IMG.test(p.img) ? p.img : lorcastArt(p.id);
      try {
        const bytes = src.startsWith("data:")
          ? Buffer.from(src.slice(src.indexOf(",") + 1), "base64")
          : await fetchBytes(src);
        const out = await sharp(bytes).resize({ width: 488, withoutEnlargement: true }).webp({ quality: 82 }).toBuffer();
        const file = artFile(p.id);
        writeFileSync(join(outDir, file), out);
        p.img = `/art/${file}?v=${createHash("sha1").update(out).digest("hex").slice(0, 8)}`;
        baked++;
      } catch (e) {
        failed.push(`${p.id} (${String(src).slice(0, 60)}): ${e.message}`);
        p.img = null;
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, jobs.length) }, work));
  // Whatever is left unsafe (a printing with a product id carrying a stray AVIF
  // or data: URI) is dropped: the Worker derives TCGplayer's photo for those.
  for (const c of identities) for (const p of c.p) if (p.img && !SAFE_IMG.test(p.img) && !p.img.startsWith("/art/")) p.img = null;
  return { baked, failed, total: jobs.length };
}
