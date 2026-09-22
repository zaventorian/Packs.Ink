// test_graded_pop.mjs — guards the PSA population join and its derived reads.
//
//     node scripts/test_graded_pop.mjs
//
// Extracts the real functions out of Index.html, house pattern, so they cannot
// drift from what ships.
//
// Every failure here is SILENT. A wrong set alias attributes one set's pops to
// another and renders a perfectly confident number. A name fold that stops
// folding drops a card's population to "no data" — which looks exactly like a
// card PSA has never graded. A gem rate computed off the wrong denominator is
// still a plausible percentage. None of it throws.
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
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

// searchNorm is the real one — popNameKey is built on top of it, and the whole
// point of the fold is that the two compose.
const mod = await import("data:text/javascript," + encodeURIComponent([
  grab("const searchNorm = (s) => (s||\"\")", ";"),
  grabLine("const popNameKey = ").replace("const popNameKey = ", "const popNameKey = ")
    + NL + "  .replace(/[^a-z0-9]+/g, \" \").trim();",
  grab("const POP_SET_ALIASES = [", NL + "];"),
  grab("const popSetName = (label) => {", NL + "};"),
  grabLine("const popCardKey = ") + NL
    + "  popNameKey(setName) + \"|\" + popNameKey(productName) + \"|\" + String(cn == null ? \"\" : cn).trim();",
  grabLine("const POP_FOIL_VARIETY = "),
  grabLine("const POP_NONFOIL_VARIETY = "),
  grab("const gradedPopBucket = (variety) => {", NL + "};"),
  grab("const gradedPopStats = (row) => {", NL + "};"),
  grab("const POP_SORT_FIELD = {", NL + "};"),
  // gradedPopPick maps an owned/rollup printing through gradedSlotBucket, so
  // the real one comes along — a stub would let the two vocabularies drift.
  grabLine("const GRADED_FOIL_PRINTINGS = "),
  grabLine("const GRADED_NONFOIL_PRINTINGS = "),
  grab("const gradedSlotBucket = (p) => {", NL + "};"),
  grab("const gradedPopPick = (rows, printing) => {", NL + "};"),
  "export {popNameKey, popSetName, popCardKey, gradedPopBucket, gradedPopStats,"
  + " POP_SET_ALIASES, POP_SORT_FIELD, gradedPopPick};",
].join(NL)));

const { popNameKey, popSetName, popCardKey, gradedPopBucket, gradedPopStats,
        POP_SORT_FIELD, gradedPopPick } = mod;
const SRC = src;

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else { fail++; console.log("  FAIL: " + m); } };
const eq = (a, b, m) => ok(a === b, `${m} (got ${JSON.stringify(a)}, want ${JSON.stringify(b)})`);
const section = (s) => console.log("\n" + s);

// 1. The name fold — all four differences are real and measured
section("1. popNameKey folds PSA's spelling onto ours");
{
  // Each pair is a REAL disagreement found in the pulled data. Together they
  // take The First Chapter from 142/146 to 146/146.
  const pairs = [
    ["DR. Facilier - Agent Provocateur", "Dr. Facilier - Agent Provocateur", "case"],
    ["Ariel - on Human Legs", "Ariel - On Human Legs", "case mid-phrase"],
    ["Belle - Strange But Special", "Belle - Strange but Special", "case mid-phrase"],
    ["Cruella de Vil - Miserable As Usual", "Cruella De Vil - Miserable As Usual", "case"],
    ["TE KA - the Burning One", "Te Kā - The Burning One", "diacritic"],
    ["Iago - Loud Mouthed Parrot", "Iago - Loud-Mouthed Parrot", "punctuation"],
    ["Jafar  - Keeper of Secrets", "Jafar - Keeper of Secrets", "double space"],
    ["Ursula  - Power Hungry", "Ursula - Power Hungry", "double space"],
    ["Dr. Facilier's Cards", "Dr. Facilier’s Cards", "curly apostrophe"],
    ["Aladdin-Misleading Phantom", "Aladdin - Misleading Phantom", "missing spaces"],
  ];
  for (const [psa, ours, why] of pairs)
    eq(popNameKey(psa), popNameKey(ours), `${why}: ${psa}`);

  // ...and it must NOT fold two genuinely different cards together.
  ok(popNameKey("Ariel - On Human Legs") !== popNameKey("Ariel - Spectacular Singer"),
     "different versions of one character stay distinct");
  ok(popNameKey("Elsa - Snow Queen") !== popNameKey("Elsa - Spirit of Winter"),
     "two Elsas stay distinct");
  eq(popNameKey(null), "", "null is empty, not a crash");
  eq(popNameKey(""), "", "empty is empty");
}

