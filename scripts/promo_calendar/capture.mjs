/* Record the raw clips the calendar promo is cut from — the REAL app, driven
 * by a script, against the local dev server (so it shows this working tree).
 *
 *   node scripts/promo_calendar/capture.mjs [--only d_home,m_cal] [--port 8850]
 *
 * Frames come from the CDP screencast, not Playwright's recordVideo: that one
 * writes low-bitrate VP8 and the calendar is mostly small text, which it turns
 * to mush. The screencast hands over a JPEG per repaint at device resolution,
 * each with a timestamp, and ffmpeg's concat demuxer turns the uneven stream
 * into a constant 30fps clip by holding each frame for its real duration.
 *
 * Output: promo/calendar/clips/<name>.mp4, all-intra H.264 (-g 1) so the
 * compositor can seek any frame exactly and quickly.
 *
 * A drawn cursor is injected, because headless Chrome paints none and a promo
 * that clicks things with no visible pointer reads as a slideshow.
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const argv = process.argv.slice(2);
const opt = (n, d) => { const i = argv.indexOf("--" + n); return i >= 0 ? argv[i + 1] : d; };
const ONLY = (opt("only", "") || "").split(",").filter(Boolean);
const PORT = opt("port", "8850");
const ORIGIN = `http://localhost:${PORT}`;
const OUT = path.join(ROOT, "promo", "calendar");
const FR = path.join(OUT, "_frames");
const CLIPS = path.join(OUT, "clips");
const LOCAL = process.env.LOCALAPPDATA || "";
const CHROME = process.env.PROMO_CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const FFMPEG = process.env.PROMO_FFMPEG ||
  [path.join(LOCAL, "Migaku", "MigakuShared", "ffmpeg.exe"), "C:/ffmpeg/bin/ffmpeg.exe"].find((p) => fs.existsSync(p)) || "ffmpeg";
const log = (...a) => console.log("[cal]", ...a);

/* Suppress the SPA's first-run chrome, same keys as promo_capture.py. */
const BOOT = (() => {
  const k = {
    "packsink:tourSeen": "1", "packsink:installDismissed": "1", "packsink:installVisits": "99",
    "packsink:avatarPromptShown": "1", "packsink:gradedTos": "2026-06-23",
    "packsink:feedback:noticeDismissed": "2099-01-01T00:00:00.000Z", "packsink:themeMode": "dark",
  };
  for (const v of ["home", "cards", "screener", "history", "market", "collection", "decks", "calendar"])
    k["packsink:sectionTourSeen:" + v] = "1";
  return `try{const k=${JSON.stringify(k)};if(!sessionStorage.getItem('__promoBooted')){` +
    `for(const [a,b] of Object.entries(k))localStorage.setItem(a,b);` +
    // Filter prefs are per-clip: a region picked in one clip must not leak into
    // the next. Follows (packsink:calSubs) deliberately DO carry over.
    `for(const x of Object.keys(localStorage))if(/^packsink:cal:|^packsink:sc(Zip|Country|Pinned|View)/.test(x))localStorage.removeItem(x);` +
    `sessionStorage.setItem('__promoBooted','1');}` +
    `sessionStorage.setItem('packsink:autoTourFired','1');}catch(e){}`;
})();

