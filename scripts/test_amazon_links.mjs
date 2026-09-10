// test_amazon_links.mjs — guards the Amazon affiliate link layer.
//
//     node scripts/test_amazon_links.mjs
//
// Extracts the real helpers and the real ASIN catalog out of Index.html rather
// than restating them, so the test cannot drift from what ships.
//
// Every failure this catches is SILENT in production, which is the whole
// reason it exists:
//
//   * A dropped or misspelled `tag=` produces a link that works perfectly,
//     sends the visitor to the right product, and earns nothing. There is no
//     error, no console warning, and no way to notice except by reading the
//     URL — and the account has a 180-day / 3-sale probation clock running.
//   * A set name typo'd against MAINLINE_SETS ("Ursulas Return") never matches,
//     so that set quietly serves a search link forever while looking curated.
//   * One ASIN pasted under two products sends both to the same box.
//   * A token rule that matches nothing is indistinguishable from one that was
//     never added.
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
  grabLine("const AMAZON_TAG = "),
  grab("const amazonUrl = (asin) => asin", ";" + NL),
  grab("const amazonSearchUrl = (query) =>", ";" + NL),
  grab("const MAINLINE_SETS = [", NL + "];"),
  grab("const SEALED_DISPLAY_TYPE_FOR = {", NL + "};"),
  grab("function deriveSealedDisplayType(item){", NL + "}"),
  grabLine("const cleanSealedName = "),
  grab("const AMAZON_ASIN_BY_SET = {", NL + "};"),
  grab("const AMAZON_SEALED_RULES = [", NL + "];"),
  grab("const AMAZON_PUZZLE_ASINS = {", NL + "};"),
  grabLine("const _amznNorm = "),
  grab("function amazonForSealed(product, setName){", NL + "}"),
  grab("const LORCANA_GEAR = [", NL + "];"),
  "export {AMAZON_TAG, amazonUrl, amazonSearchUrl, amazonForSealed,",
  "  AMAZON_ASIN_BY_SET, AMAZON_SEALED_RULES, AMAZON_PUZZLE_ASINS,",
  "  LORCANA_GEAR, MAINLINE_SETS};",
].join(NL);

const m = await import("data:text/javascript," + encodeURIComponent(moduleSrc));

let failed = 0;
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) failed++;
  console.log((ok ? "PASS  " : "FAIL  ") + name +
    (ok ? "" : "  (got " + JSON.stringify(got) + ", want " + JSON.stringify(want) + ")"));
};
const ok = (name, cond, detail) => {
  if (!cond) failed++;
  console.log((cond ? "PASS  " : "FAIL  ") + name + (cond ? "" : "  " + (detail || "")));
};

// ── The tag is the entire commercial payload ────────────────────────────────
check("tag is the approved associate id", m.AMAZON_TAG, "packsink-20");
ok("product URL carries the tag",
  m.amazonUrl("B0DK5WC19T").includes("tag=packsink-20"), m.amazonUrl("B0DK5WC19T"));
ok("search URL carries the tag",
  m.amazonSearchUrl("lorcana sleeves").includes("tag=packsink-20"));
check("null ASIN yields no link", m.amazonUrl(null), null);
check("empty ASIN yields no link", m.amazonUrl(""), null);
ok("product URL is a /dp/ link",
  m.amazonUrl("B0DK5WC19T").startsWith("https://www.amazon.com/dp/B0DK5WC19T?"));
ok("search URL is scoped to Toys & Games",
  m.amazonSearchUrl("x").includes("i=toys-and-games"));
// The one that bites: an unencoded "&" in a product name ("Amber & Ruby")
// would terminate the k= parameter and search Amazon for half the name.
const amp = m.amazonSearchUrl("Azurite Sea Amber & Ruby Starter Deck");
ok("an ampersand in the query is encoded", amp.includes("%26"), amp);
ok("…so the tag survives the query", amp.split("&tag=packsink-20").length === 2, amp);
ok("spaces are encoded", m.amazonSearchUrl("a b").includes("a%20b"));

// ── Catalog integrity ───────────────────────────────────────────────────────
const ASIN_RE = /^[A-Z0-9]{10}$/;
const all = [];
for (const [type, bySet] of Object.entries(m.AMAZON_ASIN_BY_SET))
  for (const [set, asin] of Object.entries(bySet)) all.push([type + " / " + set, asin]);
for (const r of m.AMAZON_SEALED_RULES) all.push(["rule " + r.tokens.join("+"), r.asin]);
for (const [sku, asin] of Object.entries(m.AMAZON_PUZZLE_ASINS)) all.push(["puzzle " + sku, asin]);
for (const sec of m.LORCANA_GEAR)
  for (const it of sec.items) all.push(["gear " + it.name, it.asin]);

const badShape = all.filter(([, a]) => !ASIN_RE.test(a));
ok("every ASIN is well formed", badShape.length === 0, JSON.stringify(badShape));

const seen = new Map();
const dupes = [];
for (const [where, asin] of all) {
  if (seen.has(asin)) dupes.push(asin + " = " + seen.get(asin) + " AND " + where);
  else seen.set(asin, where);
}
ok("no ASIN is used twice", dupes.length === 0, dupes.join("; "));
ok("catalog is not empty", all.length > 40, "only " + all.length + " entries");

// A set name that is not in MAINLINE_SETS can never be matched by the
// set x type pass, so it is dead weight that LOOKS curated.
const mainline = new Set(m.MAINLINE_SETS);
const strayNames = [];
for (const [type, bySet] of Object.entries(m.AMAZON_ASIN_BY_SET))
  for (const set of Object.keys(bySet))
    if (!mainline.has(set)) strayNames.push(type + " / " + set);
