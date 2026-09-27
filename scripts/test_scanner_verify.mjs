// Guard: ORB version verification decides the way the field measurements say.
//
//   node scripts/test_scanner_verify.mjs
//
// scanner-worker.js MEASURES (RANSAC inliers per candidate printing, how alike
// each candidate's art is to the winner's, a registered strip of the number line);
// the pure functions in Index.html's "ORB version verification" block DECIDE. The
// decision is where a silent regression would live: loosen the margin and the
// scanner confidently shows the wrong printing with a ✓; forget that identical
// art is a tie and an Epic "beats" its own base on noise; let the number match
// reach past the tied cards and a misread digit invents a card. So the real
// functions are extracted out of Index.html and pinned here, including against
// rec outputs recorded from real field crops (2026-09-26).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..");
const HTML = fs.readFileSync(path.join(REPO, "Index.html"), "utf8").replace(/\r\n/g, "\n");
const WORKER = fs.readFileSync(path.join(REPO, "scanner-worker.js"), "utf8").replace(/\r\n/g, "\n");
const OCRW = fs.readFileSync(path.join(REPO, "scanner-ocr-worker.js"), "utf8").replace(/\r\n/g, "\n");

let fails = 0;
const check = (cond, msg) => { console.log((cond ? "  ok    " : "  FAIL  ") + msg); if (!cond) fails++; };

const start = HTML.indexOf("// ── ORB version verification");
const end = HTML.indexOf("// ── Card VERSIONS in a scan review row");
if (start < 0 || end < 0 || end < start) { console.error("could not find the ORB verification block in Index.html"); process.exit(1); }
const block = HTML.slice(start, end);
const api = new Function("window", "scannerMetaMap", block +
  "\nreturn { SCAN_ORB, scanOrbVerdict, scanCnLead, scanCnSet, scanLev, scanCnPick, scannerFamilyOf, scanFamilyByText };")(
  { CardScanner: { state: { cards: [{ id: "a" }] }, metaVersion: 0 } },
  () => new Map([["a", { id: "a", name: "Mickey Mouse" }], ["b", { id: "b", name: "mickey mouse" }], ["c", { id: "c", name: "Minnie Mouse" }]]),
);
const { SCAN_ORB, scanOrbVerdict, scanCnLead, scanCnSet, scanLev, scanCnPick, scannerFamilyOf, scanFamilyByText } = api;

// ---- the verdict ------------------------------------------------------------
check(SCAN_ORB.MIN_INLIERS === 20 && SCAN_ORB.MARGIN === 1.6 && SCAN_ORB.TWIN_NCC === 0.97,
  "the field-measured bar: >= 20 inliers, >= 1.6x the runner-up, twins above 0.97 art likeness");
{
  const v = scanOrbVerdict({ a: 120, b: 40, c: 10 }, { b: 0.4, c: 0.3 });
  check(v.win === "a" && v.confident && v.second === 40, "a clear winner is confident");
  check(!scanOrbVerdict({ a: 60, b: 45 }, { b: 0.5 }).confident, "1.33x the runner-up is NOT confident");
  check(!scanOrbVerdict({ a: 19, b: 0 }, {}).confident, "19 inliers is not enough geometry, however alone");
  check(scanOrbVerdict({ a: 20, b: 12 }, {}).confident, "exactly 20 inliers and 1.67x clears it");
  const tw = scanOrbVerdict({ a: 150, b: 148, c: 20 }, { b: 0.99, c: 0.2 });
  check(tw.confident && tw.twins.length === 1 && tw.twins[0] === "b" && tw.second === 20,
    "identical art is a TIE with the winner, not the runner-up it must beat (Epic vs its base)");
  check(!scanOrbVerdict({ a: 150, b: 148 }, { b: 0.5 }).confident, "two different arts matching equally is no verdict");
  check(scanOrbVerdict({}, {}) === null, "no candidates, no verdict");
}