/* The drawn pointer. Mouse events only, so a touch clip gets a fingertip dot. */
const CURSOR = `(() => {
  const mk = () => {
    if (document.getElementById('__pc')) return;
    const c = document.createElement('div'); c.id = '__pc';
    c.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px);transition:none';
    c.innerHTML = window.__touch
      ? '<div style="width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;background:rgba(255,255,255,.35);border:2px solid rgba(255,255,255,.85);box-shadow:0 2px 10px rgba(0,0,0,.4)"></div>'
      : '<svg width="26" height="26" viewBox="0 0 24 24" style="filter:drop-shadow(0 2px 3px rgba(0,0,0,.55))"><path d="M4 2l16 11.2-7 1.2 4.3 7.6-3 1.6-4.3-7.7L4 21z" fill="#fff" stroke="#111" stroke-width="1.3" stroke-linejoin="round"/></svg>';
    const r = document.createElement('div'); r.id = '__pr';
    r.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483646;pointer-events:none;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;border:3px solid #f2c94c;opacity:0';
    document.documentElement.append(c, r);
    if (window.__touch) c.style.opacity = '0';
  };
  const move = (x, y) => { mk(); document.getElementById('__pc').style.transform = 'translate(' + x + 'px,' + y + 'px)'; };
  addEventListener('mousemove', (e) => move(e.clientX, e.clientY), true);
  addEventListener('pointermove', (e) => move(e.clientX, e.clientY), true);
  const ring = (x, y) => {
    mk(); const r = document.getElementById('__pr');
    r.style.left = x + 'px'; r.style.top = y + 'px';
    r.animate([{ transform: 'scale(.35)', opacity: .95 }, { transform: 'scale(1.25)', opacity: 0 }], { duration: 520, easing: 'ease-out' });
    if (window.__touch) { const c = document.getElementById('__pc'); c.style.transform = 'translate(' + x + 'px,' + y + 'px)';
      c.animate([{ opacity: 1 }, { opacity: 1, offset: .6 }, { opacity: 0 }], { duration: 650 }); }
  };
  addEventListener('pointerdown', (e) => ring(e.clientX, e.clientY), true);
  addEventListener('DOMContentLoaded', mk);
})();`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function helpers(page, mobile, marks) {
  let mx = mobile ? 195 : 720, my = mobile ? 500 : 450;
  /* Cursor travel is quick on purpose: the edit speed-ramps holds, but a
   * slow glide ramped up still reads as a slow glide. */
  const glide = async (x, y, ms = 380) => {
    const n = Math.max(6, Math.round(ms / 16)), x0 = mx, y0 = my;
    for (let i = 1; i <= n; i++) {
      const k = ease(i / n);
      await page.mouse.move(x0 + (x - x0) * k, y0 + (y - y0) * k);
      await sleep(ms / n);
    }
    mx = x; my = y;
  };
  const box = async (sel) => {
    const l = typeof sel === "string" ? page.locator(sel).first() : sel;
    await l.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
    const b = await l.boundingBox();
    if (!b) throw new Error("no box for " + sel);
    return b;
  };
  const record = (name, b) => {
    if (name) marks.push({ name, t: Date.now() / 1000, r: b ? { x: b.x, y: b.y, w: b.width, h: b.height } : null });
  };
  /* A mark on its own: where a region is on screen right now. */
  const mark = async (name, sel) => {
    let b = null;
    try { const l = page.locator(sel).first(); b = await l.boundingBox({ timeout: 3000 }); } catch { /* keep null */ }
    record(name, b);
  };
  const opt = (o, d) => (typeof o === "number" ? { ...d, ms: o } : { ...d, ...(o || {}) });
  const to = async (sel, o) => {
    const { ms, mark: m } = opt(o, { ms: 380 });
    const b = await box(sel);
    if (!mobile) await glide(b.x + b.width / 2, b.y + b.height / 2, ms);
    record(m, b);
  };
  const click = async (sel, o, afterArg) => {
    const { ms, after, mark: m } = opt(o, { ms: 380, after: afterArg ?? 900 });
    const b = await box(sel);
    const x = b.x + b.width / 2, y = b.y + b.height / 2;
    if (mobile) { await page.touchscreen.tap(x, y); mx = x; my = y; }
    else { await glide(x, y, ms); await sleep(90); record(m, b); await page.mouse.down(); await sleep(60); await page.mouse.up(); }
    if (mobile) record(m, b);
    await sleep(after);
    /* Where it is NOW: a click often re-flows the page (switching views moves
     * the toolbar), so a callout that lingers after the click needs this box. */
    if (m) { try { const a = await page.locator(sel).first().boundingBox({ timeout: 1500 }); record(m + "After", a); } catch { /* gone */ } }
  };
  const type = async (sel, text, delay = 110, m) => {
    await click(sel, { after: 150, mark: m });
    await page.locator(sel).first().fill("").catch(() => {});
    await page.locator(sel).first().pressSequentially(text, { delay });
    record(m && m + "Done", await box(sel));
  };
  const scroll = async (dy, ms = 900) => {
    await page.evaluate(([d, t]) => new Promise((res) => {
      const y0 = scrollY, t0 = performance.now();
      const e = (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);
      const f = (now) => { const k = Math.min(1, (now - t0) / t); scrollTo(0, y0 + d * e(k)); k < 1 ? requestAnimationFrame(f) : res(); };
      requestAnimationFrame(f);
    }), [dy, ms]);
  };
  const scrollTop = (y, ms) => page.evaluate(() => scrollY).then((y0) => scroll(y - y0, ms));
  return { glide, to, click, type, scroll, scrollTop, box, mark };
}

/* ── the clips ─────────────────────────────────────────────────────────────
 * Every action that matters calls h.mark(name, selector) (or passes {mark})
 * and the clip's <name>.marks.json then says WHEN it happened and WHERE on
 * screen. The plan zooms, cuts and draws callouts off those marks instead of
 * hand-typed coordinates. Capture holds generously; the edit speed-ramps the
 * waits out. ORDER MATTERS: c_local follows a store, and every later clip
 * (recorded with its storage state) shows that store. */
