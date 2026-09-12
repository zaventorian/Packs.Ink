// test_brand_art.mjs — guards the official Lorcana art maps in Index.html
// against the files scripts/bake_brand_assets.py actually produced.
//
//     node scripts/test_brand_art.mjs
//
// Two halves of one repo have to agree and neither can tell when they stop:
// a Python manifest that writes files, and a JS map that names them. Both
// failures are silent in the ugliest way — a typo'd path renders a broken image
// that hideBrokenImg politely hides, and an orphaned asset is dead weight in
// every deploy — so this checks BOTH directions.
//
// It matters most at the moment it is easiest to forget. Ravensburger renames
// things between bundle drops ("Set6_Colour" one set, "AzuriteSea-Color" the
// next); the day a new one lands, someone re-runs the bake and this is what
// tells them whether the site still points at what came out.
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url);
const src = readFileSync(new URL("Index.html", ROOT), "utf8");
const repo = new URL(".", ROOT).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const NL = String.fromCharCode(10);

const grab = (a, b) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error("missing marker: " + a);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error("missing end: " + b);
  return src.slice(i, j + b.length);
};
const grabLine = (p) => {
  const l = src.split(/\r?\n/).find((x) => x.startsWith(p));
  if (!l) throw new Error("missing line: " + p);
  return l;
};

const mod = await import("data:text/javascript," + encodeURIComponent([
  grabLine("const INKS = "),
  grab("const INK_ICONS = {", NL + "};"),
  grabLine("const LORCANA_ART = "),
  grab("const LORCANA_SET_ART = {", NL + "};"),
  grab("const lorcanaSetArt = (setName) => {", NL + "};"),
  grab("const inkPairIcon = (inks) => {", NL + "};"),
  grab("const inkShieldSrc = (inks, ink) => {", NL + "};"),
  grab("const PROMO_STAMPS = {", NL + "};"),
  grab("const LORCANA_CARD_GLYPHS = {", NL + "};"),
  grab("const LORCANA_MARKS = {", NL + "};"),
  grab("const MAINLINE_SETS = [", NL + "];"),
  grab("const SET_RELEASE_DATES = {", NL + "};"),
  grab("const PRODUCT_RELEASE_DATES = [", NL + "];"),
  "export {INKS, INK_ICONS, LORCANA_ART, LORCANA_SET_ART, lorcanaSetArt, inkPairIcon,",
  " inkShieldSrc, PROMO_STAMPS, LORCANA_CARD_GLYPHS, LORCANA_MARKS, MAINLINE_SETS,",
  " SET_RELEASE_DATES, PRODUCT_RELEASE_DATES};",
].join(NL)));

const {
  INKS, INK_ICONS, LORCANA_ART, LORCANA_SET_ART, lorcanaSetArt, inkPairIcon,
  inkShieldSrc, PROMO_STAMPS, LORCANA_CARD_GLYPHS, LORCANA_MARKS, MAINLINE_SETS,
  SET_RELEASE_DATES, PRODUCT_RELEASE_DATES,
} = mod;

let failed = 0;
const ok = (name, cond, detail) => {
  if (!cond) failed++;
  console.log((cond ? "PASS  " : "FAIL  ") + name + (cond ? "" : "  → " + (detail ?? "")));
};

// ── Every referenced file exists ────────────────────────────────────────────
const referenced = new Set();
const ref = (p) => { if (p) referenced.add(p.replace(/\\/g, "/")); return p; };
const onDisk = (p) => existsSync(join(repo, p));

for (const [set, v] of Object.entries(LORCANA_SET_ART)) ref(LORCANA_ART + v.src);
for (const p of Object.values(PROMO_STAMPS)) ref(p);
for (const p of Object.values(LORCANA_CARD_GLYPHS)) ref(p);
for (const p of Object.values(LORCANA_MARKS)) ref(p);
for (let i = 0; i < INKS.length; i++)
  for (let j = i + 1; j < INKS.length; j++) ref(inkPairIcon([INKS[i], INKS[j]]));

const missing = [...referenced].filter((p) => !onDisk(p));
ok("every referenced art file exists on disk", missing.length === 0, missing.join(", "));