// 2. Set aliases
section("2. popSetName");
{
  // Mainline parses generically off the dash, so a new set needs no edit.
  eq(popSetName("Disney Lorcana EN 5-Shimmering Skies"), "Shimmering Skies", "mainline");
  eq(popSetName("Disney Lorcana EN 13-Attack of the Vine!"), "Attack of the Vine!", "mainline w/ punctuation");
  eq(popSetName("Disney Lorcana EN 1-the First Chapter"), "the First Chapter", "mainline (case folds at key time)");
  ok(popNameKey(popSetName("Disney Lorcana EN 1-the First Chapter")) === popNameKey("The First Chapter"),
     "...and keys equal to our spelling");

  // The Demo Deck is a PROVENANCE, not a set: every one of its 35 rows is a
  // First Chapter card. Mapping it anywhere else loses all of them.
  eq(popSetName("Disney Lorcana EN 1-Demo Deck"), "The First Chapter", "Demo Deck folds into TFC");

  eq(popSetName("Disney Lorcana EN P1-Promo"), "Promo Set 1", "P1");
  eq(popSetName("Disney Lorcana EN P3-Promo"), "Promo Set 3", "P3");
  eq(popSetName("Disney Lorcana EN PD1-Promo"), "PD1", "PD1");
  // ⚠ Targets are DISPLAY names — the standing rule for every in-code set test.
  eq(popSetName("Disney Lorcana EN C1-Lorcana Challenge Promo"), "Lorcana Challenge Promo (C1)", "C1 display name");
  eq(popSetName("Disney Lorcana EN C2-Lorcana Challenge Promo"), "Lorcana Challenge Promo (C2)", "C2 display name");
  eq(popSetName("Disney Lorcana EN Dis-Magical Places Promo"), "Magical Places Promos", "EPCOT -> its display name");
  eq(popSetName("Disney Lorcana EN D23-D23 Expo Promo"), "D23 Collection", "D23 by prefix");
  eq(popSetName("Disney Lorcana EN D23-D23: the Official Disney Fan Club Promo"), "D23 Collection", "the other D23 label");
  eq(popSetName("Disney Lorcana EN CC1-Curator's Collection: Heroines Edition"),
     "Curator's Collection: Heroines", "CC1 by prefix, PSA's suffix ignored");

  // ⚠ PD1 must not be eaten by the P1 prefix, and P1 must not eat PD1.
  ok(popSetName("Disney Lorcana EN PD1-Promo") !== "Promo Set 1", "PD1 is not Promo Set 1");

  // ⚠ The two Quest headings use a SPACE where every other label uses a dash,
  // so the generic split returns null and their 40 rows disappear silently.
  eq(popSetName("Disney Lorcana EN Q1 Illuminers Quest Deep Trouble"), "Extras & Oddities", "Q1 Deep Trouble");
  eq(popSetName("Disney Lorcana EN Q2 Illuminers Quest Palace Heist"), "Extras & Oddities", "Q2 Palace Heist");
  // PSA spells it "Illuminers"; a fix on their side must not break the match.
  eq(popSetName("Disney Lorcana EN Q1 Illumineer's Quest Deep Trouble"), "Extras & Oddities",
     "...and still maps if PSA corrects its own spelling");

  ok(popSetName("Pokemon EX Ruby & Sapphire") === null, "a non-Lorcana label is null");
  ok(popSetName("") === null && popSetName(null) === null, "empty is null, not a crash");
}

// 3. The set belongs in the key
section("3. popCardKey");
{
  // Reprint sets share a name AND a collector number with what they reprint —
  // measured on the real pull, Fabled collides with Into the Inklands on 8
  // cards. Without the set, one set's pops land on another's card.
  const a = popCardKey("Into the Inklands", "Tinker Bell - Giant Fairy", "1");
  const b = popCardKey("Fabled", "Tinker Bell - Giant Fairy", "1");
  ok(a !== b, "same card+number in two sets keys differently");
  eq(popCardKey("The First Chapter", "Ariel - On Human Legs", "1"),
     popCardKey("the first chapter", "ARIEL - on human legs", "1"),
     "the key is fold-insensitive on both set and name");
  eq(popCardKey("X", "Y", null), popCardKey("X", "Y", ""), "a missing number is empty, not 'null'");
  ok(popCardKey("X", "Y", " 12 ").endsWith("|12"), "the number is trimmed");
}

