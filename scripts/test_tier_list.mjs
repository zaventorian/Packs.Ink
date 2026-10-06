// Guards the Tier List link codec (Analytics » Tier List, /tierlist).
// Runs the REAL functions out of Index.html. Every way this breaks is silent:
// a shared link still opens, it just shows the wrong cards in the wrong tiers.
import fs from "node:fs";
import vm from "node:vm";
import { TIER_SETS, tierDecodeNums, tierPreviewFrom, tierCustomCount, tierCustomPreviewFrom, tierCountFromLabels } from "../worker/tierlist.mjs";

const index = fs.readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const start = index.indexOf("const TIER_DEFAULTS = [");
const end = index.indexOf("const tierReadStore = () => {");
if(start < 0 || end < start) throw new Error("tier list block not found in Index.html");
const block = index.slice(start, end);

const MAINLINE_SETS = ["The First Chapter", "Rise of the Floodborn", "Into the Inklands",
  "Ursula's Return", "Shimmering Skies", "Azurite Sea", "Archazia's Island",
  "Reign of Jafar", "Fabled", "Whispers in the Well", "Winterspell",
  "Wilds Unknown", "Attack of the Vine!", "Hyperia City"];
const ctx = vm.createContext({MAINLINE_SETS, URLSearchParams, Map, Set, btoa, atob, escape, unescape,
  window: {location: {pathname: "/", search: ""}}});
vm.runInContext(block + "\n;globalThis.T = {tierPools, tierClean, tierEncode, tierDecode, tierLabelsParam, tierParseLabels, tierQuery, tierParamsFrom, tierToStored, tierFromStored, TIER_COUNT, tierCardIndex, tierCustomEncode, tierCustomDecode, tierCustomClean, tierCustomQuery, tierCustomToStored, tierCustomFromStored, TIER_CUSTOM_MAX, tierRenamed, tierWithAdded, tierWithRemoved, tierLabelsOf, TIER_MAX, TIER_MIN};", ctx);
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
// One low-numbered row in the pool (the scanner index holds two mis-rarity'd
// Hyperia City cards, #206 and #212) put #242 at offset 36, past what one
// character holds, and the card silently fell out of the link (2026-10-06).
const raw3 = raw.concat([{Set: "Hyperia City", card_id: "c206", Rarity: "Enchanted", Number: "206", img_normal: "/img/206"}]);
const pool3 = T.tierPools(raw3).get("Hyperia City");
const wide = [["c242", "c241"], [], [], [], []];
const enc3 = T.tierEncode(wide, pool3);
check("encode: a stray low card in the pool cannot push ranked cards out", T.tierDecode(enc3, pool3), wide);
check("encode: ...the base is the lowest RANKED card", enc3, "241-10");
check("encode: ...and the worker's preview decoder reads it", tierDecodeNums(enc3, 206)[0], [242, 241]);
check("encode: a code made against the old pool still reads against the new",
  T.tierDecode(T.tierEncode(list.tiers, pool), pool3), list.tiers);
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
// Bare on purpose: the link is posted beside the image of the list, so the
// preview must not repeat the tiers or show a card of its own.
check("worker: preview title is the list's own, no site suffix", pv.title, "My list");
check("worker: preview is one short line, no tier-by-tier names", pv.desc, "18 Enchanted · 2 Iconic · make your own at packs.ink/tierlist");
check("worker: preview carries no picture", [pv.bare, pv.image], [true, undefined]);
const pv2 = tierPreviewFrom("?ts=14", rows);
check("worker: an empty list invites", [pv2.desc, pv2.title],
  ["Rank Hyperia City's 18 Enchanted and 2 Iconic cards and share the picture.", "Hyperia City Chase Card Tier List"]);
check("worker: an unknown set is no preview", tierPreviewFrom("?ts=99", rows), null);

