/* Record the stream-ticker promo videos — one 16:9 for desktop feeds, one 9:16
 * for phones. Both frame the REAL /ticker?bar=1 page in an iframe sized like an
 * OBS browser source; nothing about the bar is re-implemented here.
 *
 *   node scripts/promo_ticker/record_promo.mjs [--sample] [--fonts <dir>]
 *        [--out <dir>] [--only desktop|mobile] [--fps 30] [--dur 36]
 *
 * Every frame is produced by seeking the scene to an exact time and taking a
 * screenshot, so output is deterministic and drops no frames — unlike
 * real-time capture. The ticker's own marquee is seeked through the Web
 * Animations API by the scene's __seek().
 *
 * --sample     answer the Supabase query from sample_data.mjs and turn card-art
 *              thumbnails off. ONLY for a machine with no egress to
 *              supabase.co / the card-art CDN; the prices are invented, so the
 *              result is for checking layout, never for publishing.
 * --fonts DIR  serve Google Fonts from a local cache (see fetch_fonts.sh) for
 *              machines with no egress to fonts.googleapis.com.
 *
 * ⚠ LIVE IS THE DEFAULT. This used to be the other way round because the run
 * that wrote it had no network; on any ordinary machine the sample path gives
 * a video whose numbers are fiction, which is not the thing to publish.
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import { loadCardPool, sampleRows } from "./sample_data.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");

/* ── args ── */
const argv = process.argv.slice(2);
const flag = (n) => argv.includes("--" + n);
const opt = (n, d) => { const i = argv.indexOf("--" + n); return i >= 0 ? argv[i + 1] : d; };
const LIVE = !flag("sample");
const FONT_DIR = opt("fonts", "");
const OUT_DIR = path.resolve(opt("out", path.join(ROOT, "promo")));
const ONLY = opt("only", "");
const FPS = parseInt(opt("fps", "30"), 10);
/* ── the music, and why the length is what it is ───────────────────────────
 * The backing track is 139.675 BPM (measured off the file with an FFT
 * autocorrelation of its onset envelope, not guessed), so a bar is 1.7184s.
 * The cut is 21 bars: one bar of lead-in and four bars for each of the five
 * blocks. promo_scene.html derives the same numbers from the same BPM, so the
 * picture changes on downbeats.
 *
 * ⚠ AUDIO_START is a DOWNBEAT (32.388s), and it is also where the track's
 * chorus enters — energy jumps from 0.34 to 0.77 there and the window ends
 * strong at 0.84, which the neighbouring downbeats do not. Move it and it must
 * land on another downbeat or every cut in the video drifts off the beat. */
const BPM = 139.674831;
const BARS = 21;
const BAR = 4 * 60 / BPM;
const DURATION = parseFloat(opt("dur", String(BARS * BAR)));
const AUDIO = opt("audio", path.join(ROOT, "promo", "audio", "ticker-promo.mp3"));
const AUDIO_START = parseFloat(opt("audio-start", "32.388"));
const FADE_IN = 0.18, FADE_OUT = 1.5;
/* A fresh random port per run: scripts/dev_server.py uses ThreadingTCPServer
 * without allow_reuse_address, so re-binding the same port right after a
 * previous run dies on the socket's TIME_WAIT. */
let PORT = parseInt(opt("port", "0"), 10) || 8800 + Math.floor(Math.random() * 900);
/* --stills 1,5,11 writes PNG frames at those seconds instead of encoding a
 * video: the fast way to iterate on the layout, and a cheap way to pull a
 * poster frame / thumbnail out of a finished cut. */
const STILLS = (opt("stills", "") || "").split(",").map((s) => parseFloat(s)).filter(Number.isFinite);
let ORIGIN = `http://localhost:${PORT}`;

const SB_HOST = "umwqowkiatjjltologrd.supabase.co";

/* ── the ticker config the videos advertise ───────────────────────────────
 * Three windows × two rarity groups, PLUS a graded section per window — so the
 * reel the video shows off covers both halves of the product. NM Market basis
 * rather than the page's default Low: over a 1D/1W window Low is a published
 * aggregate that can sit frozen, and it throws multi-thousand-percent phantoms
 * that read as a bug on screen. Every one of these is a setting the page
 * offers, so the bar in the video is a bar a viewer can actually build. */
const TICKER_PARAMS = new URLSearchParams({
  bar: "1", w: "1d,1w,1m", g: "chase,rareleg", gk: "movers", gr: "PSA", gg: "10",
  m: "mkt", n: "10", min: "5", gmin: "100", speed: "60",
});
if (!LIVE) TICKER_PARAMS.set("img", "0");
/* The same settings without bar=1 — i.e. the page a viewer would land on.
 * ⚠ /ticker is TWO pages behind one path: with ?bar= or ?embed= it is the raw
 * overlay, and bare it is the SPA's Analytics » Stream Ticker tab. The tab is
 * what "go to packs.ink/ticker" actually shows, so that is what gets shot. */
