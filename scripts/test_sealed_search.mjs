// test_sealed_search.mjs — guards sealed product appearing in CARD search.
//
//     node scripts/test_sealed_search.mjs
//
// Extracts the real searchSealedProducts out of Index.html, house pattern.
//
// Two ways this feature goes wrong, and both are silent:
//
//  1. A COLLECTIBLE LEAKS IN. Pins, lore counters and puzzles are named after
//     cards — 27 of the 70 pins/counters are literal "Character - Version"
//     names and most of the rest are bare character names. Letting them in
//     drops ~70 card-named rows into card searches, every one of them also
//     unpriced, so a dead end on the surface whose whole job is a price. That
//     is exactly the "don't make card search worse" constraint, and nothing
//     errors when it breaks.
//
//  2. SEALED DISPLACES CARDS. The card list has to be computed WITHOUT
//     reference to the sealed list, so no query can cost a card its slot.
//     That is a source-level property; section 6 checks it.
import { readFileSync } from "node:fs";

// Index.html is CRLF on disk; normalise so the marker slices below can be
// written with plain newlines.
const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8")
  .split("\r\n").join("\n");
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
  grab("const searchNorm = (s) =>", ";" + NL),
  grab("const SEALED_DISPLAY_TYPE_ORDER = [", NL + "];"),
  grab("const SEALED_DISPLAY_TYPE_FOR = {", NL + "};"),
  grab("function isHiddenSealedListing(item){", NL + "}"),
  grab("function deriveSealedDisplayType(item){", NL + "}"),
  grab("const sealedDisplayTypeRank = (t) => {", NL + "};"),
  grabLine("const isUnpricedSealed = "),
  grabLine("const cleanSealedName = "),
  grabLine("const SEALED_SEARCH_MIN = "),
  grab("const searchSealedProducts = (sealedPrices, query, setNameById, limit = 6) => {", NL + "};"),
  "export {searchSealedProducts, SEALED_SEARCH_MIN};",
].join(NL)));
const { searchSealedProducts } = mod;

let pass = 0, fail = 0;
const ok = (cond, what) => { if (cond) { pass++; } else { fail++; console.error("  FAIL: " + what); } };

// ── a small catalog shaped like sealed_prices_latest ─────────────────────
const P = (o) => Object.assign({
  printing: "Normal", product_type: "Booster Box", set_id: "s1",
  low_price: 100, market_price: 110,
}, o);

const SETS = { s1: "Azurite Sea", s2: "Attack of the Vine!", s3: "Wilds Unknown" };

const CAT = [
  P({ name: "Disney Lorcana: Azurite Sea Booster Box", tcgplayer_product_id: 1 }),
  P({ name: "Disney Lorcana: Azurite Sea Booster Pack", product_type: "Booster Pack",
      tcgplayer_product_id: 2, low_price: 5, market_price: 6 }),
  P({ name: "Disney Lorcana: Azurite Sea Illumineer's Trove",
      product_type: "Illumineer's Trove", tcgplayer_product_id: 3 }),
  P({ name: "Disney Lorcana: Stitch Collector's Gift Set", product_type: "Gift Set",
      tcgplayer_product_id: 4 }),
  P({ name: "Disney Lorcana: Attack of the Vine! Booster Box", set_id: "s2",
      tcgplayer_product_id: 5 }),
  P({ name: "Disney Lorcana: Wilds Unknown Starter Deck", set_id: "s3",
      product_type: "Starter Deck", tcgplayer_product_id: 6 }),
];

// The rows that must NEVER be offered.
const POISON = [
  // A pin. Named exactly like a card, and unpriced.
  P({ name: "Mickey Mouse - Brave Little Tailor", is_collectible: true, product_type: "Pin",
      low_price: null, market_price: null, set_id: "__pins__", tcgplayer_product_id: 950000001 }),
  // A lore counter. Same shape.
  P({ name: "Belle - Mechanic Extraordinaire", is_collectible: true, product_type: "Lore Counter",
      low_price: null, market_price: null, set_id: "__lore_counters__", tcgplayer_product_id: 960000001 }),
  // A puzzle, also card-named.
  P({ name: "Elsa - The Fifth Spirit", is_puzzle: true, product_type: "Puzzle",
      low_price: null, market_price: null, set_id: "__puzzles__", tcgplayer_product_id: 912001932 }),
  // A retailer exclusive — a real box, but no TCGplayer price to show.
  P({ name: "Best Buddies Bundle", is_exclusive: true, product_type: "Bundle",
      low_price: null, market_price: null, set_id: null, tcgplayer_product_id: 930000001 }),
  // A collectible that somehow CARRIES a price. Nothing produces this today —
  // the static catalogs hardcode null — so without it the two guards overlap
  // completely and isUnpricedSealed is never tested on its own. It stops being
  // hypothetical the day anyone puts an estimated value on a pin, and the row
  // it would leak is a card-named one.
  P({ name: "Ariel - Whoseit Collector", is_collectible: true, product_type: "Pin",
      low_price: 18, market_price: 22, set_id: "__pins__", tcgplayer_product_id: 950000003 }),
  // Aggregate listings no sealed surface browses either.
  P({ name: "Disney Lorcana: Azurite Sea Booster Pack [Set of 3]", tcgplayer_product_id: 7 }),
  P({ name: "Disney Lorcana: Azurite Sea Art Bundle", tcgplayer_product_id: 8 }),
  // A promo single is a CARD's SKU, not sealed product.
  P({ name: "Disney Lorcana: Azurite Sea Promo", product_type: "Promo Single",
      tcgplayer_product_id: 9 }),
  // A foil printing row — every sealed surface keys on Normal.
  P({ name: "Disney Lorcana: Azurite Sea Booster Box", printing: "Foil",
      tcgplayer_product_id: 10 }),
  // Priced nowhere: nothing to show, so nothing to offer.
  P({ name: "Disney Lorcana: Azurite Sea Mystery Box", low_price: null, market_price: null,
      tcgplayer_product_id: 11 }),
];

