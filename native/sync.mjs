// Builds native/www (the Capacitor webDir) from the repo's live web files.
// The web app stays a zero-build static site; this script is the ONLY step
// between "edit Index.html" and "same code runs in the Android/iOS shell".
//
// Include-list, not exclude-list: the repo root also holds ops docs, ETL
// scripts, SQL migrations and local QA harnesses that must never ship inside
// the app binary. Anything new the app needs at runtime must be added here.
//
// Deliberately EXCLUDED from the bundle:
//   sw.js            — native builds must not register the service worker
//                      (assets are on-device; Index.html also guards this).
//   scanner/ models  — ~16 MB of ONNX weights for an admin-gated feature.
//   vendor/ort/      — onnxruntime WASM, only the scanner workers load it.
//   _redirects/_headers, og-image, robots, sitemap — Netlify/crawler-only.
import { cpSync, mkdirSync, rmSync, readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const out = join(repo, "native", "www");

const FILES = [
  ["Index.html", "index.html"], // Capacitor's local server wants lowercase index.html
  "styles.css",
  "logo.js",
  "scanner.js",
  "scanner-cv.js",
  "scanner-worker.js",
  "scanner-ocr-worker.js",
  "manifest.json",
  "privacy.html",
  "favicon-32.png",
  "favicon-64.png",
  "icon-192.png",
  "icon-512.png",
  "apple-touch-icon.png",
];
const DIRS = [
  ["vendor", { exclude: ["ort"] }],
  ["Logos", {}],
];

// Guard: the native shims in Index.html are what make the bundled app work
// (skip SW, absolutize /img-proxy, packs.ink share links). If a refactor ever
// drops them, fail the sync loudly instead of shipping a silently broken app.
const indexSrc = readFileSync(join(repo, "Index.html"), "utf8");
for (const marker of ["IS_NATIVE_APP", "PROXY_ORIGIN", "SITE_ORIGIN"]) {
  if (!indexSrc.includes(marker)) {
    console.error(`sync.mjs: Index.html lost the ${marker} native shim — refusing to build.`);
    process.exit(1);
  }
}

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

for (const entry of FILES) {
  const [src, dst] = Array.isArray(entry) ? entry : [entry, entry];
  const from = join(repo, src);
  if (!existsSync(from)) { console.warn(`sync.mjs: missing ${src} (skipped)`); continue; }
  cpSync(from, join(out, dst));
}

for (const [dir, opts] of DIRS) {
  const from = join(repo, dir);
  if (!existsSync(from)) { console.warn(`sync.mjs: missing ${dir}/ (skipped)`); continue; }
  const excl = (opts.exclude || []).map((e) => join(from, e));
  cpSync(from, join(out, dir), {
    recursive: true,
    filter: (src) => !excl.some((e) => src === e || src.startsWith(e + "\\") || src.startsWith(e + "/")),
  });
}

let bytes = 0, count = 0;
const walk = (d) => {
  for (const ent of readdirSync(d, { withFileTypes: true })) {
    const p = join(d, ent.name);
    if (ent.isDirectory()) walk(p);
    else { bytes += statSync(p).size; count++; }
  }
};
walk(out);
console.log(`sync.mjs: built native/www — ${count} files, ${(bytes / 1024 / 1024).toFixed(1)} MB`);