// ---- reading the number line --------------------------------------------------
check(scanCnLead("198/204-EN-8") === "198" && scanCnSet("198/204-EN-8") === "8", "a clean line reads number 198, set 8");
check(scanCnLead("57/207EN·13") === "57" && scanCnSet("57/207EN·13") === "13", "a glued line still splits (57 / set 13)");
check(scanCnLead("19V/204-EN·12") === "19", "an unreadable glyph drops out rather than becoming a digit");
check(scanCnLead("198204EN8") === "198", "no slash read: the number is the LEADING run, not the last three digits");
check(scanCnLead("IO/204") === "10", "I and O are read as the digits they usually are");
check(scanCnSet("194/204-EN·120") === "12", "a trailing glyph after the set code does not lose the set");
check(scanCnSet("4/P1·EN") === null && scanCnSet("201/204·EN·P1") === "P1", "a promo set code reads after EN");
check(scanLev("191", "19") === 1 && scanLev("", "7") === 1 && scanLev("172", "712") === 2, "edit distance");

// ---- matching against the TIED cards only --------------------------------------
{
  const twins = [{ id: "base", cn: "82", s: "7" }, { id: "epic", cn: "213", s: "7" }];
  check((scanCnPick(["82/204-ENmbos", "82/204-EN.708", "82/204-EN.7"], twins) || {}).id === "base",
    "field crop 488: 82/204 picks the base, not its Epic (#213)");
  const reprint = [{ id: "set2", cn: "201", s: "2" }, { id: "set9", cn: "201", s: "9" }];
  check((scanCnPick(["201/204-EN2AEKACOS", "201/204-EN·2", "201/204-EN·2"], reprint) || {}).id === "set2",
    "field crop 512: the same number in two sets is settled by the set code");
  check((scanCnPick(["20/24Nec", "201/204.EN.9a", "201/204·EN.9"], reprint) || {}).id === "set9",
    "field crop 504: an offset that misreads the number abstains; the others agree on set 9");
  check(scanCnPick(["201/204", "201/204"], reprint) === null, "same number, set unread: no call");
  const fam = [{ id: "a", cn: "191", s: "12" }, { id: "b", cn: "23", s: "12" }, { id: "c", cn: "207", s: "12" }];
  check((scanCnPick(["181/204-EN-12"], [{ id: "a", cn: "191", s: "12" }, { id: "z", cn: "57", s: "12" }]) || {}).id === "a",
    "one misread digit (181 for 191) is accepted when every other card is two more edits away");
  check(scanCnPick(["19/204-EN-12"], [{ id: "a", cn: "191", s: "12" }, { id: "z", cn: "68", s: "12" }]) === null,
    "a 2-digit read one edit from 191 but only two from 68 is too close to call");
  check(scanCnPick(["19/204-EN-12"], fam) === null, "…but not when another card is only two edits away (19 vs 23)");
  check(scanCnPick(["7/204EN·12", "71204-EN-12"], [{ id: "x", cn: "172", s: "12" }, { id: "y", cn: "7", s: "3" }]) === null,
    "field crop 543: two readings that disagree (7 vs 712) abstain");
  check(scanCnPick(["", "", ""], twins) === null && scanCnPick(["国人#", "#"], twins) === null,
    "a blank or glare-garbage strip abstains");
  check((scanCnPick(["571207-EN-13"], [{ id: "p", cn: "57", s: "13" }, { id: "q", cn: "213", s: "13" }]) || {}).id === "p",
    "field crop 527: a slash read as 1 (571207) is one edit from 57, and 213 is far");
  check(scanCnPick(["82/204-EN.7"], [{ id: "base", cn: "82", s: "12" }]) === null,
    "an exact number whose set clearly disagrees is some other printing: no call");
  check((scanCnPick(["82/204-EN.708", "82/204-EN.7"], twins) || {}).id === "base",
    "…but a garbled set on one offset (EN.708) only abstains there; the clean one decides");
  check(scanCnPick(["82/204-EN.7"], [{ id: "base", cn: "81", s: "12" }]) === null,
    "one digit off AND the set disagrees: no call");
}

