/* Record the stream-ticker promo videos — one 16:9 for desktop feeds, one 9:16
 * for phones. Both frame the REAL /ticker?bar=1 page in an iframe sized like an
 * OBS browser source; nothing about the bar is re-implemented here.
 *
 *   node scripts/promo_ticker/record_promo.mjs [--live] [--fonts <dir>] [--out <dir>]
 *                                       [--only desktop|mobile] [--fps 30]
 *
 * Every frame is produced by seeking the scene to an exact time and taking a
 * screenshot, so output is deterministic and drops no frames — unlike
 * real-time capture. The ticker's own marquee is seeked through the Web
 * Animations API by the scene's __seek().
 *
 * --live       hit the real Supabase feed and show real card art. Needs egress
 *              to supabase.co AND to the card-art CDN; without it the run uses
 *              the sample rows in sample_data.mjs and turns thumbnails off,
 *              because inventing card art for a promo would misrepresent it.
 * --fonts DIR  serve Google Fonts from a local cache (see fetch_fonts.sh) for
 *              machines with no egress to fonts.googleapis.com.
 */
import { chromium } from "playwright-core";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadCardPool, sampleRows } from "./sample_data.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");

/* ── args ── */
const argv = process.argv.slice(2);
const flag = (n) => argv.includes("--" + n);
const opt = (n, d) => { const i = argv.indexOf("--" + n); return i >= 0 ? argv[i + 1] : d; };
const LIVE = flag("live");
const FONT_DIR = opt("fonts", "");
const OUT_DIR = path.resolve(opt("out", path.join(ROOT, "promo")));
const ONLY = opt("only", "");
const FPS = parseInt(opt("fps", "30"), 10);
const DURATION = parseFloat(opt("dur", "30"));
/* A fresh random port per run: scripts/dev_server.py uses ThreadingTCPServer
 * without allow_reuse_address, so re-binding the same port right after a
 * previous run dies on the socket's TIME_WAIT. */
let PORT = parseInt(opt("port", "0"), 10) || 8800 + Math.floor(Math.random() * 900);
/* --stills 1,5,11 writes PNG frames at those seconds instead of encoding a
 * video: the fast way to iterate on the layout, and a cheap way to pull a
 * poster frame / thumbnail out of a finished cut. */
const STILLS = (opt("stills", "") || "").split(",").map((s) => parseFloat(s)).filter(Number.isFinite);
let ORIGIN = `http://localhost:${PORT}`;
/* The sandbox ships Chromium at a fixed path; anywhere else, let playwright
 * resolve its own download rather than pointing at a path that doesn't exist. */
const CHROME = process.env.PROMO_CHROME || "/opt/pw-browsers/chromium";
const FFMPEG = process.env.PROMO_FFMPEG || "ffmpeg";

const SB_HOST = "umwqowkiatjjltologrd.supabase.co";
/* The ticker config the videos advertise: two windows × two rarity groups,
 * risers, NM Market basis. Matches what packs.ink/ticker hands you by default
 * apart from the count, which is tuned so the loop reads well on video. */
const TICKER_PARAMS = new URLSearchParams({
  bar: "1", w: "1d,1w", g: "chase,rareleg", n: "12", min: "5", speed: "62",
});
if (!LIVE) TICKER_PARAMS.set("img", "0");

const FORMATS = [
  { key: "desktop", w: 1920, h: 1080, file: "stream-ticker-desktop.mp4" },
  { key: "mobile", w: 1080, h: 1920, file: "stream-ticker-mobile.mp4" },
].filter((f) => !ONLY || f.key === ONLY);

