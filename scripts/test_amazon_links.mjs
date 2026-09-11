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

// CRLF-normalised: a Windows checkout (core.autocrlf=true) ends lines "\r\n",
// which never contains the ";\n" end markers below.
const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
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
  grabLine("const AMAZON_DEPT_DEFAULT = "),
  grab("const amazonSearchUrl = (query, dept) =>", ";" + NL),
  grab("const MAINLINE_SETS = [", NL + "];"),
  grab("const SEALED_DISPLAY_TYPE_FOR = {", NL + "};"),
  grab("function deriveSealedDisplayType(item){", NL + "}"),
  grabLine("const cleanSealedName = "),
  grab("const AMAZON_ASIN_BY_SET = {", NL + "};"),
  grab("const AMAZON_SEALED_RULES = [", NL + "];"),
  grab("const AMAZON_PUZZLE_ASINS = {", NL + "};"),
  grabLine("const _amznNorm = "),
  grab("function amazonForSealed(product, setName){", NL + "}"),
  grab("const SEALED_PUZZLES = [", "}));"),
  grab("const LORCANA_GEAR = [", NL + "];"),
  grabLine("const gearUrl = "),
  grabLine("const gearKey = "),
  grab("const AMAZON_DIR_SETS = [", NL + "];"),
  grab("function amazonDirectory(){", NL + "}"),
  grab("const normalizeRarity = r => {", NL + "};"),
  grabLine("const AMAZON_CARD_RARITY_WORDS = "),
  grab("const amazonCardSearchUrl = (name, rarity) => {", NL + "};"),
  grabLine("const TCG_IMG_BASE = "),
  grab("const tcgProductImg = (pid, px = 400) =>", ";" + NL),
  grab("const tcgImgSized = (url, px = 400) => {", NL + "};"),
  grabLine("const TCG_AFFILIATE_BASE = "),
  grab("const tcgUrl = (productId, printing) => {", NL + "};"),
  grab("function isHiddenSealedListing(item){", NL + "}"),
  grab("const AMAZON_SEALED_TYPE_LABEL = {", NL + "};"),
  grab("const setNameMapOf = (setsMeta) => {", NL + "};"),
  grab("function amazonSealedMatches(sealedPrices, setNameById){", NL + "}"),
  grabLine("const AMAZON_SHELF_ORDER = "),
  grabLine("const AMAZON_SHELF_SEARCH_TYPES = "),
  grabLine("const AMAZON_SHELF_MAX = "),
  grab("function amazonShelfItems(sealedPrices, setNameById){", NL + "}"),
  "export {AMAZON_TAG, amazonUrl, amazonSearchUrl, amazonForSealed, gearUrl,",
  "  AMAZON_ASIN_BY_SET, AMAZON_SEALED_RULES, AMAZON_PUZZLE_ASINS,",
  "  LORCANA_GEAR, MAINLINE_SETS, amazonDirectory,",
  "  amazonCardSearchUrl, tcgProductImg, tcgImgSized, amazonSealedMatches,",
  "  amazonShelfItems, AMAZON_SHELF_MAX};",
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
// Only the curated half: a search-backed row has no ASIN by design, and
// pushing its `undefined` here would fail both the well-formed check and the
// "reaches the page" check for a row that is working exactly as intended.
for (const sec of m.LORCANA_GEAR)
  for (const it of sec.items) if (it.asin) all.push(["gear " + it.name, it.asin]);

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
    m.gearUrl(it).includes("tag=packsink-20"))));
// An entry is either a curated product page or a tagged search, never both and
// never neither. Neither is the dangerous one: amazonUrl(undefined) returns
// null, so the row renders as a dead <a href> that looks completely normal.
ok("every gear item is exactly one of asin or search",
  m.LORCANA_GEAR.every((s) => s.items.every((it) =>
    (!!it.asin) !== (!!it.q))),
  JSON.stringify(m.LORCANA_GEAR.flatMap((s) => s.items)
    .filter((it) => (!!it.asin) === (!!it.q)).slice(0, 3)));
ok("every gear search carries real terms",
  m.LORCANA_GEAR.every((s) => s.items.every((it) =>
    !it.q || it.q.trim().length > 3)));
