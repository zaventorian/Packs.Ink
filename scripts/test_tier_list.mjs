// Guards the Tier List link codec (Analytics » Tier List, /tierlist).
// Runs the REAL functions out of Index.html. Every way this breaks is silent:
// a shared link still opens, it just shows the wrong cards in the wrong tiers.
import fs from "node:fs";
import vm from "node:vm";

const index = fs.readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const start = index.indexOf("const TIER_DEFAULTS = [");
const end = index.indexOf("const tierReadStore = () => {");
if(start < 0 || end < start) throw new Error("tier list block not found in Index.html");
const block = index.slice(start, end);

const MAINLINE_SETS = ["The First Chapter", "Rise of the Floodborn", "Into the Inklands",
  "Ursula's Return", "Shimmering Skies", "Azurite Sea", "Archazia's Island",
  "Reign of Jafar", "Fabled", "Whispers in the Well", "Winterspell",
  "Wilds Unknown", "Attack of the Vine!", "Hyperia City"];
const ctx = vm.createContext({MAINLINE_SETS, URLSearchParams, Map, Set,
  window: {location: {pathname: "/", search: ""}}});
vm.runInContext(block + "\n;globalThis.T = {tierPools, tierClean, tierEncode, tierDecode, tierLabelsParam, tierParseLabels, tierQuery, tierParamsFrom, TIER_COUNT};", ctx);
const T = ctx.T;

let fails = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if(!ok){ fails++; console.log("FAIL  " + name + "\n      got  " + JSON.stringify(got) + "\n      want " + JSON.stringify(want)); }
  else console.log("  ok  " + name);
};

// A Hyperia City-shaped pool: 18 Enchanted at 223-240, 2 Iconic at 241-242,
// plus rows the pool must ignore.
const raw = [];
for(let n = 223; n <= 242; n++){
  raw.push({Set: "Hyperia City", card_id: "c" + n, Rarity: n <= 240 ? "Enchanted" : "Iconic",
    Number: String(n), img_normal: "/img/" + n});
  raw.push({Set: "Hyperia City", card_id: "c" + n, Rarity: n <= 240 ? "Enchanted" : "Iconic",
    Number: String(n), img_normal: "/img/" + n, Printing: "Foil"});
}
raw.push({Set: "Hyperia City", card_id: "c10", Rarity: "Rare", Number: "10"});
raw.push({Set: "Hyperia City", card_id: "c223::variant::x", Rarity: "Enchanted", Number: "223"});
raw.push({Set: "Promo Set 1", card_id: "p1", Rarity: "Enchanted", Number: "1"});
const pools = T.tierPools(raw);
const pool = pools.get("Hyperia City");
check("pool: every Enchanted + Iconic once, printing rows folded", pool.length, 20);
check("pool: oldest number first", [pool[0].num, pool[19].num], [223, 242]);
check("pool: non-mainline sets left out", pools.has("Promo Set 1"), false);
check("pool: Iconics counted", pool.filter(p => p.rarity === "Iconic").length, 2);

const list = {tiers: [["c242", "c223"], ["c230", "c225"], [], ["c240"], []], title: "", labels: null};
const enc = T.tierEncode(list.tiers, pool);
check("encode: one char per card, trailing empty tiers dropped", enc, "j0.72..h");
check("decode: round trip", T.tierDecode(enc, pool), list.tiers);
check("decode: a card can only sit in one tier", T.tierDecode("00.0", pool)[0], ["c223"]);
check("decode: unknown offsets ignored", T.tierDecode("z", pool)[0], []);
check("decode: never more tiers than rows", T.tierDecode("0.1.2.3.4.5.6", pool).length, T.TIER_COUNT);

check("labels: defaults travel as nothing", T.tierLabelsParam(["S", "A", "B", "C", "D"]), "");
check("labels: null travels as nothing", T.tierLabelsParam(null), "");
const lp = T.tierLabelsParam(["GOAT", "A", "B", "C", "Mid"]);
check("labels: renamed list survives the URL", T.tierParseLabels(new URLSearchParams("tt=" + encodeURIComponent(lp)).get("tt")),
  ["GOAT", "A", "B", "C", "Mid"]);
check("labels: the separator cannot appear inside a label", T.tierLabelsParam(["a_b", "A", "B", "C", "D"]), "a b_A_B_C_D");

const q = T.tierQuery("Hyperia City", {...list, title: "My list", labels: ["GOAT", "A", "B", "C", "D"]}, pool);
const back = T.tierParamsFrom("?" + q);
check("query: set travels as its number", new URLSearchParams(q).get("ts"), "14");
check("query: full round trip", [back.set, T.tierDecode(back.tl, pool), back.tn, T.tierParseLabels(back.tt)],
  ["Hyperia City", list.tiers, "My list", ["GOAT", "A", "B", "C", "D"]]);
check("query: none of its params is ?t= (the trade-link param)", new URLSearchParams(q).has("t"), false);
check("query: no params means no link", T.tierParamsFrom("?a=ev"), null);
check("query: an out-of-range set number is dropped, not guessed", T.tierParamsFrom("?ts=99&tl=0").set, null);

const clean = T.tierClean({tiers: [["c223", "nope", "c223"], ["c223", "c224"]], title: "x".repeat(200)}, pool);
check("clean: unknown ids and duplicates dropped", clean.tiers.slice(0, 2), [["c223"], ["c224"]]);
check("clean: always five tiers", clean.tiers.length, T.TIER_COUNT);
check("clean: title capped", clean.title.length, 60);

if(fails){ console.log(`\n${fails} failure(s)`); process.exit(1); }
console.log("\nall passed");