// ── Custom lists (My lists): any cards, keyed by printed set code + number ──
const CODE = {"Hyperia City": "14", "Promo Set 1": "P1", "The First Chapter": "1"};
const codeOf = (r) => CODE[r.Set];
const craw = [
  {Set: "The First Chapter", card_id: "m1", Number: "12", Rarity: "Common", img_normal: "/a"},
  {Set: "The First Chapter", card_id: "m1", Number: "12", Rarity: "Common", img_normal: "/a", Printing: "Foil"},
  {Set: "Hyperia City", card_id: "h223", Number: "223", Rarity: "Enchanted", img_normal: "/b"},
  {Set: "Hyperia City", card_id: "h5", Number: "5", Rarity: "Legendary", img_normal: "/c"},
  {Set: "Promo Set 1", card_id: "p1", Number: "1", Rarity: "Promo", img_normal: "/d"},
  // Same printed code + number as h5, a labelled one-off: keyed by id instead.
  {Set: "Hyperia City", card_id: "h5x", Number: "5", Rarity: "Legendary", variant_label: "Serial", img_normal: "/e"},
  // No usable set code: keyed by id.
  {Set: "Mystery", card_id: "crd_ünï/x", Number: "1", Rarity: "Rare", img_normal: "/f"},
  {Set: "Hyperia City", card_id: "h5::variant::two", Number: "5", Rarity: "Legendary"},
];
const idx = T.tierCardIndex(craw, codeOf);
check("custom index: one entry per card_id, variant clones left out", idx.byId.size, 6);
check("custom index: printed code + number is the key", idx.byId.get("h223").key, "14-223");
check("custom index: a code+number tie goes to the plain card", [idx.byId.get("h5").key, idx.byId.get("h5x").key], ["14-5", "#h5x"]);
check("custom index: no set code means an id key", idx.byId.get("crd_ünï/x").key, "#crd_ünï/x");

const groups = [["h223", "m1"], [], ["p1"], [], [], ["h5", "h5x", "crd_ünï/x"]];
const cenc = T.tierCustomEncode(groups, idx);
check("custom encode: sets switch by token, groups split by *", cenc.split(".").slice(0, 6), ["_14", "223", "_1", "12", "*", "*"]);
check("custom encode: every character survives URLSearchParams unescaped", new URLSearchParams({tc: cenc}).toString(), "tc=" + cenc);
const cdec = T.tierCustomDecode(cenc, idx);
check("custom decode: round trip (tiers)", cdec.tiers, groups.slice(0, 5));
check("custom decode: round trip (unranked pool)", cdec.pool, groups[5]);
check("custom decode: nothing missing", cdec.missing, 0);
check("custom encode: an empty list is an empty code", T.tierCustomEncode([[], [], [], [], [], []], idx), "");
check("custom encode: a pool-only list keeps its cards (a template)", T.tierCustomDecode(T.tierCustomEncode([[], [], [], [], [], ["p1"]], idx), idx).pool, ["p1"]);
const swapped = T.tierCardIndex(craw.map(r => r.card_id === "h223" ? {...r, card_id: "lorcast_h223"} : r), codeOf);
check("custom decode: a prestaged card swapped for Lorcast's id still reads", T.tierCustomDecode(cenc, swapped).tiers[0], ["lorcast_h223", "m1"]);
const odd = T.tierCustomDecode("_14.223.223.999.*.*.*.*.*.*.*.5", idx);
check("custom decode: duplicates dropped, unknown cards counted", [odd.tiers[0], odd.missing], [["h223"], 1]);
check("custom decode: extra group separators land in the pool", odd.pool, ["h5"]);
const many = [];
for(let n = 1; n <= 320; n++) many.push({Set: "Hyperia City", card_id: "x" + n, Number: String(n), Rarity: "Common", img_normal: "/x"});
const midx = T.tierCardIndex(many, codeOf);
const big = T.tierCustomDecode(T.tierCustomEncode([[], [], [], [], [], many.map(r => r.card_id)], midx), midx);
check("custom decode: capped at TIER_CUSTOM_MAX", big.pool.length, T.TIER_CUSTOM_MAX);

const clist = {tiers: [["h223"], ["m1"], [], [], []], pool: ["p1", "h5"], title: "Favourite frogs", labels: ["GOAT", "A", "B", "C", "D"], t: 9};
const cst = T.tierCustomToStored(clist, idx, {vis: "public"});
check("custom store: counts and extras carried", [cst.n, cst.rk, cst.vis, cst.t, cst.labels], [4, 2, "public", 9, "GOAT_A_B_C_D"]);
const cback = T.tierCustomFromStored(cst, idx);
check("custom store: round trip", [cback.tiers, cback.pool, cback.title, cback.labels], [clist.tiers, clist.pool, clist.title, clist.labels]);
check("custom clean: a card sits in one place only", T.tierCustomClean({tiers: [["p1"], ["p1"]], pool: ["p1", "nope"]}, idx).pool, []);
const cq = T.tierCustomQuery(clist, idx);
const cp = T.tierParamsFrom("?" + cq);
check("custom query: tc + tn + tt round trip", [T.tierCustomDecode(cp.tc, idx).pool, cp.tn, T.tierParseLabels(cp.tt)], [clist.pool, "Favourite frogs", clist.labels]);
check("custom query: no ?t= (the trade-link param)", new URLSearchParams(cq).has("t"), false);
check("params: a saved list's slug", T.tierParamsFrom("?tid=AbC123xyz0").tid, "AbC123xyz0");
check("params: a malformed slug is dropped", T.tierParamsFrom("?tid=../etc").tid, null);
check("params: no tc means null, an empty tc means an empty list", [T.tierParamsFrom("?tv=mine").tc, T.tierParamsFrom("?tc=").tc], [null, ""]);
check("params: the tab", T.tierParamsFrom("?tv=community").tv, "community");

