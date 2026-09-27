// Guard: the scanner takes the cards its shipped index predates from the catalog.
//
//   node scripts/test_scanner_extra.mjs
//
// scanner/text.json + index.json only know the cards that existed at the last
// build, so a set Lorcast indexed afterwards was invisible to the scanner until
// somebody rebuilt AND redeployed. The page now hands those cards over when the
// scanner opens (Index.html `scannerExtraRows` -> scanner.js `addCards`), and the
// review rows resolve ids through one lookup that includes them (`scannerMetaMap`).
//
// Every way this breaks is silent: a card the matcher cannot answer with reads as
// a scanner miss, and an id the review row cannot resolve is simply skipped. So
// this runs the REAL scanner.js over the SHIPPED index and the REAL page helpers
// extracted out of Index.html, offline.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadScanner } from "./scanner/replay_common.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..");
const HTML = fs.readFileSync(path.join(REPO, "Index.html"), "utf8");

let fails = 0;
const check = (cond, msg) => { console.log((cond ? "  ok    " : "  FAIL  ") + msg); if (!cond) fails++; };

// ---- the page helpers, extracted -------------------------------------------
const start = HTML.indexOf("// ── The scanner's catalog supplement");
const end = HTML.indexOf("// ── Card VERSIONS in a scan review row");
if (start < 0 || end < 0 || end < start) { console.error("could not find the supplement block in Index.html"); process.exit(1); }
const block = HTML.slice(start, end);
function pageHelpers(win, setCode, setRelease, today) {
  const f = new Function("window", "_setCodeById", "_setReleaseById", "COCONUT_SET_NAME", "localYmd",
    block + "\nreturn { scannerExtraRows, scannerMetaMap, SCAN_RARITY_CODE };");
  return f(win, setCode, setRelease, "Format Coconut", () => today);
}

const TODAY = "2026-09-26";
const SET_NEW = "set_test_future", SET_OLD = "set_test_old";
const setCode = new Map([[SET_NEW, "15"], [SET_OLD, "9"]]);
const setRelease = new Map([[SET_NEW, "2027-01-15"], [SET_OLD, "2025-05-30"]]);

// catalog rows shaped like buildRow's output
const row = (o) => Object.assign({ "Product Name": "", Rarity: "Common", Number: "", set_id: SET_OLD,
  card_type: "Character", classifications: ["Storyborn"], text: "", img_normal: null }, o);
const CATALOG = [
  row({ card_id: "crd_test_zorblax", "Product Name": "Zorblax - Test Pilot", Rarity: "Rare", Number: "77",
    classifications: ["Floodborn", "Hero"], text: "Evasive. When you play this character, draw a card.",
    img_normal: "/img-proxy/cards/15/077/abcdef.avif?1700000000" }),
  row({ card_id: "crd_test_zorblax", "Product Name": "Zorblax - Test Pilot", Rarity: "Rare", Number: "77" }),  // Foil twin row
  row({ card_id: "crd_test_future_lex", "Product Name": "Lexington - Test Future", Number: "5", set_id: SET_NEW }),
  row({ card_id: "crd_test_song", "Product Name": "Quizzical Quokka", Number: "12", card_type: "Action - Song",
    classifications: null }),
  row({ card_id: "crd_test_zorblax::variant::alt", "Product Name": "Zorblax - Test Pilot" }),
  row({ card_id: "coconut::zorblax", "Product Name": "Zorblax - Leader", Set: "Format Coconut" }),
  row({ card_id: "crd_test_coco", "Product Name": "Coco - Leader", Set: "Format Coconut" }),
  row({ card_id: "synthetic_no_prefix", "Product Name": "Nope - Nope" }),
];