// ── ...and nothing on disk is unreferenced ──────────────────────────────────
// The half a one-directional check misses. An asset the bake still writes but
// nothing names ships in every deploy forever and is invisible in review.
const walk = (dir, out = []) => {
  for (const name of readdirSync(join(repo, dir))) {
    const rel = dir + "/" + name;
    if (statSync(join(repo, rel)).isDirectory()) walk(rel, out);
    else out.push(rel);
  }
  return out;
};
const baked = walk("Logos/lorcana");
const orphans = baked.filter((p) => !referenced.has(p));
ok("every baked asset is referenced from Index.html", orphans.length === 0, orphans.join(", "));
ok("the bake produced something at all", baked.length > 20, String(baked.length));

// ── Set logos ───────────────────────────────────────────────────────────────
// ⚠ The key IS the set name, and a set name that does not exist can never match
// a row — the logo simply never renders, with no error anywhere.
const strays = Object.keys(LORCANA_SET_ART).filter((s) => !MAINLINE_SETS.includes(s)
  && !Object.prototype.hasOwnProperty.call(SET_RELEASE_DATES, s));
ok("every set-logo key is a real set name", strays.length === 0, strays.join(", "));
ok("every released mainline set has a logo",
  MAINLINE_SETS.every((s) => !!lorcanaSetArt(s)),
  MAINLINE_SETS.filter((s) => !lorcanaSetArt(s)).join(", "));
ok("a set with no logo returns null rather than a broken path",
  lorcanaSetArt("Promo Set 1") === null && lorcanaSetArt(undefined) === null);

// ⚠ mono is The First Chapter and only ever will be: the one set the bundle
// ships as black line art with no colour version. Everything else must NOT be
// mono, or the dark-theme invert turns a full-colour logo into a negative.
const monos = Object.entries(LORCANA_SET_ART).filter(([, v]) => v.mono).map(([k]) => k);
ok("exactly one set logo is the currentColor mono SVG",
  monos.length === 1 && monos[0] === "The First Chapter", monos.join(", "));
ok("the mono logo is an SVG and the rest are not",
  lorcanaSetArt("The First Chapter").src.endsWith(".svg") &&
  Object.entries(LORCANA_SET_ART).filter(([, v]) => !v.mono)
    .every(([, v]) => !v.src.endsWith(".svg")));
// ⚠ And it must NOT be a currentColor SVG. It is shown in an <img>, where
// currentColor does not inherit from the page — it resolves against the SVG
// document's own initial `color`, which is UA-dependent and flips with the
// browser's dark preference. That would make one reader's First Chapter black
// and another's white on the SAME theme, with the invert rule then wrong for
// exactly one of them. Verbatim black plus the invert is deterministic.
ok("the mono set logo is plain black, not currentColor",
  !readFileSync(join(repo, lorcanaSetArt("The First Chapter").src), "utf8")
    .includes("currentColor"));

// ── Ink pairs ───────────────────────────────────────────────────────────────
// ⚠ Lorcast publishes `inks` in the card's PRINT order, which is not
// alphabetical — Sapphire/Amber is a real ordering — and there is exactly one
// file per unordered pair. Getting this wrong 404s about half of all dual-ink
// cards, and only half, which is the kind of bug that reads as a CDN hiccup.
ok("an ink pair resolves the same icon in either order",
  inkPairIcon(["Sapphire", "Amber"]) === inkPairIcon(["Amber", "Sapphire"]));
ok("all 15 unordered ink pairs resolve to distinct files",
  new Set(INKS.flatMap((a, i) => INKS.slice(i + 1).map((b) => inkPairIcon([a, b])))).size === 15);
ok("a non-pair returns null", inkPairIcon(["Amber"]) === null
  && inkPairIcon(["Amber", "Amber"]) === null && inkPairIcon(null) === null
  && inkPairIcon(["Amber", "Emerald", "Ruby"]) === null);

// inkShieldSrc is the one accessor every call site should use: a dual gets its
// pair badge, a single its existing shield, and a card with no ink gets nothing
// rather than a placeholder.
ok("a dual-ink card gets the pair badge",
  inkShieldSrc(["Emerald", "Sapphire"], null) === inkPairIcon(["Emerald", "Sapphire"]));
ok("a single-ink card still gets its existing shield",
  inkShieldSrc(["Amber"], null) === INK_ICONS.Amber
  && inkShieldSrc(null, "Steel") === INK_ICONS.Steel);
ok("a card with no ink gets nothing, not a placeholder",
  inkShieldSrc(null, null) === null && inkShieldSrc([], "") === null);