const log = (...a) => console.log("[promo]", ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ── the dev server (serves /ticker, styles.css, Logos/…) ── */
function spawnServer(port) {
  const proc = spawn("python3", [path.join(ROOT, "scripts", "dev_server.py"), String(port)], {
    cwd: ROOT, stdio: ["ignore", "ignore", "pipe"],
  });
  let err = "";
  proc.stderr.on("data", (d) => { err += d.toString(); });
  proc.on("error", () => {});
  return { proc, err: () => err };
}
async function reachable(origin) {
  try {
    const r = await fetch(`${origin}/ticker`);
    return r.ok;
  } catch { return false; }
}
/* Returns the live child process, having proved it actually answers. */
async function startDevServer() {
  let lastErr = "";
  for (let attempt = 0; attempt < 5; attempt++) {
    const port = attempt === 0 ? PORT : 8800 + Math.floor(Math.random() * 900);
    const { proc, err } = spawnServer(port);
    for (let i = 0; i < 40; i++) {
      if (proc.exitCode !== null) break;
      if (await reachable(`http://localhost:${port}`)) {
        PORT = port;
        ORIGIN = `http://localhost:${port}`;
        return proc;
      }
      await sleep(200);
    }
    lastErr = err();
    proc.kill("SIGKILL");
  }
  throw new Error(`dev server never came up.\n${lastErr}`);
}

/* ── sample-data route ─────────────────────────────────────────────────────
 * Answers the exact PostgREST query buildTickerPlan() emits, so the page's own
 * fetch/parse/render path runs untouched. Parsing the query (rather than
 * returning one canned list) keeps the rows consistent with the filters the
 * bar asked for — the reel's four sections really are four different sets. */
const POOL = LIVE ? null : loadCardPool(ROOT);
const seedOf = (s) => { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };

function answerMovers(url) {
  const q = new URL(url).searchParams;
  const order = q.get("order") || "mkt_pct_1d.desc";
  const pctCol = order.split(".")[0];
  const select = q.get("select") || "";
  const priceCol = select.includes("low_today") ? "low_today" : "market_today";
  const win = /_(1d)\b/.test(pctCol) ? "1d" : "1w";
  const limit = Math.max(1, Math.min(60, parseInt(q.get("limit") || "12", 10)));
  const rarityParam = q.get("rarity") || "";
  let rarities;
  if (rarityParam.startsWith("in.")) {
    rarities = rarityParam.slice(3).replace(/^\(|\)$/g, "").split(",").map((s) => s.replace(/"/g, "").trim());
  } else if (rarityParam.startsWith("eq.")) {
    rarities = [rarityParam.slice(3)];
  } else {
    rarities = ["Enchanted", "Epic", "Iconic", "Legendary", "Super Rare", "Rare"];
  }
  const rows = sampleRows({
    pool: POOL, rarities, window: win, limit,
    seed: seedOf(rarities.join("|") + "::" + pctCol),
  });
  return rows.map((r) => ({
    card_id: r.card_id, name: r.name, version: r.version, rarity: r.rarity,
    printing: r.printing, image_small: r.image_small,
    [priceCol]: r.price, [pctCol]: r.pct,
  }));
}

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,OPTIONS",
};

/* ── shared browser wiring ── */
async function wireContext(ctx, sceneHtml, shots) {
  if (FONT_DIR) {
    // No egress to fonts.g*.com here; serve the cached copies instead. Without
    // this every weight collapses to a fallback face and the bar re-measures
    // against type it will never ship with.
    await ctx.route("https://fonts.googleapis.com/**", async (route) => {
      const css = fs.readFileSync(path.join(FONT_DIR, "fonts.css"));
      await route.fulfill({ status: 200, contentType: "text/css", body: css, headers: CORS });
    });
    await ctx.route("https://fonts.gstatic.com/**", async (route) => {
      const file = path.join(FONT_DIR, path.basename(new URL(route.request().url()).pathname));
      if (!fs.existsSync(file)) return route.abort();
      await route.fulfill({ status: 200, contentType: "font/woff2", body: fs.readFileSync(file), headers: CORS });
    });
  }
  if (!LIVE) {
    await ctx.route(`https://${SB_HOST}/**`, async (route) => {
      if (route.request().method() === "OPTIONS") {
        return route.fulfill({ status: 204, headers: CORS, body: "" });
      }
      const body = JSON.stringify(answerMovers(route.request().url()));
      await route.fulfill({ status: 200, contentType: "application/json", body, headers: CORS });
    });
  }
  if (sceneHtml) {
    await ctx.route("**/__promo_scene*", async (route) =>
      route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: sceneHtml }));
  }
  for (const [name, buf] of Object.entries(shots || {})) {
    await ctx.route(`**/__promo_${name}.png`, async (route) =>
      route.fulfill({ status: 200, contentType: "image/png", body: buf }));
  }
}

/* ── step 1: real screenshots of the real configurator ── */
async function captureConfigurator(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 1200 }, deviceScaleFactor: 2 });
  await wireContext(ctx, null, null);
  const page = await ctx.newPage();
  await page.goto(`${ORIGIN}/ticker`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts && document.fonts.ready);
  // The configurator builds its output URL from location.origin, which here is
  // a throwaway localhost port. Rewrite it to the address the video is telling
  // people to visit — it is the one string a viewer might actually type.
  await page.evaluate(() => {
    const f = document.getElementById("urlOut");
    if (f) f.value = f.value.replace(/^https?:\/\/[^/]+\/ticker/, "https://packs.ink/ticker");
  });
  await page.waitForTimeout(900);
  const shots = {};
  const grab = async (hasText, name) => {
    const card = page.locator(".tk-card", { hasText }).first();
    if (await card.count()) shots[name] = await card.screenshot({ type: "png" });
  };
  await grab("What's in the reel", "reel");
  await grab("Your overlay URL", "url");
  await ctx.close();
  log(`configurator shots: ${Object.keys(shots).join(", ") || "none"}`);
  return shots;
}

