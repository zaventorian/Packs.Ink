// test_reveal_rotation.mjs — the new-card reveal reel's window + dedupe rules.
//
// Run: node scripts/test_reveal_rotation.mjs
//
// Why this is guarded: EVERY way this function goes wrong is silent. Too loose
// and the nav quietly announces a bulk backfill of old promos as "just
// revealed"; too tight and a real spoiler wave never appears at all and nobody
// finds out, because an empty reel renders as nothing rather than as an error.
// There is no screen that says "the reel decided you have no new cards".
//
// There is no build step, so rather than importing we slice the module-scope
// declarations out of Index.html and eval them — the house pattern. Renaming
// any sliced declaration breaks this test loudly, by design.
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = fs.readFileSync(path.join(ROOT, "Index.html"), "utf8");

function slice(startRe, endRe, label){
  const s = SRC.search(startRe);
  if(s < 0) throw new Error(`start not found: ${label}`);
  const rest = SRC.slice(s);
  const m = rest.match(endRe);
  if(!m) throw new Error(`end not found: ${label}`);
  return rest.slice(0, rest.search(endRe) + m[0].length);
}

const parts = [
  slice(/^const EXTRAS_SET_NAME = /m, /^const EXTRAS_SET_NAME = .*$/m, "EXTRAS_SET_NAME"),
  slice(/^const REVEAL_WINDOW_HOURS = /m, /^const REVEAL_SECS_PER_CARD = [\d.]+;$/m, "reveal logic"),
];
const mod = new Function(parts.join("\n\n") + `
  return {revealRotation, revealSetLabel, REVEAL_WINDOW_HOURS, REVEAL_MAX_CARDS,
          REVEAL_EXCLUDED_SETS, EXTRAS_SET_NAME};
`)();
const {revealRotation, revealSetLabel, REVEAL_WINDOW_HOURS, REVEAL_MAX_CARDS,
       REVEAL_EXCLUDED_SETS, EXTRAS_SET_NAME} = mod;

let pass = 0, fail = 0;
const eq = (label, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if(g === w){ pass++; return; }
  fail++;
  console.error(`FAIL ${label}\n  got  ${g}\n  want ${w}`);
};
const ok = (label, cond) => eq(label, !!cond, true);

const NOW = Date.parse("2026-09-22T12:00:00Z");
const hoursAgo = (h) => new Date(NOW - h * 36e5).toISOString();
// Minimal row in the shape buildRow emits.
const row = (o = {}) => ({
  card_id: o.card_id ?? "c1",
  "Product Name": o.name ?? "Card One",
  Set: o.set ?? "Hyperia City",
  Number: o.num ?? "1",
  Printing: o.printing ?? "Normal",
  img_normal: "img" in o ? o.img : "https://x/c.png",
  img_large: null, img_small: null,
  added_at: "added_at" in o ? o.added_at : hoursAgo(1),
});
const ids = (cards) => cards.map(c => c.card_id);

// ── the window ──────────────────────────────────────────────────────────────
eq("constants are the documented ones", [REVEAL_WINDOW_HOURS, REVEAL_MAX_CARDS], [96, 36]);
eq("a card added an hour ago is in", ids(revealRotation([row()], NOW)), ["c1"]);
eq("a card added 95h ago is still in",
   ids(revealRotation([row({added_at: hoursAgo(95)})], NOW)), ["c1"]);
eq("a card added 97h ago has rotated out",
   ids(revealRotation([row({added_at: hoursAgo(97)})], NOW)), []);
// ⚠ A future stamp can NEVER age out of a window whose far end keeps moving
// toward it, so trusting one pins that card to the head of the reel forever.
eq("a future stamp is ignored, not trusted",
   ids(revealRotation([row({added_at: hoursAgo(-5)})], NOW)), []);
eq("a row with no added_at is out (synthetic rows: Coconut, CUSTOM_VARIANTS)",
   ids(revealRotation([row({added_at: null})], NOW)), []);
eq("an unparseable stamp is out",
   ids(revealRotation([row({added_at: "not a date"})], NOW)), []);

// ── what is excluded ────────────────────────────────────────────────────────
ok("Extras is on the excluded list", REVEAL_EXCLUDED_SETS.has(EXTRAS_SET_NAME));
eq("an Extras row is not a reveal — that bucket is a hand backfill",
   ids(revealRotation([row({set: EXTRAS_SET_NAME})], NOW)), []);
// ⚠ The pointed opposite: promos ARE the reveal. On the day this shipped the
// live 96h window held 38 Hyperia City cards and 23 promos across Promo Set
// 3/4, PD1 and Magical Places — a set filter would have thrown all 23 away.
eq("promo sets ride along with the set being spoiled",
   ids(revealRotation([
     row({card_id: "hc", set: "Hyperia City"}),
     row({card_id: "p4", set: "Promo Set 4"}),
     row({card_id: "pd1", set: "PD1"}),
   ], NOW)).sort(), ["hc", "p4", "pd1"]);