// An ink name the site does not know (a seventh ink, a typo in a cached row)
// must degrade to nothing rather than to a 404.
ok("an unknown ink degrades to null", inkShieldSrc(["Rainbow"], null) === null);

// ── Promo stamps ────────────────────────────────────────────────────────────
// Keys are SET names here too. A stamp filed under a set that does not exist
// renders for nobody.
const setOrderSrc = grab("const SET_ORDER = [", NL + "];");
const unknownPromo = Object.keys(PROMO_STAMPS)
  .filter((s) => !setOrderSrc.includes(`"${s}"`));
ok("every promo stamp is keyed to a set in SET_ORDER", unknownPromo.length === 0,
  unknownPromo.join(", "));
// C1 and C2 print the same Challenge stamp; everything else is its own mark.
ok("the two Challenge promo sets share one stamp",
  PROMO_STAMPS["Lorcana Challenge Promo (C1)"] === PROMO_STAMPS["Lorcana Challenge Promo (C2)"]);

// ── currentColor ────────────────────────────────────────────────────────────
// ⚠ The whole reason these are SVG. A stamp or glyph that kept its baked-in
// white is invisible on all four light themes and one that kept black is
// invisible on all three dark ones — and in neither case is anything broken,
// missing, or logged. bake_svg_mono is what rewrites them; this is what proves
// it ran.
const monoSvgs = [...Object.values(PROMO_STAMPS), ...Object.values(LORCANA_CARD_GLYPHS)]
  .filter((p) => p.endsWith(".svg"));
const notMono = monoSvgs.filter((p) => {
  const t = readFileSync(join(repo, p), "utf8");
  return !t.includes("currentColor") || /fill\s*[:=]\s*"?(#[0-9a-fA-F]{3,8}|white|black)/.test(t);
});
ok("every mono SVG inherits currentColor and hardcodes no fill",
  notMono.length === 0, notMono.join(", "));
// fill:none is how Illustrator marks a counter — the hole in the inkable hex.
// Rewriting it to currentColor fills that hole in solid.
ok("fill:none survives the rewrite (it is a counter, not a colour)",
  readFileSync(join(repo, LORCANA_CARD_GLYPHS.inkable), "utf8").includes("fill: none"));

// ── Weight ──────────────────────────────────────────────────────────────────
// The bundle is 313 MB of print art. The point of the bake is that almost none
// of it ships; a run that forgot to downscale would sail through every check
// above.
const bytes = baked.reduce((n, p) => n + statSync(join(repo, p)).size, 0);
ok("the whole baked set stays under 1 MB", bytes < 1024 * 1024,
  (bytes / 1024).toFixed(0) + " KB");
const heavy = baked.filter((p) => statSync(join(repo, p)).size > 90 * 1024);
ok("no single asset is over 90 KB", heavy.length === 0, heavy.join(", "));

// ── Dated things the art is about ───────────────────────────────────────────
// SET_RELEASE_DATES is the calendar's source for set rows, so a malformed date
// here is a release that silently never appears. Same for products.
const ymd = /^\d{4}-\d{2}-\d{2}$/;
const badSet = Object.entries(SET_RELEASE_DATES).flatMap(([s, d]) =>
  Object.entries(d).filter(([, v]) => !ymd.test(v)).map(([k]) => `${s}.${k}`));
ok("every set release date is a YYYY-MM-DD", badSet.length === 0, badSet.join(", "));
ok("a set's retail date is never before its LGS date",
  Object.entries(SET_RELEASE_DATES).every(([, d]) => !d.lgs || !d.retail || d.retail >= d.lgs),
  Object.entries(SET_RELEASE_DATES).filter(([, d]) => d.lgs && d.retail && d.retail < d.lgs)
    .map(([s]) => s).join(", "));
const badProd = PRODUCT_RELEASE_DATES.filter((p) => !p.title || !ymd.test(p.on || ""));
ok("every product release date is a YYYY-MM-DD", badProd.length === 0,
  badProd.map((p) => p.title).join(", "));
// A derived product's id is `product:<title>`, and the merge keys on the title —
// so two entries sharing one would collapse into a single row with no warning.
ok("no two products share a title",
  new Set(PRODUCT_RELEASE_DATES.map((p) => p.title.toLowerCase())).size
    === PRODUCT_RELEASE_DATES.length);

console.log(failed ? `${NL}${failed} FAILED` : `${NL}all brand-art checks passed`);
process.exit(failed ? 1 : 0);
