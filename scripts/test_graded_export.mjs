// test_graded_export.mjs — guards the graded collection's price-free export.
//
//     node scripts/test_graded_export.mjs
//
// Extracts the real code out of Index.html, house pattern, so it can't drift
// from what ships.
//
// The feature exists because a collector sending someone "here is what I have
// in hand" does not want to imply an asking price for any of it. So a price
// leaking into the output is not an untidy file, it is the WRONG file — and it
// is the silent kind of wrong: the list looks right, sends fine, and says
// something its author never meant to say. Two directions are pinned:
//
//   * no price reaches either serializer, in the output OR in the projection's
//     own field list — a column added later cannot pick one up by accident;
//   * the list still carries everything it is FOR (name, set, number, rarity,
//     grade, quantity) — an export that leaks nothing by saying nothing would
//     pass a one-sided test.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const NL = "\n";
const grab = (a, b) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error("missing marker: " + a);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error("missing end: " + b);
  return src.slice(i, j + b.length);
};
const grabLine = (p) => {
  const l = src.split(NL).find((x) => x.startsWith(p));
  if (!l) throw new Error("missing line: " + p);
  return l;
};

const ROW_SRC = grab("const gradedExportRow = (e) => ({", NL + "});");
const TEXT_SRC = grab("function buildGradedExportText(buckets){", NL + "}");
const CSV_SRC = grab("function buildGradedExportCsv(buckets){", NL + "}");
const FOIL_SRC = grab("const gradedOwnedIsFoil = (e) =>", ";" + NL);

const mod = await import("data:text/javascript," + encodeURIComponent([
  grabLine("const GRADED_CHASE_RARITIES = "),
  grab("const MAINLINE_SETS = [", NL + "];"),
  FOIL_SRC,
  ROW_SRC,
  TEXT_SRC,
  CSV_SRC,
  "export { gradedExportRow, buildGradedExportText, buildGradedExportCsv, gradedOwnedIsFoil };",
].join(NL)));

const { gradedExportRow, buildGradedExportText, buildGradedExportCsv } = mod;

let fails = 0, checks = 0;
const ok = (cond, msg) => { checks++; if (!cond) { fails++; console.error("  FAIL: " + msg); } };

// A fixture whose price fields are all populated and all distinctive, so any
// one of them reaching the output is visible as a literal in the text.
const PRICES = { value: 1707.25, lastSold: 33493, avg5: 4826.5, price: 91234 };
const entry = (over) => ({
  name: "Mickey Mouse", sub: "Brave Little Tailor",
  set: "The First Chapter", rarity: "Legendary",
  grader: "psa", grade: "10", qty: 1, printing: "Normal",
  meta: { Number: "115/204" },
  ...PRICES, ...over,
});

const entries = [
  entry({}),
  entry({ name: "Elsa", sub: "Spirit of Winter", rarity: "Enchanted", set: "Rise of the Floodborn",
    printing: "Cold Foil", grader: "cgc", grade: "9.5", qty: 2, meta: { Number: "215/204" } }),
  // A mainline foil — the one shape that earns the word "Foil".
  entry({ name: "Sisu", sub: "Divine Water Dragon", rarity: "Rare", set: "The First Chapter",
    printing: "Cold Foil", grader: "bgs", grade: "9", meta: { Number: "62/204" } }),
];
const buckets = [
  { label: "The First Chapter", rows: [entries[0], entries[2]].map(gradedExportRow) },
  { label: "Rise of the Floodborn", rows: [entries[1]].map(gradedExportRow) },
];

const text = buildGradedExportText(buckets);
const csv = buildGradedExportCsv(buckets);

console.log("1. no price reaches the output");
for (const [out, label] of [[text, "text"], [csv, "csv"]]) {
  ok(!out.includes("$"), label + " contains a dollar sign");
  for (const [k, v] of Object.entries(PRICES)) {
    for (const form of [String(v), String(Math.round(v))]) {
      ok(!out.includes(form), label + " leaks " + k + " (" + form + ")");
    }
  }
}
// The projection's field list is the structural defence — pin it explicitly,
// so a price field added to it fails here rather than in someone's DM.
const ROW_FIELDS = Object.keys(gradedExportRow(entries[0]));
ok(!ROW_FIELDS.some((f) => /price|value|sold|avg|cost|paid|worth/i.test(f)),
  "gradedExportRow projects a price-shaped field: " + ROW_FIELDS.join(","));