check("worker: counts a custom code's cards the way the client wrote them", tierCustomCount(cenc), 6);
const cpv = tierCustomPreviewFrom("?" + cq, null);
check("worker: custom link preview", [cpv.title, cpv.desc, cpv.bare], ["Favourite frogs", "4 cards · make your own at packs.ink/tierlist", true]);
const spv = tierCustomPreviewFrom("?tid=AbC123xyz0", {slug: "AbC123xyz0", title: "Frogs", card_count: 1, display_name: "Zaven"});
check("worker: saved list preview names its author", [spv.title, spv.desc, spv.url],
  ["Frogs", "1 card · by Zaven · make your own at packs.ink/tierlist", "https://packs.ink/tierlist?tid=AbC123xyz0"]);
check("worker: a private or missing list is no preview", tierCustomPreviewFrom("?tid=AbC123xyz0", null), null);

// ── More (or fewer) than five tiers: the count rides in the labels ──
const six = T.tierWithAdded({...clist, labels: null, tiers: [["h223"], ["m1"], [], [], []]});
check("tiers: adding one gives six, named E", [six.tiers.length, T.tierLabelsOf(six)], [6, ["S", "A", "B", "C", "D", "E"]]);
const sixQ = T.tierCustomQuery({...six, tiers: [["h223"], [], [], [], [], ["m1"]]}, idx);
const sixP = T.tierParamsFrom("?" + sixQ);
const sixBack = T.tierCustomFromStored({code: sixP.tc, title: sixP.tn, labels: sixP.tt}, idx);
check("tiers: a six-tier list round-trips through its link", [sixBack.tiers.length, sixBack.tiers[5], sixBack.pool], [6, ["m1"], ["p1", "h5"]]);
check("tiers: the worker counts six from the labels", tierCountFromLabels(sixP.tt), 6);
const backToFive = T.tierWithRemoved(six, 5);
check("tiers: removing the extra one goes back to plain defaults (no ?tt=)", [backToFive.tiers.length, backToFive.labels], [5, null]);
const three = T.tierWithRemoved(T.tierWithRemoved({...clist, labels: null}, 1), 1);
check("tiers: removed tiers' cards go back to the pool", [three.tiers.length, T.tierLabelsOf(three), three.pool], [3, ["S", "C", "D"], ["p1", "h5", "m1"]]);
const threeBack = T.tierCustomFromStored(T.tierCustomToStored(three, idx), idx);
check("tiers: a three-tier list stores and reads back as three", [threeBack.tiers.length, T.tierLabelsOf(threeBack)], [3, ["S", "C", "D"]]);
let ten = {...clist, labels: null};
for(let i = 0; i < 9; i++) ten = T.tierWithAdded(ten);
check("tiers: never more than TIER_MAX", ten.tiers.length, T.TIER_MAX);
let two = {...clist, labels: null};
for(let i = 0; i < 9; i++) two = T.tierWithRemoved(two, 0);
check("tiers: never fewer than TIER_MIN", two.tiers.length, T.TIER_MIN);
check("tiers: renaming keeps the count", T.tierLabelsOf(T.tierRenamed(six, 5, "Trash")), ["S", "A", "B", "C", "D", "Trash"]);
check("tiers: a blank rename goes back to the letter", T.tierRenamed({...clist, labels: ["GOAT", "A", "B", "C", "D"]}, 0, " ").labels, null);
const chaseSix = {tiers: [["c242"], [], [], [], [], ["c223"]], title: "", labels: ["S", "A", "B", "C", "D", "E"]};
const chaseQ = T.tierQuery("Hyperia City", chaseSix, pool);
const cpq = T.tierParamsFrom("?" + chaseQ);
check("tiers: a six-tier chase list round-trips", T.tierFromStored({code: cpq.tl, labels: cpq.tt}, pool).tiers, chaseSix.tiers);
check("tiers: the worker reads the sixth tier of a chase link",
  tierDecodeNums(cpq.tl, 223, tierCountFromLabels(cpq.tt))[5], [223]);
check("tiers: a first-day five-label link is still five", T.tierParseLabels("S_A_B_C_D").length, 5);