// 4. Variety -> printing, and the half that must stay unmapped
section("4. gradedPopBucket");
{
  eq(gradedPopBucket(""), "Non-Foil", "no variety is the base printing");
  eq(gradedPopBucket("Foil"), "Foil", "Foil");
  eq(gradedPopBucket("Foil-Errata"), "Foil", "the foil errata is still foil");
  eq(gradedPopBucket("Errata"), "Non-Foil", "the plain errata is non-foil");
  // ⚠ The C1 split is the one worth $1,400 — Cinderella PSA 10 is $1,707 as a
  // Top Prize foil and $280 as a Prize Wall non-foil.
  eq(gradedPopBucket("Top Prize"), "Foil", "C1 Top Prize is the foil side");
  eq(gradedPopBucket("Prize Wall Exclusive"), "Non-Foil", "C1 Prize Wall is the non-foil side");
  eq(gradedPopBucket("FOIL"), "Foil", "case does not matter");

  // ⚠ Rarity and provenance are NOT printings. Forcing them into a bucket is
  // how a League Promo's pops end up counted as a base card's non-foil.
  for (const v of ["Enchanted", "Epic", "Iconic", "League Promo", "Disney Cruise",
                   "D23 Collection", "Top 8", "Fabled Set Championship Prize"])
    eq(gradedPopBucket(v), null, `${v} is not a printing`);
}

// 5. The derived reads
section("5. gradedPopStats");
{
  // Real numbers: The First Chapter #1 Ariel - on Human Legs, non-foil.
  const ariel = gradedPopStats({
    total: 93, pop_10: 73, pop_9: 18,
    grades: { "4": 1, "7": 1, "9": 18, "10": 73, gradeTotal: 93 },
  });
  eq(ariel.total, 93, "total");
  eq(ariel.ten, 73, "PSA 10 population");
  ok(Math.abs(ariel.gemRate - 73 / 93) < 1e-9, "gem rate is 10s over everything graded");
  // The slab read: what exists ABOVE the grade you hold.
  eq(ariel.popHigher(10), 0, "nothing is higher than a 10");
  eq(ariel.popHigher(9), 73, "a 9 has every 10 above it");
  eq(ariel.popHigher(8), 91, "an 8 has the 9s and 10s above it");
  // ⚠ 93, not 92: PSA has graded no copy of this card AT grade 1, so every one
  // of the 93 is above it. "Everything except your own grade" is only the same
  // number when your grade actually has a population.
  eq(ariel.popHigher(1), 93, "nothing sits at grade 1, so all 93 are above it");

  // Half grades and qualifiers are real and are NOT gem-rate numerator.
  const q = gradedPopStats({
    total: 100, pop_10: 40, pop_9: 30,
    grades: { "9": 30, "9.5": 5, "9Q": 3, "10": 40, "8": 22 },
  });
  eq(q.half, 5, "half grades are counted");
  eq(q.qualified, 3, "qualifier counts are counted");
  ok(Math.abs(q.gemRate - 0.40) < 1e-9, "a qualified 9 does not inflate the gem rate");
  // ⚠ A qualifier key must not be read as a grade — "9Q" is not grade 9.
  eq(q.popHigher(9), 45, "only straight and half grades above 9 count as higher");

  // The per-grade table the panel renders.
  const bd = gradedPopStats({
    total: 754, pop_10: 659, pop_9: 82,
    grades: { auth: 1, "6": 1, "7": 2, "8": 9, "9": 82, "10": 659, "3": 0, gradeTotal: 754 },
  }).breakdown;
  eq(bd.map((b) => b.label).join(","), "10,9,8,7,6,Auth", "highest grade first, Auth last");
  eq(bd.reduce((n, b) => n + b.n, 0), 754, "the rows account for every graded copy");
  // ⚠ Zero-population grades are dropped: eleven empty rows bury the four that
  // carry the card, and "no copies at grade 3" is not why anyone opened this.
  ok(!bd.some((b) => b.n === 0), "grades nobody owns are not rows");
  ok(!bd.some((b) => b.key === "gradeTotal"), "the totals are not mistaken for a grade");

  // ⚠ A qualifier sorts directly UNDER its straight grade, never merged into it
  // and never floated to the end — it is a different product at the same number.
  const qb = gradedPopStats({
    total: 60, pop_10: 30, pop_9: 20,
    grades: { "10": 30, "9.5": 5, "9": 20, "9Q": 4, "10Q": 1 },
  }).breakdown;
  eq(qb.map((b) => b.label).join(","), "10,10 Q,9.5,9,9 Q", "qualifiers follow their own grade");
  ok(qb.find((b) => b.label === "9 Q").qual === true, "a qualifier row is flagged");
  ok(qb.find((b) => b.label === "9").qual === false, "a straight grade is not");
  eq(qb.find((b) => b.label === "9.5").grade, 9.5, "half grades keep their value");

  // Degenerate input must degrade, never throw.
  ok(gradedPopStats(null) === null, "no row is null");
  eq(gradedPopStats({ total: 5, pop_10: 5, grades: {} }).breakdown.length, 0,
     "no grade detail is an empty table, not a crash");
  const zero = gradedPopStats({ total: 0, pop_10: 0, pop_9: 0, grades: {} });
  eq(zero.gemRate, null, "a card with nothing graded has no gem rate, not 0/0");
  eq(zero.popHigher(9), 0, "and nothing above any grade");
  const noGrades = gradedPopStats({ total: 5, pop_10: 5 });
  ok(noGrades && noGrades.ten === 5, "a missing grades object does not throw");
}