const CLIPS_DEF = [
  // THE centrepiece: find your local SCs / prereleases / locals, follow a shop.
  { name: "c_local", path: "/calendar", async run(page, h) {
    await sleep(900);
    await h.click(".cal-near-chip:not(.cal-follow-add)", { mark: "nearChip" });
    await sleep(900);
    await h.mark("finder", ".sc-box");
    await h.type(".sc-zip-input", "Chicago", 120, "zip");
    await h.click(".sc-search-btn", { mark: "search", after: 2600 });
    await h.mark("results", ".sc-results-head");
    await h.to(".sc-tile >> nth=0", { mark: "scTile", ms: 350 });
    await sleep(1400);
    await h.click(".sc-mode-btn:has-text('Prereleases')", { mark: "modePre", after: 2000 });
    await h.to(".sc-tile >> nth=0", { mark: "preTile", ms: 350 });
    await sleep(1200);
    await h.click(".sc-mode-btn:has-text('Locals')", { mark: "modeLocals", after: 2000 });
    await h.click(".sc-tile-more >> nth=0", { mark: "series", after: 1800 });
    await h.mark("seriesOpen", ".sc-tile:has(.sc-tile-more) >> nth=0");
    // Back to Set Champs only, then follow the shop running the soonest one.
    await h.click(".sc-mode-btn:has-text('Prereleases')", { after: 500 });
    await h.click(".sc-mode-btn:has-text('Locals')", { mark: "scOnlyClick", after: 1400 });
    await h.mark("scOnly", ".sc-list");
    await h.click(".sc-tile >> nth=0 >> .cal-add-btn", { mark: "addBtn", after: 1000 });
    await h.mark("pop", ".cal-add-pop");
    await h.click(".cal-add-pop .cal-add-store .cal-add-item >> nth=0", { mark: "follow", after: 1300 });
    await h.click(".cal-add-pop .cal-add-check:has-text('Locals')", { mark: "untick", after: 1500 });
    await h.mark("popDone", ".cal-add-pop");
    await sleep(600);
    { const b = await h.box(".sc-results-head"); await h.glide(b.x + b.width * 0.45, b.y + b.height / 2, 300);
      await page.mouse.down(); await page.mouse.up(); await sleep(600); }
    await h.click(".sc-viewtoggle-btn:has-text('Map')", { mark: "finderMap", after: 2800 });
    await h.to(".sc-map-pin >> nth=1", { mark: "finderPin", ms: 400 }).catch(() => {});
    await sleep(1400);
    await h.click(".sc-collapse-btn", { mark: "closeFinder", after: 1300 });
    await h.mark("backOnCal", ".cal-month");
    await h.to(".cal-chip-filter:has-text('My stores')", { mark: "myStoresChip", ms: 400 }).catch(() => {});
    await sleep(900);
    await h.click(".cal-near-chip:not(.cal-follow-add)", { mark: "nearOn", after: 1800 });
    await h.click(".cal-month-nav[aria-label='Next month']", { mark: "nextMonth", after: 2200 });
    await h.mark("octMonth", ".cal-month");
    await sleep(1500);
  }},
  // Local, on the map.
  { name: "c_map", path: "/calendar?cv=map", async run(page, h) {
    await sleep(1600);
    await h.mark("world", ".sc-map-box");
    await sleep(800);
    await h.type(".cal-map-place input", "Chicago", 110, "place");
    await h.click(".cal-map-go", { mark: "zoomGo", after: 3200 });
    await h.mark("chicago", ".sc-map-box");
    await h.click(".cal-map-zoom button[aria-label='Zoom in']", { mark: "plus", after: 2200 });
    await h.click(".cal-map-view button:has-text('Locals')", { mark: "mapLocalsOff", after: 1800 }).catch(() => {});
    await h.click(".sc-map-pin >> nth=2", { mark: "pin", after: 2000 }).catch(() => {});
    await h.mark("pinPop", ".sc-map-box");
    await h.scroll(460, 900);
    await sleep(600);
    await h.mark("onMap", ".sc-map-box");
    await sleep(1500);
  }},
  // Glance: the home tile.
  { name: "c_home", path: "/", async run(page, h) {
    await sleep(900);
    await h.mark("tile", ".cal-month--compact");
    await h.to(".cal-month--compact .cal-chip--group", { mark: "group", ms: 500 });
    await sleep(2000);
    await h.click(".cal-panel-tool--view", { mark: "flip", after: 1500 });
    await h.to(".cal-panel-list li >> nth=1", { mark: "row", ms: 350 });
    await sleep(1500);
    await h.click(".cal-panel-page button >> nth=-1", { mark: "page", after: 1500 });
  }},
  // Four views, fast.
  { name: "c_views", path: "/calendar", async run(page, h) {
    await sleep(900);
    await h.mark("month", ".cal-month");
    await h.click(".cal-modes button:has-text('List')", { mark: "list", after: 1500 });
    await h.click(".cal-modes button:has-text('Timeline')", { mark: "timeline", after: 1700 });
    await h.click(".cal-modes button:has-text('Map')", { mark: "map", after: 2200 });
  }},
  // Plan the season.
  { name: "c_timeline", path: "/calendar?cv=timeline", async run(page, h) {
    await sleep(1200);
    await h.mark("chart", ".cal-tl");
    await h.to(".cal-tl-dot >> nth=4", { mark: "dot", ms: 450 });
    await sleep(1400);
    await h.click("button:has-text('By region')", { mark: "byRegion", after: 2200 });
    await h.click(".cal-spans button:has-text('24')", { mark: "span24", after: 2200 });
    await h.to(".cal-tl-season >> nth=1", { mark: "season", ms: 450 }).catch(() => {});
    await sleep(1400);
  }},
  // Find anything: kind chips + search.
  { name: "c_filter", path: "/calendar?cv=list", async run(page, h) {
    await sleep(900);
    await h.click(".cal-chip-filter:has-text('DLCs')", { mark: "chipDlc", after: 1100 });
    await h.click(".cal-chip-filter:has-text('CCQs')", { mark: "chipCcq", after: 1300 });
    await h.click(".cal-chip-filter:has-text('DLCs')", { after: 500 });
    await h.click(".cal-chip-filter:has-text('CCQs')", { after: 900 });
    await h.type(".cal-search input", "Hyperia", 110, "search");
    await sleep(1600);
    await h.mark("results", ".cal-rows");
  }},
  // One event: the Hyperia City prerelease.
  { name: "c_detail", path: "/calendar?cv=list", async run(page, h) {
    await sleep(900);
    await h.type(".cal-search input", "Hyperia City Prerelease", 40, "search");
    await sleep(900);
    await h.click(".cal-row >> nth=0", { mark: "row", after: 2000 });
    await h.mark("modal", ".cal-modal");
    await h.to(".cal-modal .cal-products-head", { mark: "products", ms: 500 }).catch(() => {});
    await sleep(1600);
    await h.click(".cal-modal .cal-add-btn, .cal-modal button:has-text('Add to my calendar')", { mark: "add", after: 1500 }).catch(() => {});
    await h.mark("modalAfter", ".cal-modal");
    await sleep(1000);
  }},
  // Yours: the drawer + export.
  { name: "c_mine", path: "/calendar", async run(page, h) {
    await sleep(1000);
    await h.click(".cal-follow-toggle", { mark: "drawer", after: 1800 });
    await h.mark("drawerBody", ".cal-follow-body");
    await h.to("button:has-text('Export .ics')", { mark: "export", ms: 500 });
    await sleep(1500);
  }},
  // Phone.
  { name: "c_phone", path: "/calendar", mobile: true, async run(page, h) {
    await sleep(1200);
    await h.click(".cal-chip--group >> nth=0", { after: 1500 });
    await page.keyboard.press("Escape").catch(() => {}); await sleep(400);
    await h.click(".cal-modes button:has-text('List')", { after: 1300 });
    await h.click(".cal-modes button:has-text('Map')", { after: 2200 });
  }},
];

