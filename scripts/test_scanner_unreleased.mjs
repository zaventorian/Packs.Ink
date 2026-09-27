// Guard: a card whose set is not out yet cannot win a scan on its name alone.
//
//   node scripts/test_scanner_unreleased.mjs
//
// text.json carries `d` (the set's release date) only for sets unreleased at build
// time, and scanner.js compares it to the browser's own date (or loadText's
// opts.asOf). Before that date the card sorts behind every released printing AND
// loses UNRELEASED_PENALTY off its single-line score, so a name-only read of a card
// in hand is not answered with a new set's namesake. Genuine evidence for the new
// card (its version subtitle, one line or two) must still win - an early copy is a
// real thing - and on release day the whole rule has to switch itself off.
//
// Runs the REAL scanner.js over a synthetic catalog, offline.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "scanner.js"), "utf8");

// The exact pair that motivated the rule: two Lexingtons, one released, one in
// Hyperia City (set 14, out 2026-10-16), plus an unreleased REPRINT of a released
// card (same name AND version) and a brand-new character with no released sibling.
const CATALOG = [
  { id: "lex_new", n: "Lexington", v: "Fearless Flier", b: "lexington fearless flier", s: "14", cn: "38", r: "C", d: "2026-10-16" },
  { id: "lex_old", n: "Lexington", v: "Small in Stature", b: "lexington small in stature", s: "10", cn: "183", r: "U" },
  { id: "potts_cc2", n: "Mrs. Potts", v: "Enchanted Teapot", b: "mrs potts enchanted teapot", s: "CC2", cn: "2", r: "P", d: "2026-10-01" },
  { id: "potts_old", n: "Mrs. Potts", v: "Enchanted Teapot", b: "mrs potts enchanted teapot", s: "2", cn: "147", r: "R" },
  { id: "newbie", n: "Glimmerwick", v: "Lantern Keeper", b: "glimmerwick lantern keeper", s: "14", cn: "90", r: "R", d: "2026-10-16" },
  { id: "filler", n: "Maui", v: "Hero to All", b: "maui hero to all", s: "1", cn: "114", r: "R" },
];

function freshScanner() {
  const win = {};
  const fetchStub = () => Promise.resolve({ json: () => Promise.resolve(JSON.parse(JSON.stringify(CATALOG))) });
  new Function("window", "document", "fetch", SRC)(win, { createElement: () => ({ getContext: () => ({}) }) }, fetchStub);
  return win.CardScanner;
}

let fails = 0;
const check = (cond, msg) => { console.log((cond ? "  ok    " : "  FAIL  ") + msg); if (!cond) fails++; };
const topOf = (CS, lines) => { const r = CS.rankNames(lines, 6); return r.top[0] ? r.top[0].id : null; };
const scoreOf = (CS, lines, id) => { const r = CS.rankNames(lines, 6); const h = r.top.find(x => x.id === id); return h ? h.score : null; };

// Before release.
{
  const CS = freshScanner();
  await CS.loadText({ asOf: "2026-09-26" });
  check(topOf(CS, ["LEXINGTON"]) === "lex_old", "before release, a bare name read answers the released card");
  check(topOf(CS, ["EXINGION", "naaStalte"]) === "lex_old", "before release, a garbled name read answers the released card");
  check(topOf(CS, ["LEXINGTON FEARLESS FLIER"]) === "lex_new", "before release, a one-line read naming the new version still finds it");
  check(topOf(CS, ["LEXINGTON", "Fearless Flier"]) === "lex_new", "before release, a two-line read naming the new version still finds it");
  check(topOf(CS, ["MRS POTTS ENCHANTED TEAPOT"]) === "potts_old", "before release, an unreleased reprint loses the exact tie to the released printing");
  check(topOf(CS, ["GLIMMERWICK"]) === "newbie", "before release, a new character with no released namesake is still found");
  const t = await CS.loadText();
  const lexNew = t.cards.find(c => c.id === "lex_new"), lexOld = t.cards.find(c => c.id === "lex_old");
  check(lexNew._unrel === true && lexOld._unrel === false, "the release date marks only the unreleased card");
  check(t.cards.indexOf(lexOld) < t.cards.indexOf(lexNew), "an unreleased card sorts behind the released one");
}

// On release day the rule switches itself off, with no rebuild.
{
  const before = freshScanner(); await before.loadText({ asOf: "2026-10-15" });
  const after = freshScanner(); await after.loadText({ asOf: "2026-10-16" });
  const s0 = scoreOf(before, ["LEXINGTON FEARLESS FLIER"], "lex_new");
  const s1 = scoreOf(after, ["LEXINGTON FEARLESS FLIER"], "lex_new");
  check(s0 != null && s1 != null && s1 - s0 > 0.09, `the penalty lapses on the release date itself (${s0 && s0.toFixed(3)} -> ${s1 && s1.toFixed(3)})`);
  const t = await after.loadText();
  check(!t.cards.some(c => c._unrel), "nothing is marked unreleased on or after its date");
}

// A card with no `d` (every released set, and any text.json older than v6) is never touched.
{
  const CS = freshScanner(); await CS.loadText({ asOf: "2000-01-01" });
  const t = await CS.loadText();
  check(t.cards.filter(c => c._unrel).map(c => c.id).sort().join(",") === "lex_new,newbie,potts_cc2",
    "only cards carrying `d` can ever be demoted");
}

console.log(fails ? `\n${fails} failed` : "\nall passed");
process.exit(fails ? 1 : 0);
