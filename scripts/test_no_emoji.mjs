// No emoji in the UI - including the ones that don't LOOK like emoji.
//
// The site draws every pictograph as an SVG (uiIcon, UI_ICON_PATHS in
// Index.html). The trap this guards is the character that reads as plain type
// in the source but is EMOJI-CAPABLE in Unicode: the up-right arrow after
// every outbound link, the undo arrow, the play triangle, the warning sign.
// The page font (Nunito Sans, latin subset) carries none of them, so the
// browser falls back to another font for the glyph, and on an iPhone that
// fallback is Apple Color Emoji: "Buy on TCGplayer" came out with a blue
// sticker tile on the end (reported 2026-09-27, from a phone, 52 of them).
// Nothing errors and it looks fine on the desktop you wrote it on.
//
// So: any code point with the Unicode Emoji or Extended_Pictographic property,
// anywhere outside a comment, in a file the site serves, fails this test. The
// only exceptions are (c) (R) (TM), which ARE in the font and so never fall
// back. Comments may say whatever they like - they are documentation.
//
//   node scripts/test_no_emoji.mjs

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// Every text file the Worker serves that renders UI. build_dist.mjs is the
// include-list; these are the ones that hold markup, copy or styles.
const FILES = ["Index.html", "styles.css", "picks.html", "ticker.html", "swiss.html",
  "privacy.html", "logo.js", "box.html"];

// In Nunito Sans's latin subset, so the page font draws them as type.
const ALLOWED = new Set([0x00a9, 0x00ae, 0x2122]);
// Joiners and presentation selectors carry no glyph of their own.
const INVISIBLE = new Set([0x200d, 0xfe0e, 0xfe0f]);

const EMOJI = /[\p{Emoji}\p{Extended_Pictographic}]/u;

let passed = 0, failed = 0;
const check = (ok, msg) => {
  if (ok) passed++;
  else { failed++; console.log("FAIL  " + msg); }
};

// Blank out comments but keep every newline, so a hit still reports the line
// it is really on. Block comments cover `${/* ... */""}` inside htm templates
// too. A line comment only starts at `//` that is not part of a URL (`://`),
// not straight after a quote and not escaped inside a regex.
// ⚠ ONE left-to-right pass over all three comment kinds, so whichever starts
// first wins. Stripping block comments first reads the `/*` in a LINE comment
// such as "// proxied to /img-proxy/* at the boundary" as an opener and blanks
// everything up to the next `*/` - 1,900 lines of Index.html, including two
// real emoji this test exists to catch.
// ⚠ A block opener must not follow a letter, quote or slash: the `/*` in
// accept="image/*" read as one and hid ~840 lines of Index.html (2026-10-06).
const blank = (m) => m.replace(/[^\n]/g, " ");
const stripComments = (src, isCss) => isCss
  ? src.replace(/\/\*[\s\S]*?\*\//g, blank)
  : src.replace(/(?<![:"'`\\])\/\/[^\n]*|(?<![\w"'/])\/\*[\s\S]*?\*\/|<!--[\s\S]*?-->/g, blank);

const scan = (src, isCss) => {
  const hits = [];
  const lines = stripComments(src, isCss).split("\n");
  lines.forEach((ln, i) => {
    for (const ch of ln) {
      const cp = ch.codePointAt(0);
      if (cp < 0x80 || ALLOWED.has(cp) || INVISIBLE.has(cp)) continue;
      if (EMOJI.test(ch)) hits.push({ line: i + 1, ch, cp });
    }
  });
  return hits;
};

// -- The scanner itself: a scan that finds nothing is only meaningful if it
// can find something. Planted cases, both directions.
const U = (cp) => String.fromCodePoint(cp);
const planted = [
  "<a>Buy on TCGplayer " + U(0x2197) + "</a>",                        // 1 up-right arrow
  "const s = \"" + U(0x21a9) + " Reopen\";",                         // 2 undo arrow
  "  // a comment may say " + U(0x2197) + " freely",
  "x = 1; // trailing comment " + U(0x26a0),
  "${/* " + U(0x26a0) + " inside an htm comment */\"\"}",
  "<!-- " + U(0x1f512) + " -->",
  "<p>" + U(0x00a9) + " OpenStreetMap contributors</p>",
  "const u = \"https://example.test/" + U(0x25b6) + "\";",           // 8 play triangle after a URL
  "<span>" + U(0x2728) + "</span>",                                  // 9 sparkles
  "// proxied to /img-proxy/* at the boundary",                      // a /* inside a LINE comment...
  "<b>" + U(0x23f1) + "</b>",                                        // 11 ...must not hide this line
  "x = 2; /* a later block comment closes here */",
  "<input accept=\"image/*\"/>",                                      // 13 a /* in an attribute...
  "<i>" + U(0x2728) + "</i>",                                        // 14 ...must not hide this line
  "y = 3; /* a real block comment after it */",
].join("\n");
const ph = scan(planted, false);
check(ph.length === 6, "planted sample: expected 6 hits, got " + ph.length +
  " (" + ph.map(h => "line " + h.line + " U+" + h.cp.toString(16)).join(", ") + ")");
check(JSON.stringify(ph.map(h => h.line)) === JSON.stringify([1, 2, 8, 9, 11, 14]),
  "planted sample: hits on lines 1, 2, 8, 9, 11, 14 only (comments and (c) skipped), got " +
  ph.map(h => h.line).join(","));
check(scan("a{content:\"" + U(0x2197) + "\"} /* " + U(0x2197) + " */", true).length === 1,
  "CSS: a glyph in content: is caught, one in a comment is not");

// -- The real files.
for (const f of FILES) {
  const p = path.join(ROOT, f);
  if (!fs.existsSync(p)) { check(false, f + " is missing"); continue; }
  const src = fs.readFileSync(p, "utf8");
  check(src.length > 1000, f + " was read (" + src.length + " chars)");
  const hits = scan(src, f.endsWith(".css"));
  check(hits.length === 0, f + ": " + hits.length + " emoji-capable character(s) outside comments:\n" +
    hits.slice(0, 20).map(h => "        line " + h.line + "  " + h.ch + "  U+" +
      h.cp.toString(16).toUpperCase().padStart(4, "0")).join("\n") +
    "\n      Draw it: uiIcon(key) in Index.html (extIcon() for the outbound-link arrow).");
}

// -- The replacement exists, so the advice above is real.
const html = fs.readFileSync(path.join(ROOT, "Index.html"), "utf8");
check(/\n\s*ext:\s*_icoSvg\(/.test(html), "UI_ICON_PATHS carries the `ext` arrow");
check(/const extIcon = \(\) => uiIcon\("ext", "1em"\);/.test(html), "extIcon() is defined, sized in em");
check((html.match(/\$\{extIcon\(\)\}/g) || []).length >= 50, "outbound links draw the arrow with extIcon()");

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
