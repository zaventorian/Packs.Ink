// test_scan_variants.mjs — guards the scan review row's VERSION segment.
//
//     node scripts/test_scan_variants.mjs
//
// Extracts the real helpers out of Index.html rather than restating them, and
// replays them over the shipped scanner index so the coverage claim in
// CLAUDE.md is a measurement rather than a memory.
//
// The failure mode this exists for is silent. A version chip is one word next
// to a card the user is about to file into their collection, so a chip that
// cannot actually tell two versions apart doesn't error — it just makes a coin
// flip look like a choice, and the wrong card gets saved looking confirmed.
// Two booster printings of one card both label "Common"; the whole point of
// scanVariantChipsOk is to refuse that family and send it to the editor's
// list, which shows each version's art.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const NL = String.fromCharCode(10);

function grab(start, end) {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
}
function grabLine(prefix) {
  const line = src.split(/\r?\n/).find((l) => l.startsWith(prefix));
  if (!line) throw new Error("missing line: " + prefix);
  return line;
}

const moduleSrc = [
  grab("const normalizeRarity = r => {", NL + "};"),
  grabLine("const CARDS_RARITIES = "),
  grabLine("let _setRankById"),
  grab("const SCAN_VARIANT_MAX = 4;", 'const scanVariantFamilyKey = (productName) => String(productName || "").toLowerCase();'),
  "export {SCAN_VARIANT_MAX, CARDS_RARITIES, scanVariantLabel, scanVariantsFor, scanVariantChipsOk, scanVariantTitle, scanVariantFamilyKey, _setRankById};",
].join(NL);

const { SCAN_VARIANT_MAX, CARDS_RARITIES, scanVariantsFor, scanVariantChipsOk, scanVariantTitle,
  scanVariantFamilyKey, _setRankById } =
  await import("data:text/javascript," + encodeURIComponent(moduleSrc));

let failed = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  const ok = g === w;
  if (!ok) failed++;
  console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  (got " + g + ", want " + w + ")"));
};

// A catalog row, cut down to what scanVariantsFor reads.
const row = (o) => Object.assign({
  card_id: "crd_" + (o.n || o.rarity || "x"), "Product Name": "Heihei - Created by the Vine",
  Rarity: "Common", Set: "Attack of the Vine!", Number: "", variant_label: null,
  img_small: null, img_normal: null,
}, o);
const labels = (v) => v.map((e) => e.label);

// ── 1. The reported case: a Rare and its Epic, same set, same name ───────────
const heihei = scanVariantsFor([
  row({ n: "epic", Rarity: "Epic", Number: "223" }),
  row({ n: "rare", Rarity: "Rare", Number: "114" }),
]);
check("Heihei: two versions", heihei.length, 2);
check("Heihei: base rarity leads", labels(heihei), ["Rare", "Epic"]);
check("Heihei: chips render", scanVariantChipsOk(heihei), true);
check("Heihei: ids survive", heihei.map((e) => e.id), ["crd_rare", "crd_epic"]);

// ── 2. A promo of a base card — Aaron's league-promo case ────────────────────
const promo = scanVariantsFor([
  row({ n: "promo", Rarity: "Promo", Set: "Promo Set 3" }),
  row({ n: "base", Rarity: "Common" }),
]);
check("promo: base then promo", labels(promo), ["Common", "Promo"]);
check("promo: chips render", scanVariantChipsOk(promo), true);

// ── 3. ⚠ The honesty guard. Two booster printings of one card both say
//        "Common", so the chip row must refuse the family — while the editor's
//        list (which gets the full array) still offers both. ─────────────────
const reprint = scanVariantsFor([
  row({ n: "a", Rarity: "Common", Set: "The First Chapter" }),
  row({ n: "b", Rarity: "Common", Set: "Fabled" }),
]);
check("reprint: both versions reach the editor", reprint.length, 2);
check("reprint: chips refuse a duplicate label", scanVariantChipsOk(reprint), false);

// Same shape one level deeper: only ONE pair collides in a three-way family.
const ursula = scanVariantsFor([
  row({ n: "a", Rarity: "Uncommon", Set: "Into the Inklands" }),
  row({ n: "b", Rarity: "Uncommon", Set: "Fabled" }),
  row({ n: "c", Rarity: "Promo", Set: "Promo Set 2" }),
]);
check("one collision poisons the whole chip row", scanVariantChipsOk(ursula), false);
check("...but all three still list", ursula.length, 3);

// ── 4. A named variant is named by its label, not its rarity ────────────────
const named = scanVariantsFor([
  row({ n: "ench", Rarity: "Enchanted" }),
  row({ n: "err", Rarity: "Enchanted", variant_label: "Text Error", Set: "Extras & Oddities" }),
]);
check("variant_label wins over rarity", labels(named), ["Enchanted", "Text Error"]);
check("named variant un-collides the family", scanVariantChipsOk(named), true);

// ── 5. The cap. Five distinctly-labelled versions is still too many chips for
//        a review row; the editor takes it. ─────────────────────────────────
const five = scanVariantsFor(["Common", "Uncommon", "Rare", "Epic", "Enchanted"]
  .map((r, i) => row({ n: i, Rarity: r })));
check("five versions all list", five.length, 5);
check("five versions get no chips", scanVariantChipsOk(five), false);
check("four do", scanVariantChipsOk(five.slice(0, 4)), true);
check("SCAN_VARIANT_MAX is 4", SCAN_VARIANT_MAX, 4);

