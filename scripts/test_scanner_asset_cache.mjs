// Guard: the scanner's deploy-surviving cache can never serve stale bytes.
//
//   node scripts/test_scanner_asset_cache.mjs            check (CI runs this)
//   node scripts/test_scanner_asset_cache.mjs --update   re-record after a version bump
//
// sw.js keeps the scanner's models, wasm, OpenCV and card indexes in SCAN_CACHE,
// which SURVIVES deploys and serves cache-first by exact URL. That is only safe
// while no file changes content under a URL it is already cached at, so every
// file there belongs to a VERSION GROUP whose bytes may change only when the
// group's version does:
//
//   heavy — sw.js SCAN_CACHE — the OCR models + keys, vendor/ort, vendor/opencv
//   index — scanner.js IDXV  — index.json, color.bin, dhash.bin (rows align)
//   text  — scanner.js TXTV  — text.json
//
// Forget the bump and every returning scanner user keeps the old bytes, silently
// and for good: a rebuilt index never arrives, or — worse — a new color.bin is
// read against an old index.json and every colour row is off by the inserts.
// scripts/scanner/asset_versions.json records each group's version and hashes.
// --update refuses to re-record a group whose bytes changed under an unchanged
// version, so the manifest cannot be used to bless the very mistake it catches.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..");
const MANIFEST = path.join(REPO, "scripts", "scanner", "asset_versions.json");
const UPDATE = process.argv.includes("--update");
const read = (f) => fs.readFileSync(path.join(REPO, f), "utf8");

let fails = 0;
const check = (cond, msg) => { console.log((cond ? "  ok    " : "  FAIL  ") + msg); if (!cond) fails++; };

const SW = read("sw.js"), SCANNER = read("scanner.js");
const grab = (src, re, what) => { const m = src.match(re); if (!m) { console.error(`could not find ${what}`); process.exit(1); } return m[1]; };
const versions = {
  heavy: grab(SW, /const SCAN_CACHE = '([^']+)';/, "SCAN_CACHE in sw.js"),
  index: grab(SCANNER, /var IDXV = "([^"]+)";/, "IDXV in scanner.js"),
  text: grab(SCANNER, /var TXTV = "([^"]+)";/, "TXTV in scanner.js"),
};
const VERSION_OF = { heavy: "SCAN_CACHE in sw.js", index: "IDXV in scanner.js", text: "TXTV in scanner.js" };
const GROUP_OF_INDEX = { "scanner/index.json": "index", "scanner/color.bin": "index", "scanner/dhash.bin": "index", "scanner/text.json": "text" };
const DIRS = ["scanner", "vendor/ort", "vendor/opencv"];

// ---- the service worker actually routes these files through SCAN_CACHE -------
const reSrc = grab(SW, /const SCAN_ASSET_RE = (\/.+\/);/, "SCAN_ASSET_RE in sw.js");
const SCAN_ASSET_RE = new Function(`return ${reSrc};`)();
check(/k !== SCAN_CACHE/.test(SW), "activate keeps SCAN_CACHE across deploys (or it is not persistent at all)");
check(/caches\.open\(SCAN_CACHE\)/.test(SW) && /SCAN_ASSET_RE\.test\(url\.pathname\)/.test(SW), "the fetch handler serves SCAN_ASSET_RE paths out of SCAN_CACHE");
check(/text\/html/.test(SW.slice(SW.indexOf("caches.open(SCAN_CACHE)"), SW.indexOf("caches.open(SCAN_CACHE)") + 900)),
  "SCAN_CACHE refuses an HTML body (the SPA fallback for a missing file)");
for (const p of ["/scanner.js", "/scanner-worker.js", "/scanner-ocr-worker.js", "/scanner-cv.js"])
  check(!SCAN_ASSET_RE.test(p), `${p} stays OUT of the persistent cache (network-first with Index.html)`);

// ---- every index URL carries its version -----------------------------------
for (const [f, v] of [["index.json", "IDXV"], ["color.bin", "IDXV"], ["dhash.bin", "IDXV"], ["text.json", "TXTV"]])
  check(new RegExp(`"${f.replace(".", "\\.")}" \\+ ${v}`).test(SCANNER), `scanner.js fetches ${f} with ?v= from ${v} (an unversioned index would be cached forever)`);

