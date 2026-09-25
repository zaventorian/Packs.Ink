/* Cut the calendar promo from the clips capture.mjs recorded.
 *
 *   node scripts/promo_calendar/compose.mjs [--only desktop|mobile] [--stills 3,12]
 *
 * scene.html is the stage; every frame is a seek (see its header), so the
 * output is deterministic and drops nothing. Clips are served through a route
 * with Range support, because <video> seeking needs it and the dev server's
 * SimpleHTTP handler has none. Audio is the synthesised tour bed
 * (promo/audio/calendar_bed.wav, `python scripts/promo_music.py --seconds 116 --out promo/audio/calendar_bed.wav` — ours outright).
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import { PLANS } from "./plan.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const argv = process.argv.slice(2);
const opt = (n, d) => { const i = argv.indexOf("--" + n); return i >= 0 ? argv[i + 1] : d; };
const ONLY = opt("only", "");
const FPS = 30;
const STILLS = (opt("stills", "") || "").split(",").map(Number).filter(Number.isFinite).filter((x) => opt("stills", "") !== "");
const OUT = path.join(ROOT, "promo", "calendar");
const AUDIO_OPT = opt("audio", "");   // override the plan's music; "none" for a silent cut
const LOCAL = process.env.LOCALAPPDATA || "";
const CHROME = process.env.PROMO_CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const FFMPEG = process.env.PROMO_FFMPEG ||
  [path.join(LOCAL, "Migaku", "MigakuShared", "ffmpeg.exe"), "C:/ffmpeg/bin/ffmpeg.exe"].find((p) => fs.existsSync(p)) || "ffmpeg";
const log = (...a) => console.log("[compose]", ...a);
const HOST = "http://promo.local";
const TYPES = { ".html": "text/html", ".mp4": "video/mp4", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml" };

async function wire(ctx) {
  await ctx.route(HOST + "/**", async (route) => {
    const u = new URL(route.request().url());
    let p = decodeURIComponent(u.pathname);
    const file = p === "/scene.html" ? path.join(HERE, "scene.html")
      : p.startsWith("/clips/") ? path.join(OUT, "clips", p.slice(7))
      : path.join(ROOT, p);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: "" });
    const type = TYPES[path.extname(file).toLowerCase()] || "application/octet-stream";
    const size = fs.statSync(file).size;
    const range = route.request().headers()["range"];
    if (range) {
      const m = /bytes=(\d*)-(\d*)/.exec(range);
      const a = m[1] ? +m[1] : 0, b = m[2] ? Math.min(+m[2], size - 1) : Math.min(a + 8 * 1024 * 1024 - 1, size - 1);
      const fd = fs.openSync(file, "r"); const buf = Buffer.alloc(b - a + 1); fs.readSync(fd, buf, 0, buf.length, a); fs.closeSync(fd);
      return route.fulfill({ status: 206, body: buf, headers: {
        "content-type": type, "accept-ranges": "bytes", "content-range": `bytes ${a}-${b}/${size}`, "content-length": String(buf.length) } });
    }
    return route.fulfill({ status: 200, path: file, headers: { "content-type": type, "accept-ranges": "bytes" } });
  });
}

async function run(browser, fmt) {
  const plan = PLANS[fmt];
  const W = fmt === "mobile" ? 1080 : 1920, H = fmt === "mobile" ? 1920 : 1080;
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await wire(ctx);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => log("  page error:", e.message));
  await page.goto(`${HOST}/scene.html?fmt=${fmt}&plan=${encodeURIComponent(JSON.stringify(plan))}`, { waitUntil: "load" });
  await page.evaluate(() => window.__ready());
  await page.evaluate(() => window.__seek(0));
  await page.waitForTimeout(800);
  const file = path.join(OUT, `lorcana-calendar-${fmt}.mp4`);
  /* --audit: step the whole cut at 15fps and list every callout that is
   * clipped by the window or hidden under the caption. Nothing is encoded. */
  if (argv.includes("--audit")) {
    const seen = new Map();
    for (let t = 0; t < plan.total; t += 1 / 15) {
      await page.evaluate((x) => window.__seek(x), t);
      const bad = await page.evaluate(() => window.__audit());
      const sh = plan.shots.findIndex((s) => t < s.at + s.dur);
      for (const b of bad) { const k = sh + " " + b; if (!seen.has(k)) seen.set(k, [t, t]); seen.get(k)[1] = t; }
    }
    for (const [k, [a, b]] of seen) log(`  ${a.toFixed(2)}-${b.toFixed(2)}s  shot ${k}`);
    log(seen.size ? `${seen.size} problem(s)` : "audit clean: every callout is on screen and clear of the caption");
    return ctx.close();
  }
  if (STILLS.length) {
    for (const t of STILLS) {
      await page.evaluate((x) => window.__seek(x), t);
      await page.waitForTimeout(60);
      fs.writeFileSync(path.join(OUT, `still-${fmt}-${t}.png`), await page.screenshot({ type: "png" }));
    }
    log(`${fmt}: ${STILLS.length} stills`);
    return ctx.close();
  }
  const total = Math.round(plan.total * FPS);
  /* The music is part of the PLAN: it decides where video 0 sits in the song
   * and where the fade starts, because the cuts are snapped to its beat. */
  const mu = plan.music || {};
  const AUDIO = AUDIO_OPT === "none" ? "" : AUDIO_OPT || (mu.file ? path.join(ROOT, mu.file) : "");
  const hasAudio = !!AUDIO && fs.existsSync(AUDIO);
  if (AUDIO && !hasAudio) log(`  ! no audio at ${AUDIO} — silent cut`);
  const args = ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-"];
  if (hasAudio) args.push("-ss", String(mu.start || 0), "-i", AUDIO, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
    "-af", `afade=t=in:st=0:d=0.3,afade=t=out:st=${(mu.fadeAt ?? plan.total - 2.5).toFixed(2)}:d=${(mu.fadeLen ?? 2.5).toFixed(2)}`, "-shortest");
  args.push("-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-r", String(FPS), file);
  const ff = spawn(FFMPEG, args, { stdio: ["pipe", "ignore", "pipe"] });
  let err = ""; ff.stderr.on("data", (d) => (err += d));
  const done = new Promise((res, rej) => ff.on("close", (c) => (c === 0 ? res() : rej(new Error(err)))));
  ff.stdin.on("error", () => {});
  const t0 = Date.now();
  for (let i = 0; i < total; i++) {
    await page.evaluate((t) => window.__seek(t), i / FPS);
    const buf = await page.screenshot({ type: "jpeg", quality: 95 });
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
    if (i % 150 === 0) log(`  ${fmt} ${Math.round((i / total) * 100)}% (${((Date.now() - t0) / 1000).toFixed(0)}s)`);
  }
  ff.stdin.end();
  await done;
  await ctx.close();
  log(`${fmt}: ${path.relative(ROOT, file)}`);
}

const browser = await chromium.launch({ executablePath: CHROME, args: ["--autoplay-policy=no-user-gesture-required"] });
for (const fmt of Object.keys(PLANS)) if (!ONLY || ONLY === fmt) await run(browser, fmt);
await browser.close();
