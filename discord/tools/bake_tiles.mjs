// bake_tiles.mjs — the site's card tile, drawn for every priced card, once a day.
//
// `/card` shows the same picture the site's card page shows at the top of the
// modal (and copies with its camera button): the card art, its name, Low /
// Market and the 1D / 1W / 1M changes, packs.ink and the date. The Worker has
// no canvas and ~10 ms of CPU, so it cannot draw one; this does, at deploy
// time, with the SITE'S OWN drawCardTileCanvas (pulled out of Index.html by
// sitecode.mjs) running on a Node canvas. Nothing about the tile is re-typed
// here: a change to the site's tile changes the bot's on the next deploy.
//
//   * One tile per priced FINISH (a card's non-foil and its foil are two
//     tiles), written to public/tile/<card file>-<finish>.webp, which wrangler
//     serves as a static asset without running the Worker.
//   * Prices and changes come from prices_daily through the site's own
//     computeSeriesDeltas, anchored on the index's price date — the same
//     numbers /card's text and the site's card page show.
//   * Colours are the site's default dark theme (velvet), read out of
//     styles.css so a theme retune reaches the bot too.
//   * The art is the site's art (Lorcast's render, or our own storage for a
//     prestaged card), cached between runs in .tile-art-cache/ so a daily
//     deploy downloads only new cards.
//   * ⚠ A tile that cannot be drawn is SKIPPED, never fatal: /card falls back
//     to the plain card picture it showed before tiles existed.
import { createCanvas, GlobalFonts, loadImage } from "@napi-rs/canvas";
import sharp from "sharp";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadSite } from "./sitecode.mjs";
import { lorcastArt } from "./bake_art.mjs";
import { tileFile } from "../src/tile.js";
import { tileJobs, needsLonger, tileMeta, tileDate, ymdBack, SHORT_DAYS, LONG_DAYS } from "./tile_rules.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const FONT_DIR = join(ROOT, "scripts", "fonts");
export const TILE_DIR = fileURLToPath(new URL("../public/tile/", import.meta.url));
export const ART_CACHE = fileURLToPath(new URL("../.tile-art-cache/", import.meta.url));
// The tile is drawn at the site's own SCALE 2 (600px wide), then saved at
// this width: Discord shows an embed image at most ~400px wide, so 600 is all
// detail nobody sees and half again the upload.
const OUT_WIDTH = 450;
// ⚠ Discord fits an embed image inside a ~400 x 300 box, so the site's
// portrait tile (1:2) came out 150 px wide — the card a thumbnail beside an
// empty half of the embed (Zaven, 2026-10-04: "make the card art tile much
// bigger"). A portrait card is therefore laid out WIDE for Discord: the art
// panel exactly as the site draws it on the left, and the tile's own info
// block (name, prices, changes, packs.ink · date) moved to its right, the
// whole thing 4:3 so it fills the box. Same pixels the site drew, rearranged.
const WIDE_RATIO = 4 / 3;
const WIDE_OUT_WIDTH = 720;
const TILE = { W: 300, PAD: 12, SCALE: 2 };
const WEBP_QUALITY = 82;
// The art box on the tile is 276 x 386 CSS px, drawn at 2x.
const ART_CACHE_WIDTH = 560;

export { tileFile, tileJobs, needsLonger, tileMeta, tileDate };

let fontsReady = false;
function registerFonts() {
  if (fontsReady) return;
  for (const [file, family] of [["Cinzel-Bold.ttf", "Cinzel"], ["NunitoSans-SemiBold.ttf", "Nunito Sans"],
    ["NunitoSans-Bold.ttf", "Nunito Sans"], ["NunitoSans-ExtraBold.ttf", "Nunito Sans"]]) {
    const ok = GlobalFonts.registerFromPath(join(FONT_DIR, file), family);
    if (!ok) throw new Error("could not register font " + file);
  }
  fontsReady = true;
}

// The velvet theme's colours, the way posterPalette() reads them in a browser.
export function velvetPalette(css = readFileSync(join(ROOT, "styles.css"), "utf8")) {
  const i = css.indexOf('html[data-theme="velvet"]');
  if (i < 0) throw new Error("styles.css has no velvet theme block");
  const block = css.slice(i, css.indexOf("}", i));
  const v = (name, fb) => {
    const m = block.match(new RegExp(`${name.replace(/-/g, "\\-")}\\s*:\\s*([^;]+);`));
    return m ? m[1].trim() : fb;
  };
  return {
    bg: v("--bg-modal", "#15131f"), surface: v("--bg-surface", "rgba(255,255,255,0.05)"),
    border: v("--border", "rgba(255,255,255,0.14)"), text: v("--text", "#f1ede4"),
    dim: v("--text-dim", "#bdb6aa"), muted: v("--text-muted", "#8d8678"),
    accent: v("--accent", "#c8a64e"), green: v("--green", "#27ae60"), red: v("--red", "#e05a3e"),
    normal: "#1d8d4a", foil: "#7e54c4",
  };
}