const PAGE_PARAMS = new URLSearchParams(TICKER_PARAMS);
PAGE_PARAMS.delete("bar");

const FORMATS = [
  { key: "desktop", w: 1920, h: 1080, file: "stream-ticker-desktop.mp4" },
  { key: "mobile", w: 1080, h: 1920, file: "stream-ticker-mobile.mp4" },
].filter((f) => !ONLY || f.key === ONLY);

const log = (...a) => console.log("[promo]", ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ── binaries ─────────────────────────────────────────────────────────────
 * Resolved rather than assumed: this runs on a sandbox with Chromium at a
 * fixed path, and on Windows where neither ffmpeg nor a playwright-managed
 * Chromium is necessarily present. */
const WIN = process.platform === "win32";
const PY = process.env.PROMO_PYTHON || (WIN ? "python" : "python3");
function firstExisting(list) {
  for (const p of list) { try { if (p && fs.existsSync(p)) return p; } catch { /* ignore */ } }
  return "";
}
const LOCAL = process.env.LOCALAPPDATA || "";
const CHROME = process.env.PROMO_CHROME || firstExisting([
  "/opt/pw-browsers/chromium",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
]);
/* ⚠ Playwright ships an ffmpeg, and it CANNOT be used here: it is a stripped
 * build with libvpx/webm only — no libx264, no mp4 muxer. Anything found under
 * ms-playwright is deliberately not in this list. */
const FFMPEG = process.env.PROMO_FFMPEG || firstExisting([
  LOCAL && path.join(LOCAL, "Migaku", "MigakuShared", "ffmpeg.exe"),
  "C:/ffmpeg/bin/ffmpeg.exe",
  "C:/Program Files/ffmpeg/bin/ffmpeg.exe",
]) || "ffmpeg";

/* ── the dev server (serves /ticker, styles.css, Logos/…) ── */
function spawnServer(port) {
  /* stdio is dropped, not piped: dev_server logs every request, and a piped
   * stderr nobody drains fills its buffer and BLOCKS the server mid-response —
   * which shows up as ERR_EMPTY_RESPONSE in the browser, not as an error here. */
  const proc = spawn(PY, [path.join(ROOT, "scripts", "dev_server.py"), String(port)], {
    cwd: ROOT, stdio: "ignore",
  });
  proc.on("error", () => {});
  return proc;
}
async function reachable(origin) {
  try { return (await fetch(`${origin}/ticker`)).ok; } catch { return false; }
}
/* Returns the live child process, having proved it actually answers. */
async function startDevServer() {
  for (let attempt = 0; attempt < 5; attempt++) {
    const port = attempt === 0 ? PORT : 8800 + Math.floor(Math.random() * 900);
    const proc = spawnServer(port);
    for (let i = 0; i < 40; i++) {
      if (proc.exitCode !== null) break;
      if (await reachable(`http://localhost:${port}`)) {
        PORT = port;
        ORIGIN = `http://localhost:${port}`;
        return proc;
      }
      await sleep(200);
    }
    proc.kill("SIGKILL");
  }
  throw new Error(`dev server never came up (tried ${PY} scripts/dev_server.py)`);
}

/* ── sample-data route ─────────────────────────────────────────────────────
 * Answers the exact PostgREST query buildTickerPlan() emits, so the page's own
 * fetch/parse/render path runs untouched. */
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

/* Suppress the SPA's first-run chrome — the onboarding tour, the install
 * nudge, the graded ToS gate — so the page shot is the page, not a modal.
 * Same keys promo_capture.py's boot_script() sets, for the same reason. */
const SPA_VIEWS = ["home", "screener", "history", "market", "cards", "collection",
                   "decks", "faq", "gear", "calendar", "elo"];
function bootScript() {
  const keys = {
    "packsink:tourSeen": "1",
    "packsink:installDismissed": "1",
    "packsink:installVisits": "99",
    "packsink:avatarPromptShown": "1",
    "packsink:gradedTos": "2026-06-23",
    "packsink:feedback:noticeDismissed": "2099-01-01T00:00:00.000Z",
    "packsink:themeMode": "dark",
  };
  for (const v of SPA_VIEWS) keys["packsink:sectionTourSeen:" + v] = "1";
  return `try{const k=${JSON.stringify(keys)};` +
    "for(const [a,b] of Object.entries(k))localStorage.setItem(a,b);" +
    "sessionStorage.setItem('packsink:autoTourFired','1');}catch(e){}";
}

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

/* ── step 1: a real screenshot of the real page ───────────────────────────
 * Shot at 900 CSS px wide on purpose. The configurator's own layout goes
 * single-column under 900px, which makes every settings card ~824px wide and
 * genuinely readable when it is panned inside a frame — at desktop width the
 * same cards are a 340px column and the labels turn to mush on video. */
async function capturePage(browser) {
  const ctx = await browser.newContext({ viewport: { width: 900, height: 1000 }, deviceScaleFactor: 2 });
  await wireContext(ctx, null, null);
  await ctx.addInitScript(bootScript());
  const page = await ctx.newPage();
  await page.goto(`${ORIGIN}/ticker?${PAGE_PARAMS.toString()}`, { waitUntil: "networkidle", timeout: 120000 });
  await page.evaluate(() => document.fonts && document.fonts.ready).catch(() => {});
  await page.waitForTimeout(6000);
  // The configurator builds its output URL from location.origin, which here is
  // a throwaway localhost port. Rewrite it to the address the video is telling
  // people to visit — it is the one string a viewer might actually type.
  await page.evaluate(() => {
    const frames = [document, ...[...document.querySelectorAll("iframe")]
      .map((f) => { try { return f.contentDocument; } catch (e) { return null; } })];
    for (const d of frames) {
      const f = d && d.getElementById && d.getElementById("urlOut");
      if (f) f.value = f.value.replace(/^https?:\/\/[^/]+\/ticker/, "https://packs.ink/ticker");
    }
  }).catch(() => {});
  /* Per-beat pan bounds, measured off the real cards rather than guessed.
   * Every bullet beat shows the page beside it, parked on the card that beat
   * is actually talking about — so the copy and the demo agree instead of the
   * settings turning up once at the end. */
  const meta = await page.evaluate(() => {
    const idoc = (() => {
      for (const f of document.querySelectorAll("iframe")) {
        try { if (f.contentDocument && f.contentDocument.querySelector(".tk-card")) return f.contentDocument; }
        catch (e) { /* cross-origin, ignore */ }
      }
      return null;
    })();
    const frameTop = (() => {
      for (const f of document.querySelectorAll("iframe")) {
        try { if (f.contentDocument && f.contentDocument.querySelector(".tk-card")) return f.getBoundingClientRect().top + window.scrollY; }
        catch (e) { /* ignore */ }
      }
      return 0;
    })();
    const d = idoc || document;
    const cards = [...d.querySelectorAll(".tk-card")];
    const off = idoc ? frameTop : 0;
    const sy = idoc ? idoc.defaultView.scrollY : window.scrollY;
    const byTitle = (re) => cards.find((c) => { const h = c.querySelector("h2"); return h && re.test(h.textContent); });
    const box = (c) => c && [Math.round(c.getBoundingClientRect().top + sy + off),
                             Math.round(c.getBoundingClientRect().bottom + sy + off)];
    const span = (a, b) => { const x = box(a), y = box(b); return x && y ? [x[0], y[1]] : (x || y); };
    return {
      w: document.documentElement.clientWidth,
      h: document.documentElement.scrollHeight,
      frameTop: Math.round(frameTop), inIframe: !!idoc,
      /* One entry per bullet beat, keyed the way the scene names its beats. */
      rects: {
        reel: box(byTitle(/what's in the reel/i) || cards[0]),
        graded: box(byTitle(/graded slabs/i) || cards[1]),
        custom: span(byTitle(/look & motion|look &amp; motion|look/i) || cards[2],
                     byTitle(/add it to obs/i) || byTitle(/your overlay url/i) || cards[cards.length - 1]),
      },
      cards: cards.map((c) => (c.querySelector("h2") || {}).textContent || ""),
    };
  });
  const buf = await page.screenshot({ type: "png", fullPage: true });
  await ctx.close();
  log(`page shot: ${meta.w}x${meta.h} css · iframe=${meta.inIframe} frameTop=${meta.frameTop}`);
  log(`  cards: ${meta.cards.map((s) => s.trim()).join(" | ")}`);
  for (const [k, r] of Object.entries(meta.rects)) log(`  pan/${k}: ${r ? r.join(" -> ") : "MISSING"}`);
  return { buf, meta };
}

/* ── step 2: render one format ── */
async function record(browser, fmt, sceneHtml, shots, pageMeta) {
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

  // Wait for the bar to actually hold rows AND to have measured itself, or the
  // first seconds record an empty rail that snaps into place mid-shot.
  await page.waitForFunction(() => window.__tickerReady && window.__tickerReady(), null,
    { timeout: 60000 });
  await page.waitForFunction(() => {
    const f = document.querySelector(".tkslot iframe");
    const rail = f && f.contentDocument && f.contentDocument.getElementById("rail");
    return !!(rail && rail.style.getPropertyValue("--tk-dur"));
  }, null, { timeout: 60000 });
  await page.evaluate(() => document.fonts && document.fonts.ready).catch(() => {});
  await page.waitForTimeout(900);
  // Fonts landing re-runs layoutStrip; re-assert the measurement afterwards.
  await page.evaluate(() => {
    const f = document.querySelector(".tkslot iframe");
    if (f && f.contentWindow && f.contentWindow.layoutStrip) f.contentWindow.layoutStrip();
  }).catch(() => {});
  await page.waitForTimeout(600);

  // The page shot, and the pan bounds measured off it.
  if (shots.page && pageMeta) {
    /* Raw card rects only. Turning them into a pan is deliberately left to the
     * scene: only the scene knows the frame's height and scale, so only it can
     * decide whether a card fits whole or has to be swept. */
    await page.evaluate(([url, m]) => window.__setPage(url, m), ["/__promo_page.png", {
      w: pageMeta.w, h: pageMeta.h, rects: pageMeta.rects,
    }]);
    // The shot is a big PNG; let it decode before the first frame is taken.
    await page.waitForFunction(() => {
      const i = document.getElementById("shotPage");
      return !!(i && i.complete && i.naturalWidth > 0);
    }, null, { timeout: 30000 }).catch(() => log("  ! page shot never decoded"));
  }

  /* Cue the marquee: measured inside the iframe, handed to the scene. Without
   * this the 36-second video would never leave the first of nine sections. */
  const cues = await page.evaluate(() => {
    const c = window.__measureCues && window.__measureCues();
    if (c) window.__setCues(c);
    return c && { dur: c.dur, seqW: Math.round(c.seqW), n: c.secs.length,
                  secs: c.secs.map((s) => s.title + (s.sub ? " · " + s.sub : "")) };
  });
  if (!cues) log("  ! no cue table — the bar will run from zero");
  else log(`  cues: ${cues.n} sections, loop ${Math.round(cues.dur)}s / ${cues.seqW}px`);
  if (cues && fmt.key === FORMATS[0].key) cues.secs.forEach((s, i) => log(`    ${i}. ${s}`));

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

  /* Video and audio in ONE pass: the frames arrive on stdin while the track is
   * a second input seeked to its downbeat, so the video is never re-encoded to
   * add sound. -shortest ends the file with the picture. */
  const hasAudio = fs.existsSync(AUDIO);
  const args = ["-y", "-loglevel", "error",
    "-f", "image2pipe", "-framerate", String(FPS), "-i", "-"];
  if (hasAudio) args.push("-ss", String(AUDIO_START), "-i", AUDIO);
  args.push("-map", "0:v");
  if (hasAudio) {
    args.push("-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
      "-af", `afade=t=in:st=0:d=${FADE_IN},` +
             `afade=t=out:st=${(DURATION - FADE_OUT).toFixed(3)}:d=${FADE_OUT}`,
      "-shortest");
  }
  args.push("-c:v", "libx264", "-preset", "slow", "-crf", "20",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-r", String(FPS), outFile);
  if (!hasAudio) log(`  ! no audio at ${path.relative(ROOT, AUDIO)} — silent cut`);
  const ff = spawn(FFMPEG, args, { stdio: ["pipe", "ignore", "pipe"] });
  let ffErr = "";
  ff.stderr.on("data", (d) => { ffErr += d.toString(); });
  const done = new Promise((res, rej) => {
    ff.on("close", (code) => code === 0 ? res() : rej(new Error(`ffmpeg exit ${code}\n${ffErr}`)));
    ff.on("error", (e) => rej(new Error(`ffmpeg (${FFMPEG}) failed to start: ${e.message}`)));
  });
  ff.stdin.on("error", () => {});

  log(`${fmt.key}: ${fmt.w}x${fmt.h}, ${total} frames @ ${FPS}fps`);
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
  log(`${fmt.key} -> ${path.relative(ROOT, outFile)} (${mb} MB)`);
  return outFile;
}

/* ── main ── */
let browser;
const server = await startDevServer();
try {
  log(`dev server up on ${ORIGIN}${LIVE ? " · LIVE data" : " · SAMPLE data (invented prices)"}`);
  if (!LIVE) log("  ! --sample: prices are fiction and thumbnails are off. Do not publish.");
  const sceneHtml = fs.readFileSync(path.join(HERE, "promo_scene.html"), "utf8");
  browser = await chromium.launch({
    executablePath: CHROME || undefined,
    args: ["--force-device-scale-factor=1", "--hide-scrollbars", "--font-render-hinting=none",
           "--disable-lcd-text", "--autoplay-policy=no-user-gesture-required"],
  });
  const page = await capturePage(browser);
  const shots = { page: page.buf };
  for (const fmt of FORMATS) await record(browser, fmt, sceneHtml, shots, page.meta);
  log("done");
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill("SIGTERM");
}