// ---- hash the tree ------------------------------------------------------------
// ⚠ Text files hash with CRLF folded to LF. core.autocrlf is on for Windows
// clones, so vendor/ort/*.js and ppocr_keys_v1.txt sit in THIS working tree as
// CRLF while CI checks out the committed LF bytes: a raw hash recorded on one
// fails on the other, which is a guard nobody can trust. Git's own rule decides
// text vs binary (a NUL byte in the first 8000 bytes), so the .onnx/.wasm/.bin
// files still hash raw. Which line endings a deploy serves is not a change of
// substance: the bytes mean the same thing either way.
const isBinary = (buf) => buf.subarray(0, 8000).includes(0);
const digest = (buf) => crypto.createHash("sha256")
  .update(isBinary(buf) ? buf : Buffer.from(buf.toString("latin1").replace(/\r\n/g, "\n"), "latin1"))
  .digest("hex");
check(digest(Buffer.from("a\r\nb\r\n")) === digest(Buffer.from("a\nb\n")), "a text file hashes the same with CRLF or LF endings");
check(digest(Buffer.from("a\r\nb\u0000")) !== digest(Buffer.from("a\nb\u0000")), "a binary file hashes its raw bytes");
check(digest(Buffer.from("a\rb")) !== digest(Buffer.from("ab")), "a lone CR is content, never folded away");
const files = [];
for (const d of DIRS) {
  const abs = path.join(REPO, d);
  if (!fs.existsSync(abs)) continue;
  for (const f of fs.readdirSync(abs)) if (fs.statSync(path.join(abs, f)).isFile()) files.push(`${d}/${f}`);
}
files.sort();
const current = { heavy: {}, index: {}, text: {} };
for (const f of files) {
  check(SCAN_ASSET_RE.test("/" + f), `/${f} is routed into SCAN_CACHE`);
  const g = GROUP_OF_INDEX[f] || "heavy";
  current[g][f] = digest(fs.readFileSync(path.join(REPO, f)));
}
check(files.includes("vendor/opencv/opencv.js"), "OpenCV is vendored (vendor/opencv/opencv.js)");
check(Object.keys(current.index).length === 3 && Object.keys(current.text).length === 1, "all four index files are present");

const prior = fs.existsSync(MANIFEST) ? JSON.parse(fs.readFileSync(MANIFEST, "utf8")) : null;
const same = (a, b) => JSON.stringify(a || {}) === JSON.stringify(b || {});
const changed = (g) => prior && prior.groups[g] && !same(prior.groups[g].files, current[g]);
const diffList = (g) => {
  const a = (prior && prior.groups[g] && prior.groups[g].files) || {}, b = current[g];
  return [...new Set([...Object.keys(a), ...Object.keys(b)])].filter((k) => a[k] !== b[k]).sort();
};

if (UPDATE) {
  let refused = 0;
  for (const g of Object.keys(current)) {
    if (changed(g) && prior.groups[g].version === versions[g]) {
      console.error(`  REFUSED  ${g}: ${diffList(g).join(", ")} changed but ${VERSION_OF[g]} is still ${versions[g]} — bump it first`);
      refused++;
    }
  }
  if (refused) process.exit(1);
  const out = {
    note: "Recorded by scripts/test_scanner_asset_cache.mjs --update. Each group's bytes may change only when its version does; see sw.js SCAN_CACHE.",
    groups: Object.fromEntries(Object.keys(current).map((g) => [g, { version_of: VERSION_OF[g], version: versions[g], files: current[g] }])),
  };
  fs.writeFileSync(MANIFEST, JSON.stringify(out, null, 1) + "\n");
  console.log(`recorded ${path.relative(REPO, MANIFEST)}: ${files.length} files`);
  for (const g of Object.keys(current)) console.log(`  ${g.padEnd(5)} ${versions[g]}  (${Object.keys(current[g]).length} files)`);
  process.exit(fails ? 1 : 0);
}

// ---- the check ----------------------------------------------------------------
check(!!prior, "scripts/scanner/asset_versions.json exists (create it with --update)");
if (prior) {
  for (const g of Object.keys(current)) {
    const pg = prior.groups[g];
    check(!!pg, `the manifest records the ${g} group`);
    if (!pg) continue;
    if (!same(pg.files, current[g]) && pg.version === versions[g]) {
      check(false, `${g}: ${diffList(g).join(", ")} changed but ${VERSION_OF[g]} is still ${versions[g]} — bump it, then run --update`);
    } else if (pg.version !== versions[g]) {
      check(false, `${g}: ${VERSION_OF[g]} moved ${pg.version} -> ${versions[g]}; re-record with --update`);
    } else {
      check(true, `${g}: ${Object.keys(current[g]).length} files unchanged at ${versions[g]}`);
    }
  }
}

console.log(fails ? `\n${fails} failed` : "\nall passed");
process.exit(fails ? 1 : 0);