let _site = null;
export function siteTile() {
  if (_site) return _site;
  const palette = velvetPalette();
  _site = loadSite(["drawCardTileCanvas", "computeSeriesDeltas", "CARD_DELTA_WINDOWS", "roundRectPath"], {
    stop: ["posterPalette"],
    globals: { posterPalette: () => palette },
  });
  return _site;
}

// An image the site's drawImageCover can take: it reads naturalWidth/Height.
function asDrawable(img) {
  if (img.naturalWidth == null) Object.defineProperty(img, "naturalWidth", { value: img.width });
  if (img.naturalHeight == null) Object.defineProperty(img, "naturalHeight", { value: img.height });
  return img;
}

async function fetchBytes(url, timeout = 20000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return Buffer.from(await r.arrayBuffer());
  } finally { clearTimeout(t); }
}

// The art as a JPEG sized for the tile, from the cache or the network.
async function artBytes(src, localDir) {
  const key = createHash("sha1").update(src).digest("hex").slice(0, 20);
  const cached = join(ART_CACHE, key + ".jpg");
  if (existsSync(cached)) return readFileSync(cached);
  let raw;
  if (src.startsWith("/art/")) raw = readFileSync(join(localDir, src.slice(5).split("?")[0]));
  else raw = await fetchBytes(src);
  const jpg = await sharp(raw).resize({ width: ART_CACHE_WIDTH, withoutEnlargement: true })
    .flatten({ background: "#000000" }).jpeg({ quality: 90 }).toBuffer();
  mkdirSync(ART_CACHE, { recursive: true });
  // Written aside and renamed in, so a half-written file is never read back.
  const tmp = `${cached}.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`;
  writeFileSync(tmp, jpg);
  renameSync(tmp, cached);
  return jpg;
}

// The picture the site draws for a card: the art the index kept for it (our
// own storage, or a baked copy of Lorcast's), else Lorcast's render of the
// card id, else TCGplayer's photo.
export function tileArtSource(p) {
  if (p.img && !/^https:\/\/tcgplayer-cdn/.test(p.img)) return p.img;
  const lc = lorcastArt(String(p.id).split("::")[0]);
  if (lc) return lc;
  const pid = (p.f || []).map((f) => f[1]).find(Boolean);
  return pid ? `https://tcgplayer-cdn.tcgplayer.com/product/${pid}_in_1000x1000.jpg` : null;
}

// Draw one tile. Returns WebP bytes.
export async function drawTile({ name, meta, low, market, dateStr, art, logo, landscape = false }) {
  registerFonts();
  const site = siteTile();
  const tile = createCanvas(10, 10);
  const H = site.drawCardTileCanvas(tile, { artImg: art, logoImg: logo, name, meta, low, market, dateStr, landscape });
  const canvas = landscape ? tile : widen(tile, H, site);
  // Raw pixels straight into sharp: a PNG round trip cost ~135 ms a tile, all
  // of it compression thrown away a line later. sharp works off the main
  // thread, so the tiles overlap; effort 2 is twice as fast as the default
  // for the same size.
  const px = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
  return sharp(Buffer.from(px.data.buffer, px.data.byteOffset, px.data.byteLength),
    { raw: { width: canvas.width, height: canvas.height, channels: 4 } })
    .resize({ width: landscape ? OUT_WIDTH : WIDE_OUT_WIDTH }).webp({ quality: WEBP_QUALITY, effort: 2 }).toBuffer();
}

// The portrait tile rearranged 4:3 (see WIDE_RATIO). Every coordinate is the
// site's tile geometry in CSS px (drawCardTileCanvas: W 300, PAD 12, art
// 276 x 386, info from 12 px under the art), times its SCALE.
export function widen(tile, H, site) {
  const { W, PAD, SCALE: S } = TILE;
  const artW = W - PAD * 2, artH = Math.round(artW * 7 / 5);
  const LH = PAD + artH + PAD, LW = Math.round(LH * WIDE_RATIO);
  const out = createCanvas(LW * S, LH * S);
  const ctx = out.getContext("2d");
  const P = velvetPalette();
  ctx.scale(S, S);
  site.roundRectPath(ctx, 0.5, 0.5, LW - 1, LH - 1, 12);
  ctx.fillStyle = P.bg; ctx.fill();
  ctx.strokeStyle = P.border; ctx.lineWidth = 1; ctx.stroke();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  // The art panel, as drawn (its rounded corners are already clipped in).
  ctx.drawImage(tile, PAD * S, PAD * S, artW * S, artH * S, PAD * S, PAD * S, artW * S, artH * S);
  // The info block: everything under the art, inside the panel's border.
  const sx = 2, sy = PAD + artH + 4, sw = W - 4, sh = H - sy - 2;
  const dx0 = PAD + artW + 4, dw = LW - 2 - dx0;
  const k = Math.min(dw / sw, (LH - 4) / sh);
  const dh = sh * k, dy = (LH - dh) / 2;
  ctx.drawImage(tile, sx * S, sy * S, sw * S, sh * S, dx0 * S, dy * S, sw * k * S, dh * S);
  return out;
}

