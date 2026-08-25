// test_screener_url.mjs — guards the Screener + Price Graphing URL codecs.
//
//     node scripts/test_screener_url.mjs
//
// Extracts the real functions out of Index.html rather than restating them, so
// they can't drift from what ships.
//
// Both codecs fail silently, which is why they need a test. A dropped or
// mangled field in encodeScreenerState produces a link that opens a page
// looking perfectly normal — just not the page that was sent, and the sender
// can't tell because their own tab still holds the state. decodeCompareItems
// is worse: a printing that decodes to the wrong value graphs a real series
// for the wrong SKU, which reads as a data bug rather than a link bug.
//
// The adversarial cases matter more than the happy path. The search box
// accepts every character a keyboard can produce, including this codec's own
// `;` `:` `,` `~` delimiters, and set names carry apostrophes.
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

const pieces = [
  // SOLD_FILTER_OFF is a decode-time default, so the real one has to come along.
  grab("const SOLD_FILTER_OFF = ", NL),
  grab("const COMPARE_MAX = 18;", NL),
  grab("const SCREENER_STATE_FIELDS = [", NL + "];"),
  grab("const _scEsc = ", NL),
  grab("const _scUnesc = ", NL),
  grab("const _scArr = ", NL),
  grab("const _scSameArr = ", NL),
  grab("function encodeScreenerState(payload){", NL + "}"),
  grab("function decodeScreenerState(str){", NL + "}"),
  grab("const CMP_PRINTING_TO = ", NL),
  grab("const CMP_PRINTING_FROM = ", NL),
  grab("const encodeCmpPrinting = ", NL),
  // Two physical lines — grab to the statement's real end, not the first NL.
  grab("const decodeCmpPrinting = ", "(CMP_PRINTING_FROM[c] || null);"),
  grab("function encodeCompareItems(items){", NL + "}"),
  grab("function decodeCompareItems(str){", NL + "}"),
];

const mod = await import(
  "data:text/javascript," +
    encodeURIComponent(
      pieces.join(NL) +
        NL +
        "export {encodeScreenerState, decodeScreenerState, encodeCompareItems, decodeCompareItems, SCREENER_STATE_FIELDS};"
    )
);
const {
  encodeScreenerState,
  decodeScreenerState,
  encodeCompareItems,
  decodeCompareItems,
  SCREENER_STATE_FIELDS,
} = mod;

let failures = 0;
function check(name, cond, detail) {
  if (cond) return;
  failures++;
  console.error("FAIL " + name + (detail ? "  -> " + detail : ""));
}
function eq(name, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  check(name, g === w, "got " + g + " want " + w);
}

// ── The field table itself ──────────────────────────────────────────────
{
  const urlKeys = SCREENER_STATE_FIELDS.map((f) => f[1]);
  check(
    "url keys are unique",
    new Set(urlKeys).size === urlKeys.length,
    "duplicate: " + urlKeys.filter((k, i) => urlKeys.indexOf(k) !== i).join(",")
  );
  const payloadKeys = SCREENER_STATE_FIELDS.map((f) => f[0]);
  check(
    "payload keys are unique",
    new Set(payloadKeys).size === payloadKeys.length
  );
  const kinds = new Set(SCREENER_STATE_FIELDS.map((f) => f[2]));
  for (const k of kinds) {
    check(
      "kind '" + k + "' is one the codec handles",
      ["str", "bool", "arr", "tri", "nstr", "sold"].includes(k)
    );
  }
  // A url key must not contain the delimiters, or the chunk splitter mis-parses.
  for (const k of urlKeys) {
    check("url key '" + k + "' has no delimiter", !/[;:,~]/.test(k));
  }
}

// ── Defaults produce an empty string ────────────────────────────────────
{
  const defaults = decodeScreenerState("");
  eq("round-trip of pure defaults encodes to nothing", encodeScreenerState(defaults), "");
  check("a bare /screener has no ?v=", encodeScreenerState({}) === "");
}