// ── 6. Nothing to choose between ────────────────────────────────────────────
check("a lone printing is not a version set", scanVariantsFor([row({ n: "solo" })]), []);
check("no rows", scanVariantsFor(null), []);
check("chips need two", scanVariantChipsOk([]), false);

// ── 7. Rows that are not cards ──────────────────────────────────────────────
const skipped = scanVariantsFor([
  row({ n: "a", Rarity: "Rare" }),
  row({ n: "b", Rarity: "Epic" }),
  row({ n: "coco", Rarity: "Rare", isCoconut: true }),
  { card_id: null, "Product Name": "x", Rarity: "Rare" },
  { card_id: "crd_noname", Rarity: "Rare" },
]);
check("coconut leaders and malformed rows drop out", skipped.length, 2);

// ── 8. Ordering is the canonical rarity order, not alphabetical ─────────────
const order = scanVariantsFor([
  row({ n: "p", Rarity: "Promo", Set: "Promo Set 1" }),
  row({ n: "e", Rarity: "Enchanted" }),
  row({ n: "l", Rarity: "Legendary" }),
]);
check("Legendary → Enchanted → Promo", labels(order), ["Legendary", "Enchanted", "Promo"]);

// Within one rarity the older print leads, so a reprint falls in behind the
// printing it reprints. Alphabetical set names put Fabled above The First
// Chapter, which reads as the reprint being the original.
_setRankById.set("set_tfc", "2023-08-18");
_setRankById.set("set_fab", "2026-05-15");
const reprintOrder = scanVariantsFor([
  row({ n: "new", Rarity: "Common", Set: "Fabled", set_id: "set_fab" }),
  row({ n: "old", Rarity: "Common", Set: "The First Chapter", set_id: "set_tfc" }),
]);
check("older print leads its reprint", reprintOrder.map((e) => e.set),
  ["The First Chapter", "Fabled"]);

// Lorcast's wire spelling is normalised on the way in (CLAUDE.md's rarity
// invariant) — an un-normalised label would also read as a distinct one.
const sr = scanVariantsFor([
  row({ n: "a", Rarity: "Super_rare" }),
  row({ n: "b", Rarity: "Enchanted" }),
]);
check("Super_rare normalises", labels(sr), ["Super Rare", "Enchanted"]);

// ── 9. The tooltip says where the version lives ─────────────────────────────
check("title carries set + number",
  scanVariantTitle({ label: "Epic", set: "Attack of the Vine!", number: "223" }),
  "Epic · Attack of the Vine! #223");
check("title degrades without them", scanVariantTitle({ label: "Promo", set: "", number: "" }), "Promo");

// ── 10. Replay over the SHIPPED scanner index ───────────────────────────────
// The index is name/version/set_id/rarity per card_id, which is exactly the
// shape the version segment keys on, so this is the real population rather
// than a fixture of it.
const idx = JSON.parse(readFileSync(new URL("../scanner/index.json", import.meta.url), "utf8"));
const famsOf = (key) => {
  const m = new Map();
  for (const c of idx.cards) {
    const name = (c.name || "") + (c.version ? " - " + c.version : "");
    const r = { card_id: c.id, "Product Name": name, Rarity: c.rarity,
      Set: c.set_id, Number: "", variant_label: null };
    const k = key(name);
    const a = m.get(k);
    if (a) a.push(r); else m.set(k, [r]);
  }
  return m;
};
const fams = famsOf(scanVariantFamilyKey);

// ⚠ Lorcast spells the same card two ways across sets. Folding the family key
// is what keeps a promo attached to the card it promotes — without it these
// versions are simply not offered, which is the original report.
check("family key folds case", scanVariantFamilyKey("HeiHei - Bumbling Rooster"),
  scanVariantFamilyKey("Heihei - Bumbling Rooster"));
const exact = famsOf((n) => n);
const exactSize = new Map();
for (const [k, v] of exact) exactSize.set(k, v.length);
// Cards that gain at least one version purely by folding the key. Counting
// FAMILIES would undercount: Vanellope's Rare and Enchanted already sat
// together under one spelling, so folding her Promo in grows a family that
// already existed rather than creating one.
let gained = 0;
for (const rows of fams.values()) {
  for (const r of rows) if (exactSize.get(r["Product Name"]) < rows.length) { gained++; }
}
check("folding recovers versions Lorcast's casing had hidden", gained, 19);
let multi = 0, chipped = 0, dupLabel = 0, overCap = 0, misordered = 0;
for (const rows of fams.values()) {
  if (rows.length < 2) continue;
  const vars = scanVariantsFor(rows);
  if (vars.length !== rows.length) { dupLabel++; continue; }   // would be a lost version
  multi++;
  const ok = scanVariantChipsOk(vars);
  if (ok) {
    chipped++;
    if (new Set(vars.map((v) => v.label)).size !== vars.length) dupLabel++;
    if (vars.length > SCAN_VARIANT_MAX) overCap++;
    const ranks = vars.map((v) => CARDS_RARITIES.indexOf(v.rarity));
    for (let i = 1; i < ranks.length; i++) if (ranks[i] < ranks[i - 1]) misordered++;
  }
}
check("no chip row ever carries a duplicate label", dupLabel, 0);
check("no chip row exceeds the cap", overCap, 0);
check("every chip row reads base-rarity-first", misordered, 0);
check("every version of every card survives the pass", multi, fams.size - [...fams.values()].filter((v) => v.length < 2).length);
console.log("      " + chipped + " of " + multi + " multi-version cards get inline chips; the rest go to the editor's list");

console.log(failed ? NL + failed + " FAILED" : NL + "all passed");
process.exit(failed ? 1 : 0);