async function recordClip(browsers, def, state) {
  const mobile = !!def.mobile;
  /* viewport:null + --force-device-scale-factor is what makes the screencast
   * hand over REAL device pixels: with Playwright's own DPR emulation the
   * frames arrive at CSS size, so a 2x context still records 1440x900. */
  const ctx = await browsers[mobile ? 1 : 0].newContext({ viewport: null, hasTouch: mobile, storageState: state });
  await ctx.addInitScript(BOOT);
  if (mobile) await ctx.addInitScript("window.__touch=true");
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  // deviceScaleFactor 0 = leave the real (flag-forced) 2x alone; only the CSS
  // viewport is pinned, which keeps the screencast at device resolution.
  const pre = await ctx.newCDPSession(page);
  await pre.send("Emulation.setDeviceMetricsOverride", mobile
    ? { width: 390, height: 844, deviceScaleFactor: 0, mobile: true }
    : { width: 1440, height: 900, deviceScaleFactor: 0, mobile: false });
  if (mobile) await pre.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await page.goto(ORIGIN + def.path, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(7500);
  await page.evaluate(() => document.fonts && document.fonts.ready).catch(() => {});
  log("  viewport " + await page.evaluate(() => innerWidth + "x" + innerHeight + " @" + devicePixelRatio));

  const dir = path.join(FR, def.name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const cdp = await ctx.newCDPSession(page);
  const frames = [];
  cdp.on("Page.screencastFrame", async (f) => {
    const file = String(frames.length).padStart(5, "0") + ".jpg";
    frames.push({ file, t: f.metadata.timestamp });
    fs.writeFileSync(path.join(dir, file), Buffer.from(f.data, "base64"));
    cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
  });
  const W = mobile ? 780 : 2880, H = mobile ? 1688 : 1800;
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
  // Nudge a repaint so frame 0 exists even on a static page.
  await page.mouse.move(mobile ? 195 : 720, mobile ? 500 : 450);
  await sleep(300);
  const marks = [];
  const h = helpers(page, mobile, marks);
  let err = null;
  try { await def.run(page, h); } catch (e) { err = e; log(`  ! ${def.name}: ${String(e.message).split("\n")[0]}`); }
  await sleep(1500);
  await page.evaluate(() => { const c = document.getElementById("__pc"); if (c) c.style.opacity = c.style.opacity; });
  const tEnd = Date.now() / 1000;
  await cdp.send("Page.stopScreencast").catch(() => {});
  const st = await ctx.storageState();
  await ctx.close();
  return { frames, tEnd, dir, err, state: st, marks };
}

function encode(name, { frames, dir }, tEnd) {
  if (!frames.length) throw new Error("no frames for " + name);
  const lines = [];
  for (let i = 0; i < frames.length; i++) {
    const next = i + 1 < frames.length ? frames[i + 1].t : Math.max(frames[i].t + 0.5, tEnd);
    lines.push(`file '${frames[i].file}'`, `duration ${Math.max(0.001, next - frames[i].t).toFixed(4)}`);
  }
  lines.push(`file '${frames[frames.length - 1].file}'`);
  fs.writeFileSync(path.join(dir, "list.txt"), lines.join("\n"));
  fs.mkdirSync(CLIPS, { recursive: true });
  const out = path.join(CLIPS, name + ".mp4");
  return new Promise((res, rej) => {
    const ff = spawn(FFMPEG, ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
      "-vf", "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "medium", "-crf", "14",
      "-g", "1", "-pix_fmt", "yuv420p", out], { cwd: dir, stdio: ["ignore", "ignore", "pipe"] });
    let e = ""; ff.stderr.on("data", (d) => (e += d));
    ff.on("close", (c) => (c === 0 ? res(out) : rej(new Error(e))));
  });
}

/* Window sizes are the CSS viewport plus headless chrome's own frame (16x95),
 * measured: 1456x995 -> 1440x900. The run asserts it below. */
const browsers = [
  await chromium.launch({ executablePath: CHROME, args: ["--hide-scrollbars", "--force-device-scale-factor=2", "--window-size=1456,995"] }),
  await chromium.launch({ executablePath: CHROME, args: ["--hide-scrollbars", "--force-device-scale-factor=2", "--window-size=520,1000"] }),
];
let state = undefined;
const statePath = path.join(OUT, "_state.json");
if (fs.existsSync(statePath) && ONLY.length) state = statePath;
for (const def of CLIPS_DEF) {
  if (ONLY.length && !ONLY.includes(def.name)) continue;
  log(def.name);
  const r = await recordClip(browsers, def, state);
  // The follow made in d_finder carries into every later clip.
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(statePath, JSON.stringify(r.state));
  state = statePath;
  const out = await encode(def.name, r, r.tEnd);
  /* Marks in CLIP time (seconds from the first frame) and CLIP pixels. */
  const t0 = r.frames.length ? r.frames[0].t : 0, k = def.mobile ? 2 : 2;
  const mk = r.marks.map((m) => ({ name: m.name, t: +(m.t - t0).toFixed(3),
    r: m.r && { x: Math.round(m.r.x * k), y: Math.round(m.r.y * k), w: Math.round(m.r.w * k), h: Math.round(m.r.h * k) } }));
  fs.writeFileSync(path.join(CLIPS, def.name + ".marks.json"), JSON.stringify(mk, null, 1));
  log(`  marks: ${mk.map((m) => m.name + (m.r ? "" : "(no box)")).join(" ")}`);
  const dur = r.frames.length ? (r.tEnd - r.frames[0].t).toFixed(1) : 0;
  log(`  ${r.frames.length} frames, ${dur}s -> ${path.relative(ROOT, out)}`);
}
for (const b of browsers) await b.close();