// ---- which of a big family reach the art check ------------------------------------
{
  const fam = { o8: { version: "V.8" }, o10: { version: "V.10" }, scan: { version: "Scanning for Threats" }, none: { version: null } };
  const metaOf = (id) => fam[id];
  const order = ["o8", "scan", "none", "o10"];
  check(scanFamilyByText(order, ["OMNIDROID", "V.10"], metaOf)[0] === "o10",
    "a big family is ordered by the version the read found (V.10 first), not by index order");
  check(scanFamilyByText(order, ["OMNIDROID", "SCANNING FOR THREAIS"], metaOf)[0] === "scan",
    "…and a garbled subtitle still ranks its printing first");
  check(scanFamilyByText(order, ["OMNIDROID"], metaOf).join(",") === order.join(","),
    "no version text read: the index order stands (ties are stable)");
  check(scanFamilyByText(order, [], metaOf).join(",") === order.join(","), "no lines at all: unchanged");
  check(scanFamilyByText(order, ["LOOKING FOR A DEAL V.8"], metaOf)[0] === "o8",
    "a line carrying name AND version still counts");
}
check(/scanFamilyByText\(scannerFamilyOf\(topM\.name\), lines,/.test(HTML)
  && /verifyIdentity\(\{ rectBlob, top, cands, idr, verUnsure, conf: curConf, lines: ocrLines \}\)/.test(HTML),
  "the snap path hands its OCR lines to the family ranking");

// ---- the family index -------------------------------------------------------------
check(scannerFamilyOf("MICKEY MOUSE").sort().join(",") === "a,b", "a character's family is case-folded (Lorcast spells names inconsistently)");
check(scannerFamilyOf("Nobody").length === 0, "an unknown name has no family");

// ---- the wiring ------------------------------------------------------------------
check(/const doVerify = async \(\) => \{[\s\S]{0,400}verifyIdentity\(/.test(HTML), "the snap tail verifies through verifyIdentity");
check(/window\.__scanBench = async \(canvas, opts\) => \{[\s\S]*?verifyIdentity\(/.test(HTML), "…and so does __scanBench, so the bench measures what ships");
check(/orbDecided = r\.settled \|\| !!\(r\.info && r\.info\.ok\)/.test(HTML) && /if\(!orbDecided && unsure/.test(HTML),
  "the old look runs only when ORB was not confident");
check(/doBand: false \}\);\n\s+ocrLines = o\.lines/.test(HTML), "the snap path's primary read skips the subtitle band");
check(/"max", NAME_DET_SIDE/.test(OCRW) && /var NAME_DET_SIDE = 544;/.test(OCRW), "the name read dets at max-side 544");
check(/else if \(d\.type === "rec"\) \{ handleRec\(d\); \}/.test(OCRW), "the OCR worker answers rec-only requests");
check(/msg\.type === "verify"/.test(WORKER) && /cv\.RANSAC, 6\.0/.test(WORKER) && /0\.8 \* b\.distance/.test(WORKER),
  "the worker's measurement is the audit's: knn ratio 0.8, RANSAC 6.0");
check(/const ORB_FEATURES = 1000;/.test(WORKER), "1000 ORB features (measured: ~same precision as 1500 at ~60% of the time)");
check(/post\("verify-ref", \{ ref: \{ id, bitmap: b \} \}, \[b\]\)/.test(HTML) && /post\("verify", \{ query: q, refs: \[\], cands/.test(HTML)
  && /msg\.type === "verify-ref"/.test(WORKER),
  "references go to the shared detector worker ONE per message, so the live loop is never frozen behind a cold family");

console.log(fails ? `\n${fails} failed` : "\nall passed");
process.exit(fails ? 1 : 0);
