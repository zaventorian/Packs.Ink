// Guards the Tier List link codec (Analytics » Tier List, /tierlist).
// Runs the REAL functions out of Index.html. Every way this breaks is silent:
// a shared link still opens, it just shows the wrong cards in the wrong tiers.
import fs from "node:fs";
import vm from "node:vm";
import { TIER_SETS, tierDecodeNums, tierPreviewFrom } from "../worker/tierlist.mjs";

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
vm.runInContext(block + "\n;globalThis.T = {tierPools, tierClean, tierEncode, tierDecode, tierLabelsParam, tierParseLabels, tierQuery, tierParamsFrom, tierToStored, tierFromStored, TIER_COUNT};", ctx);
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
check("encode: base, then one char per card, trailing empty tiers dropped", enc, "223-j0.72..h");
check("decode: round trip", T.tierDecode(enc, pool), list.tiers);
check("decode: a card can only sit in one tier", T.tierDecode("223-00.0", pool)[0], ["c223"]);
check("decode: a first-day code with no base still reads", T.tierDecode("j0.72..h", pool), list.tiers);
check("encode: nothing ranked is an empty code", T.tierEncode([[], [], [], [], []], pool), "");
// A lower-numbered chase card revealed after a link was shared must not shift it.
const raw2 = raw.concat([{Set: "Hyperia City", card_id: "c221", Rarity: "Enchanted", Number: "221", img_normal: "/img/221"}]);
const pool2 = T.tierPools(raw2).get("Hyperia City");
check("decode: a later, lower card does not shift an old link", T.tierDecode(enc, pool2), list.tiers);
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

// Device storage is the link's shape, and the first-day id-keyed form still reads.
const stored = T.tierToStored({...list, title: "T", labels: ["GOAT", "A", "B", "C", "D"], t: 5}, pool);
check("store: kept as a code, not card ids", [stored.code, stored.title, stored.labels, stored.t], ["223-j0.72..h", "T", "GOAT_A_B_C_D", 5]);
check("store: round trip", T.tierFromStored(stored, pool).tiers, list.tiers);
check("store: a v523 id-keyed list still reads", T.tierFromStored({tiers: list.tiers, title: "x", t: 3}, pool).tiers, list.tiers);
check("store: nothing saved is a blank list", T.tierFromStored(undefined, pool).tiers.flat(), []);

// The link-preview worker reads the client's own codes, and indexes the same sets.
const msStart = index.indexOf("const MAINLINE_SETS = [");
const mainline = vm.runInNewContext("(" + index.slice(index.indexOf("[", msStart), index.indexOf("];", msStart) + 1) + ")");
check("worker: TIER_SETS matches MAINLINE_SETS in Index.html", TIER_SETS, mainline);
check("worker: decodes a based code to collector numbers", tierDecodeNums("223-j0.72..h", 999), [[242, 223], [230, 225], [], [240], []]);
check("worker: decodes a first-day code against the first card", tierDecodeNums("j0", 223)[0], [242, 223]);
const rows = [];
for(let n = 223; n <= 242; n++) rows.push({name: "Card" + n, version: "V", collector_number: String(n), rarity: n <= 240 ? "Enchanted" : "Iconic",
  image_large: "https://x/supabase/" + n + ".jpg", tcgplayer_product_id: n === 242 ? 123 : null});
const pv = tierPreviewFrom("?" + q, rows);
check("worker: preview title", pv.title, "My list | Packs.Ink");
check("worker: preview names each tier", pv.desc, "GOAT: Card242, Card223 · A: Card230, Card225 · C: Card240");
check("worker: preview image is the top card, TCGplayer's JPEG when listed", pv.image, "https://tcgplayer-cdn.tcgplayer.com/product/123_in_1000x1000.jpg");
const pv2 = tierPreviewFrom("?ts=14", rows);
check("worker: an empty list invites, and keeps the site image", [pv2.desc, pv2.image, pv2.title],
  ["Rank Hyperia City's 18 Enchanted and 2 Iconic cards and share the picture.", null, "Hyperia City Chase Card Tier List | Packs.Ink"]);
check("worker: an unknown set is no preview", tierPreviewFrom("?ts=99", rows), null);

if(fails){ console.log(`\n${fails} failure(s)`); process.exit(1); }
console.log("\nall passed");