// The home panel renders only the `home` sections and signs off with "Official
// Ravensburger accessories". Marking a third-party section `home` would make
// that sentence false — silently, since nothing about the render would change.
ok("every home-panel section is first-party",
  m.LORCANA_GEAR.filter((s) => s.home).every((s) => s.items.every((it) => it.asin)));
ok("the home panel is a strict subset of the page",
  m.LORCANA_GEAR.filter((s) => s.home).length < m.LORCANA_GEAR.length);

// ── The compliance boundary ─────────────────────────────────────────────────
// An Amazon price or image may only ever come from Amazon's own API, and we
// hold no Creators API keys. So a price or an image URL appearing in this
// static catalog means somebody typed one in by hand off a listing — which is
// exactly the unlicensed use that costs accounts. Assert there are none.
// (This does NOT forbid prices forever — see the amazonUrl comment for the
// terms that apply once keys exist. It forbids hand-copied ones.)
const gearBlob = JSON.stringify(m.LORCANA_GEAR);
ok("gear stores no prices", !/\$|\bprice\b/i.test(gearBlob));
ok("gear stores no image URLs", !/https?:\/\//i.test(gearBlob));
const catalogBlob = JSON.stringify([m.AMAZON_ASIN_BY_SET, m.AMAZON_SEALED_RULES, m.AMAZON_PUZZLE_ASINS]);
ok("the ASIN catalog stores nothing but ASINs and keys", !/https?:\/\/|\$/.test(catalogBlob));

// ── The /gear directory ─────────────────────────────────────────────────────
// It is BUILT from the same maps the resolver reads, so the thing to guard is
// that the build stayed faithful — not the data, which is already covered.
const dir = m.amazonDirectory();
ok("the directory has sections", dir.length >= 6, "only " + dir.length);
ok("every section has a title and items",
  dir.every((s) => s.title && s.items && s.items.length > 0));
ok("every directory item has a name and a tagged link",
  dir.every((s) => s.items.every((it) =>
    it.name && it.url && it.url.includes("tag=packsink-20"))),
  JSON.stringify(dir.flatMap((s) => s.items).filter((it) => !it.name || !it.url).slice(0, 3)));

// The one that matters: a curated ASIN that never reaches the page is money
// left on the table AND invisible — nothing renders it, so nobody notices.
const asinOf = (u) => (u.match(/\/dp\/([A-Z0-9]{10})/) || [])[1];
// Search-backed rows have no ASIN by design, so they are simply not part of
// this question — filter them out rather than letting an `undefined` sit in
// the set and fail the "invents none" check below for the wrong reason.
const onPage = new Set(dir.flatMap((s) => s.items.map((it) => asinOf(it.url))).filter(Boolean));
const missing = all.map(([, a]) => a).filter((a) => !onPage.has(a));
ok("every curated ASIN appears on the /gear page",
  missing.length === 0, missing.join(", "));
ok("…and the page invents none", [...onPage].every((a) => seen.has(a)),
  [...onPage].filter((a) => !seen.has(a)).join(", "));

// A rule with no label is silently dropped from the directory, so its ASIN
// would fail the check above — but name the real cause rather than the symptom.
const unlabelled = m.AMAZON_SEALED_RULES.filter((r) => !r.label || !r.group);
ok("every sealed rule carries a label and a group",
  unlabelled.length === 0, JSON.stringify(unlabelled.map((r) => r.tokens)));
ok("rule groups are ones the directory renders",
  m.AMAZON_SEALED_RULES.every((r) => r.group === "gift" || r.group === "deck"),
  JSON.stringify([...new Set(m.AMAZON_SEALED_RULES.map((r) => r.group))]));

// Sets run newest-first: a shopper wants the current set, not The First Chapter.
const boxes = dir.find((s) => s.title === "Booster boxes");
ok("booster boxes run newest first",
  boxes && boxes.items[0].name === "Wilds Unknown",
  boxes && boxes.items[0].name);

// Same no-prices/no-images rule as the static catalog, now over what RENDERS.
const dirBlob = JSON.stringify(dir);
ok("the directory renders no prices", !/\$[0-9]/.test(dirBlob));
// Product pages AND search pages are both links this code generates; what the
// check is actually hunting is an image CDN URL somebody pasted off a listing,
// which is the unlicensed use. Anything else on amazon.com is ours.
const OURS = /^https?:\/\/www\.amazon\.com\/(dp\/|s\?)/;
ok("the directory renders no image URLs",
  (dirBlob.match(/https?:\/\/[^"]+/g) || []).every((u) => OURS.test(u)),
  (dirBlob.match(/https?:\/\/[^"]+/g) || []).filter((u) => !OURS.test(u)).slice(0, 3).join(" "));

// ── Cards on Amazon ─────────────────────────────────────────────────────────
// Singles are always a search. The name's dash goes (Amazon titles never carry
// it) and a chase rarity is added, or the common outranks the Enchanted.
const elsaUrl = m.amazonCardSearchUrl("Elsa - Spirit of Winter", "Common");
ok("a card search carries the tag", elsaUrl.includes("tag=packsink-20"), elsaUrl);
ok("…searches the name without its dash",
  decodeURIComponent(elsaUrl).includes("k=Disney Lorcana Elsa Spirit of Winter&"), decodeURIComponent(elsaUrl));
ok("…and adds no base rarity", !/Common/.test(decodeURIComponent(elsaUrl)));
ok("a chase card searches with its rarity",
  decodeURIComponent(m.amazonCardSearchUrl("Elsa - Spirit of Winter", "enchanted")).includes("Spirit of Winter Enchanted&"));
ok("an em-dashed tile title is cleaned the same way",
  decodeURIComponent(m.amazonCardSearchUrl("Elsa — Spirit of Winter", "Rare")).includes("k=Disney Lorcana Elsa Spirit of Winter&"));
check("no name yields no link", m.amazonCardSearchUrl("", "Rare"), null);

// ── Resolver fixes found against the live catalog (2026-09-10) ──────────────
// A case or display is not the single product a rule's ASIN points at.
check("a case never takes a rule's listing",
  m.amazonForSealed({name: "Disney Lorcana: Fabled Collection Starter Set Case", product_type: "Starter Deck"}, "Fabled").exact, false);
check("…nor does a display",
  m.amazonForSealed({name: "Disney Lorcana: Wilds Unknown 2-Player Starter Set Display", product_type: "Starter Deck"}, "Wilds Unknown").exact, false);
check("a later Collection Starter Set no longer lands on Fabled's listing",
  m.amazonForSealed({name: "Disney Lorcana: Attack of the Vine! Collection Starter Set - Rapunzel Edition", product_type: "Starter Deck"}, "Attack of the Vine!").exact, false);
const fabledStarter = m.amazonForSealed({name: "Disney Lorcana: Fabled Collection Starter Set", product_type: "Starter Deck"}, "Fabled");
ok("…while Fabled's own still does", fabledStarter.exact && fabledStarter.url.includes("B0FM8FBTNM"), fabledStarter.url);
const stitchLive = m.amazonForSealed({name: "Disney Lorcana: Stitch Collector's Gift Set", product_type: "Gift Set"}, null);
ok("the gift set resolves under TCGplayer's own name for it",
  stitchLive.exact && stitchLive.url.includes("B0DK5WC19T"), stitchLive.url);
const d100 = m.amazonForSealed({name: "Disney Lorcana: Disney100 Collector's Edition", product_type: "Collector's Edition"}, null);
ok("Disney100 resolves under its catalog spelling", d100.exact && d100.url.includes("B0CLQR9D3N"), d100.url);

// ── Photos: TCGplayer's, never Amazon's ─────────────────────────────────────
// Amazon licenses its images only through its API, so every photo on an
// Amazon-linked tile is TCGplayer's (or, for the puzzles, Ravensburger's),
// derived at render from an id — which is what keeps URLs out of the catalog.
check("a product photo comes from TCGplayer's CDN at tile size",
  m.tcgProductImg(149665), "https://tcgplayer-cdn.tcgplayer.com/product/149665_in_400x400.jpg");
ok("…and a thumbnail uses the stored 200px image", m.tcgProductImg(149665, 200).endsWith("/149665_200w.jpg"));
check("no id yields no photo", m.tcgProductImg(null), null);
check("a stored catalog image is re-sized for a tile",
  m.tcgImgSized("https://tcgplayer-cdn.tcgplayer.com/product/690384_200w.jpg"),
  "https://tcgplayer-cdn.tcgplayer.com/product/690384_in_400x400.jpg");
ok("a non-TCGplayer image passes through untouched",
  m.tcgImgSized("https://ravensburger.cloud/images/produktseiten/520x445/12001621.webp").startsWith("https://ravensburger.cloud/"));
const gearIds = m.LORCANA_GEAR.flatMap((s) => s.items.filter((it) => "tcg" in it).map((it) => it.tcg));
ok("every gear photo id is a positive integer",
  gearIds.every((n) => Number.isInteger(n) && n > 0), JSON.stringify(gearIds.filter((n) => !(Number.isInteger(n) && n > 0))));
ok("most gear rows have a photo", gearIds.length >= 30, "only " + gearIds.length);
ok("every gear section names a fallback glyph", m.LORCANA_GEAR.every((s) => typeof s.glyph === "string" && s.glyph));

// ── The home shelf ──────────────────────────────────────────────────────────
const shelfSets = {wu: "Wilds Unknown", aotv: "Attack of the Vine!", az: "Azurite Sea"};
const sRow = (pid, set, type, name, mkt, low) => ({tcgplayer_product_id: pid, set_id: set, product_type: type,
  name: "Disney Lorcana: " + name, market_price: mkt, low_price: low, price_date: "2026-09-10",
  image_url: "https://tcgplayer-cdn.tcgplayer.com/product/" + pid + "_200w.jpg"});
const shelf = m.amazonShelfItems([
  sRow(1, "wu", "Booster Box", "Wilds Unknown Booster Box", 236.33, 220),
  sRow(2, "wu", "Booster Box", "Wilds Unknown Booster Box Case", 882.94, 850),
  sRow(3, "aotv", "Booster Box", "Attack of the Vine! Booster Box", 214.79, 200),
  sRow(4, "aotv", "Trove", "Attack of the Vine! Illumineer's Trove", 89.52, 80),
  sRow(5, "az", "Booster Box", "Azurite Sea Booster Box", 150, 140),
  sRow(6, "aotv", "Starter Deck", "Attack of the Vine! Collection Starter Set - Rapunzel Edition", 45.58, 40),
  sRow(7, null, "Gift Set", "Stitch Collector's Gift Set", 29.37, null),
  sRow(8, "wu", "Promo Single", "Wilds Unknown Puzzle Insert (Top Left)", 0.1, 0.1),
  sRow(9, "wu", "Booster Pack", "Wilds Unknown Sleeved Booster Pack Art Bundle [Set of 3]", 39.36, 30),
  sRow(10, "az", "Trove", "Azurite Sea Illumineer's Trove", null, 70),
], shelfSets);
const shelfNames = shelf.map((it) => it.name);
ok("the shelf carries curated listings",
  shelfNames.includes("Wilds Unknown Booster Box") && shelfNames.includes("Stitch Collector's Gift Set"), shelfNames.join(" | "));
ok("…the newest set's box as a search, labelled as one",
  shelf.some((it) => it.name === "Attack of the Vine! Booster Box" && it.exact === false), shelfNames.join(" | "));
ok("…and never a case, a promo single or a multi-unit bundle",
  !shelfNames.some((n) => /case|insert|set of 3/i.test(n)), shelfNames.join(" | "));
ok("a search for anything else stays off the shelf",
  !shelfNames.includes("Attack of the Vine! Collection Starter Set - Rapunzel Edition"), shelfNames.join(" | "));
check("the shelf opens on the newest set", shelf[0].setName, "Attack of the Vine!");
ok("product types alternate rather than bunching", shelf[1].type !== shelf[0].type,
  shelf.slice(0, 3).map((it) => it.type).join(", "));
const azTrove = shelf.find((it) => it.name === "Azurite Sea Illumineer's Trove");
ok("market price first, low only when market is missing",
  azTrove && azTrove.priceBasis === "low" && azTrove.price === 70, JSON.stringify(azTrove));
ok("every sealed shelf tile carries both links",
  shelf.filter((it) => it.type !== "Puzzles").every((it) => it.tcg && it.amazon.includes("tag=packsink-20")));

// Cap: one row per curated set x type is more than the shelf holds.
const TYPE_ROW = {"Booster Boxes": ["Booster Box", "Booster Box"],
  "Illumineer's Troves": ["Trove", "Illumineer's Trove"], "Booster Packs": ["Booster Pack", "Booster Pack"]};
const bigSets = {}, bigRows = [];
let bigPid = 1000;
for (const [type, bySet] of Object.entries(m.AMAZON_ASIN_BY_SET))
  for (const set of Object.keys(bySet)) {
    bigSets["id:" + set] = set;
    bigRows.push(sRow(bigPid++, "id:" + set, TYPE_ROW[type][0], set + " " + TYPE_ROW[type][1], 50, 45));
  }
const bigShelf = m.amazonShelfItems(bigRows, bigSets);
check("the shelf is capped", bigShelf.length, m.AMAZON_SHELF_MAX);
ok("every curated tile links its exact listing",
  bigShelf.filter((it) => it.exact).every((it) => /\/dp\/[A-Z0-9]{10}\?tag=packsink-20/.test(it.amazon)));
const shelfPhotos = [...shelf, ...bigShelf].map((it) => it.img).filter(Boolean);
ok("no shelf photo is Amazon's",
  shelfPhotos.every((u) => !/media-amazon|ssl-images-amazon|images-amazon/i.test(u)));
ok("every shelf photo is TCGplayer's or Ravensburger's",
  shelfPhotos.every((u) => /^https:\/\/(tcgplayer-cdn\.tcgplayer\.com|ravensburger\.cloud)\//.test(u)),
  shelfPhotos.filter((u) => !/^https:\/\/(tcgplayer-cdn\.tcgplayer\.com|ravensburger\.cloud)\//.test(u)).slice(0, 3).join(" "));

// /gear joins its sealed rows to the same matches by Amazon URL, so a curated
// listing with a live TCGplayer row has to find it there.
const gearMatches = m.amazonSealedMatches([sRow(1, "wu", "Booster Box", "Wilds Unknown Booster Box", 236.33, 220)], shelfSets);
const wuBox = m.amazonDirectory().find((s) => s.title === "Booster boxes").items.find((it) => it.name === "Wilds Unknown");
ok("a /gear row finds its TCGplayer photo and price",
  !!(gearMatches.get(wuBox.url) && gearMatches.get(wuBox.url).price === 236.33));

// ── The grading-queue supplies note ─────────────────────────────────────────
// Source-text checks, because the block is JSX inside a component rather than a
// pure function — but every way it breaks is silent, so it is worth pinning:
//
//   * The gate is what separates "a fact you need right now" from an advert. If
//     it inverts or is dropped, the note shows for cards ALREADY at the grader,
//     where the packing question is answered — nothing errors, it just starts
//     reading as a shop prompt on somebody's collection page.
//   * A dropped tag earns nothing and looks perfectly fine.
//   * The disclosure is required near the link, not only in a footer.
const queue = grab("const GradingQueueSection = ", NL + "};");
ok("the queue's supplies note is gated on cards still to submit",
  /toSubmit\s*>\s*0/.test(queue) && /gq-supplies/.test(queue));
ok("…and 'to submit' is derived from the status, not the queue length",
  /status\s*!==\s*"at_grader"/.test(queue));
ok("its link goes through the tagged search helper",
  /amazonSearchUrl\(/.test(queue) && !/href=\$\{"https/.test(queue));
ok("it is marked sponsored + nofollow",
  /rel="noopener nofollow sponsored"/.test(queue));
ok("it carries the Associate disclosure",
  /as an Amazon Associate I earn from qualifying purchases/i.test(queue));
// PSA's spec is the reason the note exists; losing it leaves a bare shop link.
ok("it states PSA's semi-rigid spec and the toploader warning",
  /3 5\/16/.test(queue) && /toploader/i.test(queue));

console.log(NL + (failed ? failed + " FAILED" : "all passed"));
process.exit(failed ? 1 : 0);