// ── Custom lists on the account: privacy and deletes (2026-10-06) ──────────
// Each of these failed silently: a list made private was published again by a
// device holding an old copy; a copy of an unlisted list named its parent's
// slug (its whole secret) to every reader; a delete made signed out was undone
// by the next sign-in; and "Copy link" handed out a short link to a list the
// account had never received. The hook needs a signed-in account to run, so the
// decisions are run here and the wiring is pinned at source.
const grabConst = (name) => {
  const a = index.indexOf(`const ${name} = `);
  if(a < 0) throw new Error("missing " + name);
  const b = index.indexOf(";\n", a);
  return index.slice(a, b + 1);
};
const ls = {};
const ctx2 = vm.createContext({localStorage: {getItem: k => (k in ls ? ls[k] : null), setItem: (k, v) => { ls[k] = String(v); }}});
vm.runInContext(["tierCustomSendsVis", "tierForkParent"].map(grabConst).join("\n")
  + "\n" + index.slice(index.indexOf("const TIER_GONE_LS = "), index.indexOf("const tierCustomRead = () => {"))
  + "\n;globalThis.S = {tierCustomSendsVis, tierForkParent, tierGoneRead, tierGoneSet};", ctx2);
const S = ctx2.S;
check("sync: a save from a device holding an OLD copy leaves visibility alone",
  S.tierCustomSendsVis("u1", {r: "u1", vis: "public"}), false);
check("sync: ...a visibility button pressed here is sent", S.tierCustomSendsVis("u1", {r: "u1", vd: 1}), true);
check("sync: ...as is a list's first save to this account", S.tierCustomSendsVis("u1", {vis: "private"}), true);
check("sync: ...or one last confirmed on another account", S.tierCustomSendsVis("u1", {r: "u2"}), true);
check("fork: a public parent is named", S.tierForkParent({kind: "remote", slug: "abc", row: {visibility: "public"}}), "abc");
check("fork: an unlisted parent is NOT (its slug is its secret)",
  S.tierForkParent({kind: "remote", slug: "abc", row: {visibility: "unlisted"}}), null);
check("fork: your own list names nothing", S.tierForkParent({kind: "own", slug: "abc"}), null);
S.tierGoneSet("s1", "u1"); S.tierGoneSet("s2", "u2");
check("deletes: marked per account", JSON.parse(JSON.stringify(S.tierGoneRead())), {s1: "u1", s2: "u2"});
S.tierGoneSet("s1", null);
check("deletes: a confirmed delete clears its mark", JSON.parse(JSON.stringify(S.tierGoneRead())), {s2: "u2"});
ls["packsink:tierlist:gone:v1"] = "{not json";
check("deletes: an unreadable mark store reads as empty", JSON.parse(JSON.stringify(S.tierGoneRead())), {});

const hookSrc = index.slice(index.indexOf("function useTierCustomStore(user){"), index.indexOf("function TierCardViewer("));
check("sync: a local visibility choice is flagged to send (a patch FROM the account is not)",
  /\("vis" in patch0 && !\("r" in patch0\)\) \? \{\.\.\.patch0, vd: 1\}/.test(hookSrc), true);
check("sync: the flag clears only when the value it carried has landed",
  /const landed = sent && e\.vd && sent\.vis === e\.vis;/.test(hookSrc), true);
check("sync: a newer local copy takes the ACCOUNT's visibility unless a change is pending",
  /\.\.\.\(mine\.vd \? \{\} : \{vis: r\.visibility\}\)/.test(hookSrc), true);
check("sync: the save only adds visibility when it should",
  /if\(tierCustomSendsVis\(uid, st\)\) row\.visibility = /.test(index), true);
check("deletes: remove marks the delete before asking the account",
  hookSrc.indexOf("tierGoneSet(slug, owner)") > 0
  && hookSrc.indexOf("tierGoneSet(slug, owner)") < hookSrc.indexOf("tierCustomDeleteRemote(uid, slug)"), true);
check("deletes: the sign-in merge finishes marked deletes instead of rebuilding them",
  /if\(gone\[r\.slug\] !== uid\) return true;\s*\n\s*tierCustomDeleteRemote\(uid, r\.slug\)/.test(hookSrc), true);
check("sync: a failed save is shown, not covered by the old tick", /sf: 1/.test(hookSrc) && /sf: 0/.test(hookSrc), true);
check("fork: both copy paths use tierForkParent", (index.match(/fork: tierForkParent\(source\)/g) || []).length, 2);
check("fork: no copy path names a remote parent directly", /fork: source\.kind === "remote" \? source\.slug/.test(index), false);
check("share: the short link waits for THIS list to be on the account",
  /const shortLink = \(own && onAccount && confirmed && vis !== "private"\)/.test(index), true);
if(fails){ console.log(`\n${fails} failure(s)`); process.exit(1); }
console.log("\nall passed");