// 6. Optional: replay the real pull, when it is on disk
section("6. real pulled data (skipped when pop_output is empty)");
{
  const dir = new URL("./pop_output/", import.meta.url);
  let files = [];
  try { files = readdirSync(dir).filter((f) => /^psa_pop_\d+_/.test(f)); } catch {}
  if (!files.length) {
    console.log("  (no pulled files — run scripts/psa_pop_pull.mjs to exercise this)");
  } else {
    let sets = 0, unmapped = [];
    const specs = new Set();
    let dupSpec = 0, rows = 0;
    for (const f of files) {
      const d = JSON.parse(readFileSync(new URL(f, dir), "utf8"));
      sets++;
      const mapped = popSetName(d.set.name);
      if (!mapped) unmapped.push(d.set.name);
      for (const r of d.rows) {
        if (!r.CardNumber) continue;
        rows++;
        if (specs.has(r.SpecID)) dupSpec++;
        specs.add(r.SpecID);
        // Every row must produce usable stats without throwing.
        const st = gradedPopStats({ total: r.Total, pop_10: r.Grade10, pop_9: r.Grade9, grades: {} });
        if (!st) { unmapped.push("stats:" + r.SpecID); break; }
      }
    }
    console.log(`  ${sets} pulled sets, ${rows} card rows`);
    ok(unmapped.length === 0, `every pulled set label maps (unmapped: ${unmapped.slice(0, 3)})`);
    ok(dupSpec === 0, `spec_id is unique across sets (${dupSpec} duplicates)`);
    ok(specs.size === rows, "one spec_id per card row");
  }
}

// 7. gradedPopPick — which printing's population you are shown
section("7. gradedPopPick");
{
  const nf = { variety: "", total: 93, pop_10: 73 };
  const fo = { variety: "Foil", total: 150, pop_10: 110 };
  eq(gradedPopPick([], "Foil").row, null, "no rows is no pick");
  eq(gradedPopPick(null, null).row, null, "null is no pick");

  // One printing needs no label — there was no choice to report.
  const one = gradedPopPick([nf], null);
  eq(one.row, nf, "a single row is the pick");
  eq(one.label, null, "and carries no label");

  // ⚠ It must never SUM. Non-Foil and Foil are different markets — the C1
  // split is $1,707 against $280 — so one number across both describes neither.
  const pickFoil = gradedPopPick([nf, fo], "Foil");
  eq(pickFoil.row, fo, "the foil printing is picked for a foil slab");
  eq(pickFoil.label, "Foil", "and named, because there was a choice");
  eq(gradedPopPick([nf, fo], "Cold Foil").row, fo, "cold foil is foil");
  eq(gradedPopPick([nf, fo], "Holofoil").row, fo, "holofoil is foil");
  eq(gradedPopPick([nf, fo], "Normal").row, nf, "normal is non-foil");
  eq(gradedPopPick([nf, fo], "Non-Foil").row, nf, "non-foil is non-foil");
  eq(gradedPopPick([nf, fo], null).row, fo, "no printing falls back to the biggest");
  eq(gradedPopPick([nf, fo], "Two Swords").row, fo,
     "an unmappable printing falls back to the biggest rather than guessing");
  ok(gradedPopPick([nf, fo], "Foil").row.total !== nf.total + fo.total,
     "the two printings are never summed");
}

// 8. Every Screener pop column can actually be sorted
section("8. POP_SORT_FIELD covers the shipped columns");
{
  // The comparator falls through to r[k]. A column key missing from this map
  // makes every row tie, which on screen reads as "this column does not sort"
  // — no error, no clue. So the map is checked against what actually ships.
  const cols = [...SRC.matchAll(/popCol\("([a-z0-9]+)",\s*"[^"]*",\s*"([a-z0-9_]+)"/g)]
    .map((m) => ({ key: m[1], field: m[2] }));
  ok(cols.length >= 7, `the pop columns were found in Index.html (got ${cols.length})`);
  for (const c of cols) {
    eq(POP_SORT_FIELD[c.key], c.field,
       `column ${c.key} sorts on the field it renders`);
  }
  // The hand-written gem column is not a popCol (it renders a percentage).
  eq(POP_SORT_FIELD.popgem, "pop_gem", "the gem-rate column sorts too");
  ok(SRC.includes('onSort("popgem"'), "...and its header is wired to onSort");
  // Nothing in the map should be dead weight either.
  const keys = new Set(cols.map((c) => c.key).concat("popgem"));
  for (const k of Object.keys(POP_SORT_FIELD)) {
    ok(keys.has(k), `POP_SORT_FIELD.${k} corresponds to a real column`);
  }
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