// ── Every field survives a round trip ───────────────────────────────────
{
  const payload = {
    preset: "buyouts",
    moverWin: "pct_90d",
    priceMode: "market",
    search: "ench elsa",
    collFilter: "owned",
    pctWin: "pct_7d",
    density: "compact",
    minPrice: "12.5",
    maxPrice: "400",
    minPct: "-30",
    maxPct: "80",
    filterLegality: "core",
    sortKey: "market",
    sortKey2: "set_rank",
    sortDesc: false,
    sortDesc2: false,
    showAllWins: true,
    showGraded: true,
    showSealed: false,
    showFoil: false,
    showNonFoil: false,
    filterDualInk: true,
    filterInkable: false,
    filterSet: ["Ursula's Return", "Azurite Sea"],
    filterRarities: ["Enchanted", "Iconic"],
    filterInks: ["Amber"],
    sigFilter: ["buy", "trend"],
    filterCosts: [1, 9],
    filterCardTypes: ["Character"],
    filterStrengths: [3],
    filterWillpowers: [4],
    filterLores: [2],
    filterKeywords: ["Bodyguard"],
    filterClassifications: ["Princess"],
    filterIllustrators: ["Nicholas Kole"],
    filterSealedTypes: ["Booster Boxes"],
    filterGraders: ["psa"],
    filterGrades: ["10", "9.5"],
    soldFilter: { mode: "between", days: "7", from: "2026-01-01", to: "2026-02-01" },
  };
  const round = decodeScreenerState(encodeScreenerState(payload));
  for (const [key, , kind] of SCREENER_STATE_FIELDS) {
    if (payload[key] === undefined) continue;
    if (kind === "arr") {
      // Numeric chip values (cost / strength) come back as strings — the
      // component rebuilds Sets from them and compares as strings, so this is
      // the contract, but it must be STABLE, not accidental.
      eq("round-trip " + key, round[key].map(String), payload[key].map(String));
    } else if (kind === "sold") {
      eq("round-trip " + key + ".mode", round[key].mode, payload[key].mode);
      eq("round-trip " + key + ".from", round[key].from, payload[key].from);
      eq("round-trip " + key + ".to", round[key].to, payload[key].to);
    } else {
      eq("round-trip " + key, round[key], payload[key]);
    }
  }
}

// ── Adversarial text ────────────────────────────────────────────────────
{
  // Every delimiter this codec owns, plus its own escape marker, plus the
  // percent sign that a naive implementation would double-encode.
  const nasty = 'a;b:c,d~e~4f%20g"h\'i';
  const round = decodeScreenerState(encodeScreenerState({ search: nasty }));
  eq("search with every delimiter survives", round.search, nasty);

  const setNames = ["Ursula's Return", "a,b", "x;y", "p:q", "t~u"];
  const r2 = decodeScreenerState(encodeScreenerState({ filterSet: setNames }));
  eq("set names with delimiters survive", r2.filterSet, setNames);

  // An empty search must not be encoded, and must not resurrect as undefined.
  eq("empty search stays empty", decodeScreenerState(encodeScreenerState({ search: "" })).search, "");
}

// ── Decode is defensive ─────────────────────────────────────────────────
{
  eq("garbage decodes to defaults", decodeScreenerState("!!!!").preset, "all");
  eq("unknown key is ignored", decodeScreenerState("zz:1;p:movers").preset, "movers");
  eq("chunk with no colon is ignored", decodeScreenerState("nocolon;p:losers").preset, "losers");
  eq("null decodes to defaults", decodeScreenerState(null).preset, "all");
  // Missing fields must come back as their DEFAULT, never undefined — a
  // partial link that left a Set undefined would crash `new Set(undefined)`
  // consumers or, worse, keep the previous screen's chips.
  const partial = decodeScreenerState("p:movers");
  for (const [key, , kind] of SCREENER_STATE_FIELDS) {
    if (kind === "arr") check("partial link: " + key + " is an array", Array.isArray(partial[key]));
    else check("partial link: " + key + " is defined", partial[key] !== undefined);
  }
  eq("partial link resets sold filter", partial.soldFilter.mode, "any");
}