ok("every keyed set name exists in MAINLINE_SETS",
  strayNames.length === 0, strayNames.join("; "));

// Rule tokens are matched against a normalized name, so an uppercase or
// punctuated token can never fire.
const badTokens = m.AMAZON_SEALED_RULES
  .flatMap((r) => r.tokens.filter((t) => t !== t.toLowerCase() || /[^a-z0-9 ]/.test(t)));
ok("rule tokens are all normalized-form", badTokens.length === 0, JSON.stringify(badTokens));

// ── Resolution ──────────────────────────────────────────────────────────────
const box = (set) => ({name: "Disney Lorcana: " + set + " Booster Box", product_type: "Booster Box"});

const azurite = m.amazonForSealed(box("Azurite Sea"), "Azurite Sea");
check("set x type resolves a booster box", azurite.exact, true);
ok("…to that set's ASIN", azurite.url.includes("B0DLHGL62N"), azurite.url);

const trove = m.amazonForSealed(
  {name: "Disney Lorcana: Fabled Illumineer's Trove", product_type: "Trove"}, "Fabled");
ok("set x type resolves a trove", trove.exact && trove.url.includes("B0DTK3JD8B"), trove.url);

// A token rule must WIN over set x type — the Stitch gift set and the plain
// Azurite booster box are both "Azurite Sea", and only the rule can tell them
// apart. This is the ordering the resolver depends on.
const stitch = m.amazonForSealed(
  {name: "Disney Lorcana: Azurite Sea - Stitch Collector's Gift Set", product_type: "Gift Set"},
  "Azurite Sea");
ok("a token rule beats set x type",
  stitch.exact && stitch.url.includes("B0DK5WC19T"), stitch.url);

// The user's own example link, reduced to its working parts.
ok("the example gift set resolves to the example ASIN",
  stitch.url === "https://www.amazon.com/dp/B0DK5WC19T?tag=packsink-20&linkCode=ll1", stitch.url);

// Two starter decks in one set are separated by their ink pair.
const sd1 = m.amazonForSealed(
  {name: "Archazia's Island Starter Deck - Amethyst & Steel", product_type: "Starter Deck"},
  "Archazia's Island");
const sd2 = m.amazonForSealed(
  {name: "Archazia's Island Starter Deck - Ruby & Sapphire", product_type: "Starter Deck"},
  "Archazia's Island");
ok("ink pair picks the right starter deck",
  sd1.url.includes("B0DDL6BJDS") && sd2.url.includes("B0DDL8HJ2M"),
  sd1.url + " / " + sd2.url);

// An uncurated set must degrade to a tagged search, never to a broken or
// mislabelled "exact" link.
const vine = m.amazonForSealed(box("Attack of the Vine!"), "Attack of the Vine!");
check("an uncurated set falls back to search", vine.exact, false);
ok("…and the fallback still carries the tag",
  vine.url.includes("tag=packsink-20") && vine.url.includes("/s?k="), vine.url);

// The set name is prepended when the product name lacks it, and not doubled
// when it has it (a doubled name narrows a search to nothing).
const noSet = m.amazonForSealed({name: "Booster Pack Display", product_type: "Booster Box"}, "Attack of the Vine!");
ok("search prepends a missing set name",
  decodeURIComponent(noSet.url).includes("Attack of the Vine! Booster Pack Display"), noSet.url);
ok("search does not double the set name",
  (decodeURIComponent(vine.url).match(/Attack of the Vine!/g) || []).length === 1, vine.url);

// Puzzles resolve off the synthetic pid (900000000 + Ravensburger SKU).
const puzzle = m.amazonForSealed(
  {name: "Glimmers of the Realm: Ruby", is_puzzle: true, tcgplayer_product_id: 900000000 + 12001624});
ok("a puzzle resolves by its SKU",
  puzzle.exact && puzzle.url.includes("B0F1X7RRP2"), puzzle.url);
const puzzle300 = m.amazonForSealed(
  {name: "Moana - Of Motunui", is_puzzle: true, tcgplayer_product_id: 900000000 + 12001660});
check("an uncurated puzzle falls back to search", puzzle300.exact, false);

check("a nameless product yields no link", m.amazonForSealed({name: ""}, "Fabled"), null);
check("no product yields no link", m.amazonForSealed(null, "Fabled"), null);

// ── Gear ────────────────────────────────────────────────────────────────────
ok("gear has sleeves, portfolios and a deck box",
  m.LORCANA_GEAR.length >= 3 && m.LORCANA_GEAR.every((s) => s.items.length > 0));
ok("every gear item links with the tag",
  m.LORCANA_GEAR.every((s) => s.items.every((it) =>
    m.amazonUrl(it.asin).includes("tag=packsink-20"))));

// ── The compliance boundary ─────────────────────────────────────────────────
// Amazon's licence permits a displayed price only when fetched live (<=1h
// cache) and forbids storing their images at all. This site is an ETL +
// localStorage cache, so it must never hold either. Assert the catalog carries
// nothing that looks like a price or an image URL.
const gearBlob = JSON.stringify(m.LORCANA_GEAR);
ok("gear stores no prices", !/\$|\bprice\b/i.test(gearBlob));
ok("gear stores no image URLs", !/https?:\/\//i.test(gearBlob));
const catalogBlob = JSON.stringify([m.AMAZON_ASIN_BY_SET, m.AMAZON_SEALED_RULES, m.AMAZON_PUZZLE_ASINS]);
ok("the ASIN catalog stores nothing but ASINs and keys", !/https?:\/\/|\$/.test(catalogBlob));

console.log(NL + (failed ? failed + " FAILED" : "all passed"));
process.exit(failed ? 1 : 0);