// ---- scannerExtraRows ---------------------------------------------------------
{
  const H = pageHelpers({}, setCode, setRelease, TODAY);
  const out = H.scannerExtraRows(CATALOG, new Set());
  const ids = out.map((r) => r.id);
  check(ids.join(",") === "crd_test_zorblax,crd_test_future_lex,crd_test_song",
    `only real, unique, non-Coconut card ids are handed over (${ids.join(",")})`);
  const z = out[0];
  check(z.n === "Zorblax" && z.v === "Test Pilot", "Product Name splits into name + version at the first ' - '");
  check(out[2].n === "Quizzical Quokka" && out[2].v === null, "a card with no version keeps its whole name and a null version");
  check(z.s === "15" || z.s === "9", "the printed set code comes from the set map");
  check(z.s === "9", "…and it is the code of THIS card's set");
  check(z.cn === "77" && z.r === "R" && z.rarity === "Rare", "collector number and rarity code carry over");
  check(z.b === "zorblax test pilot character floodborn hero evasive when you play this character draw a card",
    `the body blob is build_text_index.py's shape (${z.b})`);
  check(z.art_key === "abcdef.avif", `art_key is the image's own filename (${z.art_key})`);
  check(out[2].art_key === "x:crd_test_song", "no image -> a per-id art key, never a shared empty one");
  check(!("d" in z) && out[1].d === "2027-01-15", "only a set that is not out yet carries its release date");
  const known = H.scannerExtraRows(CATALOG, new Set(["crd_test_zorblax"]));
  check(!known.some((r) => r.id === "crd_test_zorblax"), "an id the shipped index already holds is not handed over");
  const onDay = pageHelpers({}, setCode, setRelease, "2027-01-15").scannerExtraRows(CATALOG, new Set());
  check(!onDay.some((r) => r.d), "on the release day itself the date is no longer carried");
}

// ---- scanner.js addCards, both orders ---------------------------------------
const supplement = pageHelpers({}, setCode, setRelease, TODAY).scannerExtraRows(CATALOG, new Set());
// A row the shipped TEXT index holds but the colour index does not, plus a row
// whose id the colour index holds under a DIFFERENT name: in both, the shipped
// record must win. The builders now keep text.json a subset of index.json (the
// C1 promos whose Lorcast row only fills image_large used to be the live case),
// so the text-only card is SYNTHESISED into a fixture copy of the shipped files
// rather than looked for, or its three checks would quietly never run.
const shippedText = JSON.parse(fs.readFileSync(path.join(REPO, "scanner", "text.json"), "utf8"));
const shippedIdx = JSON.parse(fs.readFileSync(path.join(REPO, "scanner", "index.json"), "utf8")).cards;
const idxIds = new Set(shippedIdx.map((c) => c.id));
const textOnly = { id: "crd_test_textonly", n: "Pemberton", v: "Only In Text", b: "pemberton only in text character storyborn", s: "9", cn: "201", r: "R" };
check(!idxIds.has(textOnly.id) && !shippedText.some((c) => c.id === textOnly.id), "the text-only fixture id is in neither shipped file");
const FIXTURE = fs.mkdtempSync(path.join(os.tmpdir(), "scanner-extra-"));
fs.mkdirSync(path.join(FIXTURE, "scanner"));
for (const f of ["index.json", "color.bin", "dhash.bin"]) fs.copyFileSync(path.join(REPO, "scanner", f), path.join(FIXTURE, "scanner", f));
fs.writeFileSync(path.join(FIXTURE, "scanner", "text.json"), JSON.stringify(shippedText.concat([textOnly])));
process.on("exit", () => { try { fs.rmSync(FIXTURE, { recursive: true, force: true }); } catch (_e) {} });
const idxCard = shippedIdx[0];
const extraRows = supplement.concat(
  [{ id: textOnly.id, n: textOnly.n, v: textOnly.v, b: "garbage", s: textOnly.s, cn: textOnly.cn, r: textOnly.r }],
  [{ id: idxCard.id, n: "Not The Real Name", v: "Impostor", b: "impostor", s: "1", cn: "1", r: "C" }],
);