// ── Compare-list codec ──────────────────────────────────────────────────
{
  const items = [
    { kind: "card", productId: 123456, printing: "Normal" },
    { kind: "card", productId: 123457, printing: "Cold Foil" },
    { kind: "card", productId: 123458, printing: "Holofoil" },
    { kind: "sealed", productId: 999001 },
    { kind: "set", setId: "set_abc123" },
    { kind: "graded", gradedCardId: "crd_deadbeef", grader: "psa", grade: "9.5", gradedPrinting: "Foil" },
    { kind: "graded", gradedCardId: "crd_cafe", grader: "cgc", grade: "10", gradedPrinting: null },
    { kind: "index", indexScope: "all", indexKey: "" },
    // scope_key carries a "|" and a space; neither may be re-split or dropped.
    { kind: "index", indexScope: "setrarity", indexKey: "set_abc123|Super Rare" },
    { kind: "index", watchlistId: "3f1c0e88-0000-4000-8000-000000000abc" },
  ];
  const round = decodeCompareItems(encodeCompareItems(items));
  eq("compare list length", round.length, items.length);
  eq("card printing Normal", round[0], { kind: "card", productId: 123456, printing: "Normal" });
  eq("card printing Cold Foil", round[1].printing, "Cold Foil");
  eq("card printing Holofoil", round[2].printing, "Holofoil");
  eq("sealed", round[3], { kind: "sealed", productId: 999001 });
  eq("set", round[4], { kind: "set", setId: "set_abc123" });
  // A grade containing a dot is the case a `.`-delimited encoding would break.
  eq("graded grade with a decimal", round[5].grade, "9.5");
  eq("graded foil printing", round[5].gradedPrinting, "Foil");
  eq("graded null printing stays null", round[6].gradedPrinting, null);

  // An unknown printing must round-trip verbatim rather than collapsing to
  // Normal — that would graph a real line for the wrong SKU.
  const odd = decodeCompareItems(
    encodeCompareItems([{ kind: "card", productId: 5, printing: "Rainbow Foil" }])
  );
  eq("unknown printing survives", odd[0].printing, "Rainbow Foil");

  eq("index scope round-trips", round[7], { kind: "index", indexScope: "all", indexKey: "" });
  // The one that would break a naive codec: "|" separates the composite key and
  // the rarity contains a space.
  eq("setrarity key survives its pipe and space", round[8].indexKey, "set_abc123|Super Rare");
  eq("custom index travels as its watchlist id", round[9],
    { kind: "index", watchlistId: "3f1c0e88-0000-4000-8000-000000000abc" });
  eq("an index with no scope is dropped", encodeCompareItems([{ kind: "index" }]), "");

  eq("empty encodes to nothing", encodeCompareItems([]), "");
  eq("empty decodes to nothing", decodeCompareItems(""), []);
  eq("garbage decodes to nothing", decodeCompareItems("nonsense~~~"), []);
  // Items missing their identifying field are dropped, not emitted half-formed.
  eq("card with no pid is dropped", encodeCompareItems([{ kind: "card" }]), "");
  eq("graded with no card_id is dropped", encodeCompareItems([{ kind: "graded", grader: "psa" }]), "");

  // A hand-edited link can't blow past the graph cap.
  const many = Array.from({ length: 40 }, (_, i) => "c~" + (1000 + i) + "~N").join(",");
  check("decode caps at COMPARE_MAX", decodeCompareItems(many).length <= 18,
    "got " + decodeCompareItems(many).length);
}

if (failures) {
  console.error(NL + failures + " check(s) failed.");
  process.exit(1);
}
console.log("test_screener_url: all checks passed");