/* ── step 2: render one format ── */
async function record(browser, fmt, sceneHtml, shots) {
  const total = Math.round(DURATION * FPS);
  const outFile = path.join(OUT_DIR, fmt.file);
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const ctx = await browser.newContext({
    viewport: { width: fmt.w, height: fmt.h }, deviceScaleFactor: 1,
    reducedMotion: "no-preference",
  });
  await wireContext(ctx, sceneHtml, shots);
  const page = await ctx.newPage();

  const sceneUrl = `${ORIGIN}/__promo_scene?fmt=${fmt.key}&dur=${DURATION}` +
    `&ticker=${encodeURIComponent("/ticker?" + TICKER_PARAMS.toString())}`;
  await page.goto(sceneUrl, { waitUntil: "load" });
  await page.evaluate(([r, u]) => window.__setShots(r, u),
    [shots.reel ? "/__promo_reel.png" : "", shots.url ? "/__promo_url.png" : ""]);

  // Wait for the bar to actually hold rows AND to have measured itself, or the
  // first seconds record an empty rail that snaps into place mid-shot.
  await page.waitForFunction(() => window.__tickerReady && window.__tickerReady(), null,
    { timeout: 30000 });
  await page.waitForFunction(() => {
    const f = document.querySelector(".tkslot iframe");
    const rail = f && f.contentDocument && f.contentDocument.getElementById("rail");
    return !!(rail && rail.style.getPropertyValue("--tk-dur"));
  }, null, { timeout: 30000 });
  await page.evaluate(() => document.fonts && document.fonts.ready);
  await page.evaluate(() => window.__layout && window.__layout());
  await page.waitForTimeout(700);
  // Fonts landing re-runs layoutStrip; re-assert the measurement afterwards.
  await page.evaluate(() => {
    const f = document.querySelector(".tkslot iframe");
    if (f && f.contentWindow && f.contentWindow.layoutStrip) f.contentWindow.layoutStrip();
  }).catch(() => {});
  await page.waitForTimeout(400);

  if (STILLS.length) {
    for (const t of STILLS) {
      await page.evaluate((x) => window.__seek(x), t);
      const f = path.join(OUT_DIR, `still-${fmt.key}-${String(t).replace(".", "_")}s.png`);
      fs.writeFileSync(f, await page.screenshot({ type: "png" }));
      log(`  still ${path.relative(ROOT, f)}`);
    }
    await ctx.close();
    return null;
  }

  const ff = spawn(FFMPEG, [
    "-y", "-loglevel", "error",
    "-f", "image2pipe", "-framerate", String(FPS), "-i", "-",
    "-c:v", "libx264", "-preset", "slow", "-crf", "20",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-r", String(FPS),
    outFile,
  ], { stdio: ["pipe", "ignore", "pipe"] });
  let ffErr = "";
  ff.stderr.on("data", (d) => { ffErr += d.toString(); });
  const done = new Promise((res, rej) => {
    ff.on("close", (code) => code === 0 ? res() : rej(new Error(`ffmpeg exit ${code}\n${ffErr}`)));
    ff.on("error", rej);
  });
  ff.stdin.on("error", () => {});

  log(`${fmt.key}: ${fmt.w}×${fmt.h}, ${total} frames @ ${FPS}fps`);
  const t0 = Date.now();
  for (let i = 0; i < total; i++) {
    await page.evaluate((t) => window.__seek(t), i / FPS);
    const buf = await page.screenshot({ type: "jpeg", quality: 96 });
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
    if (i % 90 === 0 || i === total - 1) {
      const pct = Math.round(((i + 1) / total) * 100);
      log(`  ${fmt.key} ${pct}% (${i + 1}/${total}, ${((Date.now() - t0) / 1000).toFixed(0)}s)`);
    }
  }
  ff.stdin.end();
  await done;
  await ctx.close();
  const mb = (fs.statSync(outFile).size / 1048576).toFixed(2);
  log(`${fmt.key} → ${path.relative(ROOT, outFile)} (${mb} MB)`);
  return outFile;
}

/* ── main ── */
let browser;
const server = await startDevServer();
try {
  log(`dev server up on ${ORIGIN}${LIVE ? " · LIVE data" : " · sample data (no egress)"}`);
  const sceneHtml = fs.readFileSync(path.join(HERE, "promo_scene.html"), "utf8");
  browser = await chromium.launch({
    executablePath: fs.existsSync(CHROME) ? CHROME : undefined,
    args: ["--force-device-scale-factor=1", "--hide-scrollbars", "--font-render-hinting=none",
           "--disable-lcd-text", "--autoplay-policy=no-user-gesture-required"],
  });
  const shots = await captureConfigurator(browser);
  for (const fmt of FORMATS) await record(browser, fmt, sceneHtml, shots);
  log("done");
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill("SIGTERM");
}