async function scenario(label, addFirst) {
  const CS = loadScanner(FIXTURE, path.join(REPO, "scanner.js"));
  await CS.load();
  const v0 = CS.metaVersion;
  let added;
  if (addFirst) { added = CS.addCards(extraRows); await CS.loadText({ asOf: TODAY }); }
  else { await CS.loadText({ asOf: TODAY }); added = CS.addCards(extraRows); }
  const t = CS.textState;
  check(added >= 3, `${label}: the new cards are taken (${added})`);
  check(CS.metaVersion > v0, `${label}: metaVersion moves, so a memoised lookup can tell it is stale`);
  const top = (lines) => { const r = CS.rankNames(lines, 6); return r.top[0] ? r.top[0].id : null; };
  check(top(["ZORBLAX", "Test Pilot"]) === "crd_test_zorblax", `${label}: the name matcher answers with a supplement card`);
  check(top(["QUIZZICAL QUOKKA"]) === "crd_test_song", `${label}: …including a card with no version`);
  const idr = CS.identify({ lines: ["ZORBLAX", "Test Pilot"], cnNum: null, cnSet: null, colourRanked: shippedIdx.slice(0, 5).map((c) => c.id) });
  check(idr && idr.top3 && idr.top3[0] === "crd_test_zorblax", `${label}: identify() answers with it too, colour ranking alongside`);
  check(CS.metaById("crd_test_zorblax") && CS.metaById("crd_test_zorblax").name === "Zorblax", `${label}: the review lookup resolves it`);
  check(top(["LEXINGTON"]) !== "crd_test_future_lex", `${label}: a supplement card from an unreleased set does not take a bare name read`);
  const lexOld = shippedText.find((c) => c.n === "Lexington" && !c.d);
  if (lexOld) check(top(["LEXINGTON"]) === lexOld.id, `${label}: …the released Lexington keeps it`);
  check(t.cards.filter((c) => c.id === textOnly.id).length === 1, `${label}: a card already in text.json is not duplicated`);
  check((t.cards.find((c) => c.id === textOnly.id) || {}).b === textOnly.b, `${label}: …and the shipped text row wins`);
  check(!!CS.metaById(textOnly.id), `${label}: …while the review lookup gains it (it had no colour row)`);
  check(CS.metaById(idxCard.id).name === idxCard.name, `${label}: the shipped colour-index record wins over a catalog copy`);
  check(t.cards.filter((c) => c.id === idxCard.id).length === 1, `${label}: …and text.json's too`);
  check(CS.allMeta().filter((c) => c.id === idxCard.id).length === 1, `${label}: allMeta holds each id once`);
  check(CS.addCards(extraRows) === 0, `${label}: handing the same rows over again is a no-op`);
  // the page's one lookup
  const H = pageHelpers({ CardScanner: CS }, setCode, setRelease, TODAY);
  const m1 = H.scannerMetaMap();
  check(m1.get("crd_test_zorblax") && m1.get(idxCard.id).name === idxCard.name, `${label}: scannerMetaMap resolves both kinds`);
  check(H.scannerMetaMap() === m1, `${label}: …and is reused while nothing changes`);
  CS.addCards([{ id: "crd_test_late", n: "Latecomer", v: null, b: "latecomer", s: "9", cn: "3", r: "C" }]);
  check(H.scannerMetaMap().has("crd_test_late"), `${label}: …and rebuilt when the scanner's list grows`);
  return CS;
}

const csA = await scenario("before loadText", true);
const csB = await scenario("after loadText", false);
// the two orders have to agree about everything the matcher answers
const probe = [["ZORBLAX"], ["QUIZZICAL QUOKKA"], ["LEXINGTON"], ["LEXINGTON", "Test Future"]];
check(probe.every((l) => (csA.rankNames(l, 3).top[0] || {}).id === (csB.rankNames(l, 3).top[0] || {}).id),
  "adding before or after text.json lands gives the same answers");

// ---- the page wiring -----------------------------------------------------------
{
  const mount = HTML.indexOf("try { await window.CardScanner.load(); }\n      catch(e){ setPhase(\"noindex\")");
  const hand = HTML.indexOf("CS.addCards(scannerExtraRows(raw", mount);
  const lt = HTML.indexOf("window.CardScanner.loadText().catch", mount);
  const cam = HTML.indexOf("navigator.mediaDevices.getUserMedia({", mount);
  check(mount > 0 && hand > mount && hand < lt && hand < cam,
    "the scanner modal hands the supplement over right after the index loads, before text + camera");
  check(!/const META = window\.CardScanner\.state\.cards/.test(HTML),
    "no review path builds its own id map off the colour index alone");
  check((HTML.match(/const byId = scannerMetaMap\(\);/g) || []).length === 3,
    "all three review paths resolve ids through scannerMetaMap");
  check(/select\("id,name,code,released_at"\)/.test(HTML) && /select:"id,name,code,released_at"/.test(HTML),
    "both catalog reads of `sets` carry the printed code");
  check(/_setCodeById = code;/.test(HTML), "setSetReleaseDates stamps the set-code map");
}

console.log(fails ? `\n${fails} failed` : "\nall passed");
process.exit(fails ? 1 : 0);