// fetchHistory(pids, since) -> prices_daily rows {tcgplayer_product_id,
// printing, date, low_price, market_price}, any order.
export async function tileHistory(jobs, priceDate, fetchHistory, log = console.log) {
  const byKey = new Map();
  const add = (rows) => {
    for (const r of rows) {
      const k = `${r.tcgplayer_product_id}|${r.printing}`;
      if (!byKey.has(k)) byKey.set(k, []);
      byKey.get(k).push(r);
    }
  };
  const pids = [...new Set(jobs.map((j) => j.pid))];
  add(await fetchHistory(pids, ymdBack(priceDate, SHORT_DAYS)));
  const sortAll = () => { for (const rows of byKey.values()) rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0)); };
  sortAll();
  const again = new Set();
  for (const j of jobs) {
    const f = j.p.f.find((x) => x[0] === j.code);
    if (needsLonger(byKey.get(`${j.pid}|${j.printing}`) || [], priceDate, [f[4], f[5]])) again.add(j.pid);
  }
  if (again.size) {
    for (const pid of again) for (const k of [...byKey.keys()]) if (k.startsWith(pid + "|")) byKey.delete(k);
    add(await fetchHistory([...again], ymdBack(priceDate, LONG_DAYS)));
    sortAll();
  }
  log(`  tile history: ${pids.length} products, ${again.size} needed a year of it`);
  return byKey;
}

// One tile per item, several at a time: the drawing itself is ~1 ms on this
// thread, the WebP encode is sharp's and runs on its own threads.
let _logo = null;
export async function drawItems(items, artDir, concurrency = 8) {
  registerFonts();
  siteTile();
  if (!_logo) _logo = asDrawable(await loadImage(readFileSync(join(ROOT, "Logos", "packs-ink-logo.png"))));
  const done = [], failed = [];
  let next = 0;
  const work = async () => {
    while (next < items.length) {
      const it = items[next++];
      try {
        const art = asDrawable(await loadImage(await artBytes(it.src, artDir)));
        const webp = await drawTile({ name: it.name, meta: it.meta, low: it.low, market: it.market,
          dateStr: it.dateStr, landscape: it.landscape, art, logo: _logo });
        writeFileSync(join(TILE_DIR, it.file), webp);
        done.push(it.i);
      } catch (e) {
        failed.push(`${it.label}: ${String(e.message || e).slice(0, 120)}`);
      }
    }
  };
  await Promise.all(Array.from({ length: concurrency }, work));
  return { done, failed };
}

// Draws every tile into public/tile/ (cleared first, so a card that lost its
// price loses its tile) and sets p.tl = the finish codes that have one.
// Returns {drawn, total, failed[]}.
export async function bakeTiles(identities, { priceDate, fetchHistory, artDir, log = console.log }) {
  rmSync(TILE_DIR, { recursive: true, force: true });
  mkdirSync(TILE_DIR, { recursive: true });
  const site = siteTile();
  const jobs = tileJobs(identities);
  const history = await tileHistory(jobs, priceDate, fetchHistory, log);
  const dateStr = tileDate(priceDate);
  const items = [];
  jobs.forEach((j, i) => {
    const rows = history.get(`${j.pid}|${j.printing}`) || [];
    if (!rows.length) return;
    const low = site.computeSeriesDeltas(rows, "low_price", priceDate);
    const market = site.computeSeriesDeltas(rows, "market_price", priceDate);
    if (low.now == null && market.now == null) return;
    const src = tileArtSource(j.p);
    if (!src) return;
    items.push({ i, src, file: tileFile(j.p.id, j.code), label: `${j.c.n} [${j.code}]`,
      name: j.c.n, meta: tileMeta(j.p.r, j.badge), low, market, dateStr, landscape: /Location/.test(j.c.t || "") });
  });
  const t0 = Date.now();
  const { done, failed } = await drawItems(items, artDir);
  const tl = new Map();
  let drawn = 0;
  for (const i of done.sort((a, b) => a - b)) {
    const j = jobs[i];
    tl.set(j.p, (tl.get(j.p) || "") + j.code);
    drawn++;
  }
  for (const [p, codes] of tl) p.tl = codes;
  log(`tiles: drew ${drawn} of ${jobs.length} priced finishes in ${((Date.now() - t0) / 1000).toFixed(0)}s`
    + (failed.length ? `, ${failed.length} failed` : ""));
  return { drawn, total: jobs.length, failed };
}