eq("a card with no art at all is dropped — the reel is nothing but art",
   ids(revealRotation([row({img: null})], NOW)), []);

// ── one entry per card, not per printing ────────────────────────────────────
eq("Normal + Foil of one card is ONE reveal",
   ids(revealRotation([
     row({card_id: "c1", printing: "Normal"}),
     row({card_id: "c1", printing: "Cold Foil"}),
   ], NOW)), ["c1"]);
{
  // The artless printing comes first; the entry must still end up with art.
  const got = revealRotation([
    row({card_id: "c1", printing: "Normal", img: null}),
    row({card_id: "c1", printing: "Cold Foil"}),
  ], NOW);
  eq("the printing WITH art wins regardless of row order",
     [got.length, got[0] && got[0].row.Printing], [1, "Cold Foil"]);
}

// ── ordering ────────────────────────────────────────────────────────────────
eq("newest first",
   ids(revealRotation([
     row({card_id: "old", added_at: hoursAgo(80)}),
     row({card_id: "new", added_at: hoursAgo(2)}),
     row({card_id: "mid", added_at: hoursAgo(40)}),
   ], NOW)), ["new", "mid", "old"]);
// A whole wave lands on one timestamp, so the tiebreak is what makes it read
// in printed order rather than in whatever order the fetch happened to return.
eq("a single wave reads in collector-number order",
   ids(revealRotation([
     row({card_id: "c12", num: "12"}),
     row({card_id: "c3",  num: "3"}),
     row({card_id: "c7",  num: "7"}),
   ], NOW)), ["c3", "c7", "c12"]);
eq("a non-numeric collector number sorts last, it does not throw",
   ids(revealRotation([
     row({card_id: "weird", num: "P1/abc"}),
     row({card_id: "c2", num: "2"}),
   ], NOW)), ["c2", "weird"]);

// ── the cap ─────────────────────────────────────────────────────────────────
{
  const many = Array.from({length: REVEAL_MAX_CARDS + 25},
    (_, i) => row({card_id: "c" + i, num: String(i)}));
  const got = revealRotation(many, NOW);
  eq("the reel is capped", got.length, REVEAL_MAX_CARDS);
}

// ── input safety ────────────────────────────────────────────────────────────
eq("null input is empty, not a throw", ids(revealRotation(null, NOW)), []);
eq("undefined input is empty", ids(revealRotation(undefined, NOW)), []);
eq("junk rows are skipped", ids(revealRotation([null, undefined, {}, row()], NOW)), ["c1"]);

// ── the headline ────────────────────────────────────────────────────────────
const setOf = (n, set) => Array.from({length: n}, () => ({set}));
eq("a clear majority names its set",
   revealSetLabel([...setOf(7, "Hyperia City"), ...setOf(3, "Promo Set 4")]), "Hyperia City");
// ⚠ Strictly MORE than half. At a dead tie there is no story to tell and
// naming either one is a coin flip presented to the reader as a fact.
eq("an exact 50/50 names neither",
   revealSetLabel([...setOf(5, "Hyperia City"), ...setOf(5, "Promo Set 4")]), null);
eq("a three-way split with no majority names neither",
   revealSetLabel([...setOf(4, "A"), ...setOf(3, "B"), ...setOf(3, "C")]), null);
eq("one set alone names itself", revealSetLabel(setOf(3, "Hyperia City")), "Hyperia City");
eq("an empty reel has no label", revealSetLabel([]), null);
eq("null is safe", revealSetLabel(null), null);

// ── the live shape, end to end ──────────────────────────────────────────────
{
  // Reproduces the real 2026-09-22 window: a Hyperia City wave plus promos,
  // an out-of-window straggler and a synthetic row with no stamp.
  const live = [
    ...Array.from({length: 20}, (_, i) => row({card_id: "hc" + i, set: "Hyperia City",
      num: String(i + 1), added_at: hoursAgo(2)})),
    ...Array.from({length: 6}, (_, i) => row({card_id: "p" + i, set: "Promo Set 4",
      num: String(i + 1), added_at: hoursAgo(20)})),
    row({card_id: "stale", set: "Azurite Sea", added_at: hoursAgo(400)}),
    row({card_id: "coconut", set: "[Format Coconut]", added_at: null}),
  ];
  const got = revealRotation(live, NOW);
  eq("live-shaped window keeps exactly the fresh cards", got.length, 26);
  eq("and names the dominant set", revealSetLabel(got), "Hyperia City");
  ok("the freshest wave leads", got[0].card_id.startsWith("hc"));
  ok("no stale card survived", !got.some(c => c.card_id === "stale"));
  ok("no synthetic row survived", !got.some(c => c.card_id === "coconut"));
  ok("every entry carries art", got.every(c => !!c.art));
  ok("every entry carries its source row for the enlarge overlay",
     got.every(c => c.row && c.row["Product Name"]));
}

console.log(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