// ...and that the serializers never name one either, even in dead code.
for (const [srcTxt, label] of [[ROW_SRC, "gradedExportRow"], [TEXT_SRC, "buildGradedExportText"], [CSV_SRC, "buildGradedExportCsv"]]) {
  for (const bad of ["lastSold", "avg5", "e.value", "rawPlaceholder", "fmt(", "totalValue"]) {
    ok(!srcTxt.includes(bad), label + " references " + bad);
  }
}

console.log("2. the list carries what it is for");
ok(text.includes("Mickey Mouse - Brave Little Tailor"), "text missing full card name");
ok(text.includes("#115/204"), "text missing the printed collector number");
ok(text.includes("Legendary"), "text missing rarity");
ok(text.includes("PSA 10"), "text missing the grader + grade");
ok(text.includes("CGC 9.5"), "text missing a decimal grade");
ok(text.includes("×2"), "text missing the quantity marker");
ok(text.includes("The First Chapter") && text.includes("Rise of the Floodborn"), "text missing set headings");
ok(/^Graded Lorcana — 3 cards \(4 copies\)/.test(text), "header miscounts cards/copies: " + text.split("\n")[0]);

const csvLines = csv.split("\n");
ok(csvLines[0] === "Qty,Name,Set,Card Number,Rarity,Printing,Grader,Grade", "csv header changed: " + csvLines[0]);
ok(csvLines.length === 4, "csv should have 3 data rows, got " + (csvLines.length - 1));
ok(csvLines[1] === "1,Mickey Mouse - Brave Little Tailor,The First Chapter,115/204,Legendary,Normal,PSA,10",
  "csv row 1 changed: " + csvLines[1]);
ok(csvLines.some((l) => l.startsWith("2,Elsa - Spirit of Winter")), "csv lost the x2 quantity");

console.log("3. the Foil tag is the grid's own rule");
const rows = buckets.flatMap((b) => b.rows);
const byName = (n) => rows.find((r) => r.name.startsWith(n));
ok(byName("Sisu").foil === true, "a mainline Cold Foil should read Foil");
ok(byName("Elsa").foil === false, "an Enchanted is single-printing — it must NOT read Foil");
ok(byName("Mickey").foil === false, "a Normal printing must not read Foil");
ok(/Sisu[^\n]*· Foil/.test(text), "text dropped the Foil tag on the one row that earns it");
ok(!/Elsa[^\n]*Foil/.test(text), "text called an Enchanted Foil");
// The CSV carries the raw printing instead, which is a different (fuller) fact.
ok(csvLines.some((l) => l.includes(",Cold Foil,CGC,9.5")), "csv lost the raw printing string");

console.log("4. an empty selection exports nothing");
ok(buildGradedExportText([]) === null, "empty text export should be null");
ok(buildGradedExportCsv([{ label: "x", rows: [] }]) === null, "empty csv export should be null");

console.log("5. csv escaping");
const QUOTED = "Giant Fairy, " + String.fromCharCode(34) + "Big" + String.fromCharCode(34);
const comma = buildGradedExportCsv([{ label: null, rows: [gradedExportRow(entry({
  name: "Tinker Bell", sub: QUOTED, meta: { Number: "1/204" } }))] }]);
const q = String.fromCharCode(34);
ok(comma.includes(q + "Tinker Bell - Giant Fairy, " + q + q + "Big" + q + q + q),
  "csv did not escape a comma + quotes: " + comma.split("\n")[1]);

console.log("6. an ungrouped screen exports a flat list, and each row names its set");
const flat = buildGradedExportText([{ label: null, rows: rows }]);
ok(!flat.split("\n").some((l) => l === "The First Chapter"), "a label-less bucket should print no heading");
ok(flat.split("\n").filter((l) => l.startsWith("- ")).length === 3, "flat list lost rows");
// ⚠ The real defect this catches: promo sets each restart their collector
// numbers at 1, so an ungrouped list of promos said "#2 · Promo" for three
// different cards. With no heading above it, a row must carry its own set.
ok(/- Mickey Mouse - Brave Little Tailor · The First Chapter #115\/204 ·/.test(flat),
  "an ungrouped row must name its set: " + flat.split("\n").find((l) => l.startsWith("- ")));
// ...and must NOT, when the heading above it already said so.
ok(/- Mickey Mouse - Brave Little Tailor · #115\/204 ·/.test(text),
  "a grouped row repeats its set: " + text.split("\n").find((l) => l.startsWith("- ")));

console.log("\n" + (checks - fails) + "/" + checks + " checks passed");
if (fails) { console.error(fails + " FAILED"); process.exit(1); }