const ALL = [...CAT, ...POISON];
const find = (q, limit) => searchSealedProducts(ALL, q, SETS, limit);

console.log("1. the poison rows are unreachable by any query");
{
  // Every poison row, searched for by its own exact name, must not return
  // itself. This is the check the whole feature is allowed to exist because of.
  for (const bad of POISON) {
    const got = find(bad.name, 50);
    ok(!got.some((r) => r.tcgplayer_product_id === bad.tcgplayer_product_id),
      'searching "' + bad.name + '" must not return that row');
  }
  // And by the bare character name, which is how somebody actually searches.
  for (const q of ["mickey", "belle", "elsa", "best buddies", "brave little tailor",
                    "ariel", "whoseit"]) {
    ok(find(q).length === 0, '"' + q + '" must match no sealed product');
  }
}

console.log("2. real product is found by name, type and set");
{
  ok(find("booster box").length === 2, '"booster box" finds both boxes');
  const az = find("azurite booster box");
  ok(az.length === 1 && az[0].tcgplayer_product_id === 1, "set + type narrows to the right box");
  ok(find("trove")[0].tcgplayer_product_id === 3, "a bare type word finds the trove");
  ok(find("stitch")[0].tcgplayer_product_id === 4, "a character-named gift set is still findable");
  ok(find("wilds unknown starter").length === 1, "set name plus partial type");
  ok(find("gift set").length === 1, "display type alone");
}

console.log("3. tokens are AND-ed, and display type orders the result");
{
  ok(find("azurite vine").length === 0, "two different sets at once matches nothing");
  const boxes = find("booster box");
  ok(boxes[0].name < boxes[1].name, "ties break alphabetically");
  // Four: the three whose own name says Azurite Sea, plus the Stitch gift set,
  // which is an Azurite Sea product and matches via the set name appended to
  // the haystack. A name hit outranks that, so Stitch sorts last.
  const az = find("azurite");
  ok(az.length === 4, "every priced Azurite Sea product matches, by name or by set");
  ok(az[0].tcgplayer_product_id === 1, "Booster Boxes rank ahead of packs by display type");
  ok(az[az.length - 1].tcgplayer_product_id === 4,
    "a set-only match sorts behind every name match");
}

console.log("4. the minimum query length, the cap, and missing inputs");
{
  ok(find("a").length === 0, "a single character matches nothing");
  ok(find("").length === 0, "empty matches nothing");
  ok(find("   ").length === 0, "whitespace matches nothing");
  ok(find("booster", 1).length === 1, "the limit is honoured");
  ok(searchSealedProducts(null, "booster box", SETS).length === 0, "a missing catalog is empty, not a throw");
  ok(searchSealedProducts([], "booster box", SETS).length === 0, "an empty catalog is empty");
  ok(searchSealedProducts(ALL, "booster box", null).length === 2, "a missing set map still works");
}

console.log("5. diacritics and apostrophes fold, as they do for cards");
{
  ok(find("illumineers trove").length === 1, "a dropped apostrophe still matches");
  ok(find("collectors gift").length === 1, "…and on the gift set");
}

console.log("6. source-level: sealed can never displace a card");
{
  const hqs = src.slice(src.indexOf("const HomeQuickSearch ="),
                        src.indexOf("const EVENT_TILES ="));
  // The card suggestions must stay a function of [q, raw] alone. If a future
  // edit folds sealed into them, cards start losing slots to boxes.
  ok(/const suggestions = useMemo\([\s\S]*?\}, \[q, raw\]\);/.test(hqs),
    "home card suggestions still depend on [q, raw] only");
  ok(/sealedSuggestions[\s\S]{0,400}searchSealedProducts/.test(hqs),
    "home sealed list comes from searchSealedProducts");
  ok(hqs.indexOf('home-quick-search-divider">Sealed products') >
     hqs.indexOf('home-quick-search-divider">Variants'),
    "the home sealed section renders AFTER the cards, not before");

  const cb = src.slice(src.indexOf("const CardBrowser ="),
                       src.indexOf("const CardsView ="));
  ok(/if\(deckMode \|\| !onOpenSealed\) return \[\];/.test(cb),
    "CardBrowser offers no sealed inside the deck editor");
  ok(/searchSealedProducts\(sealedPrices, filter\.search/.test(cb),
    "CardBrowser keys sealed on the TYPED text, never the chips");
  ok(cb.indexOf('class="cards-sealed"') > cb.indexOf('class="cards-grid'),
    "the sealed section renders after the card grid");

  // The priced-only rule, asserted at source: these five predicates are what
  // keep the card-named collectibles out, and dropping any one is silent.
  const fn = src.slice(src.indexOf("const searchSealedProducts ="),
                       src.indexOf("// ── Amazon ASIN catalog"));
  for (const guard of ['p.printing !== "Normal"', 'p.product_type === "Promo Single"',
                       "isUnpricedSealed(p)", "isHiddenSealedListing(p)",
                       "p.low_price == null && p.market_price == null"]) {
    ok(fn.includes(guard), "the " + guard + " guard is still there");
  }
}

console.log((fail ? "\nFAILED " : "\nOK ") + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
