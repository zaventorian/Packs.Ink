// Guard for the universal event-search box (Index.html, "Upcoming events near
// me" + the Elo Upcoming SCs distance box).
//
// Why this file exists: EVERY failure mode here is silent. A wrong truncation
// does not throw — it returns *a* location, just the wrong one, and the user
// sees a confident "3 events near Springfield" for a town they have never been
// to. A candidate list that quietly loses a country returns "not found" for a
// perfectly good postal code, which is indistinguishable from a typo. Neither
// shows up in a console.
//
// It extracts the REAL helpers out of Index.html rather than re-stating them,
// so the test cannot drift from what ships.
//
//   node scripts/test_event_search.mjs

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// Index.html is CRLF on disk; normalise so the multi-line anchors below match.
const SRC = fs.readFileSync(path.join(ROOT, "Index.html"), "utf8").replace(/\r\n/g, "\n");

// ── extract ─────────────────────────────────────────────────────────────────
const slice = (startsWith, endsWith, what) => {
  const a = SRC.indexOf(startsWith);
  if (a < 0) throw new Error(`could not find the start of ${what} in Index.html`);
  const b = SRC.indexOf(endsWith, a);
  if (b < 0) throw new Error(`could not find the end of ${what} in Index.html`);
  return SRC.slice(a, b + endsWith.length);
};

const source = [
  slice("const haversineMi = (la1, lo1, la2, lo2) => {",
        "return 2*R*Math.asin(Math.min(1, Math.sqrt(a)));\n};", "haversineMi"),
  slice("const searchNorm = (s) => (s||\"\")",
        ".replace(/['‘’`´]/g, \"\");", "searchNorm"),
  slice("const SC_GEO_COUNTRIES = [",
        "const scZipReady = (q) => String(q || \"\").trim().length >= 2;", "the resolver block"),
].join("\n\n");

// scLookupPlaces / scResolveOrigin are defined but never called here (they need
// Supabase); that stub only has to exist for the block to load.
//
// `fetch` is a different matter: scCountryOptions IS exercised, so it gets a
// tiny zippopotam driven by globalThis.__ZIPDB. Anything not in the fixture
// answers 404, which is exactly what the real API does for the candidates that
// never held the code — the whole point of probing.
const stub = `
const localStorage = { getItem: () => null, setItem: () => {} };
const navigator = { language: "en-US" };
const sbClient = { from: () => { throw new Error("no network in this test"); } };
const fetch = async (url) => {
  globalThis.__ZIPHITS = (globalThis.__ZIPHITS || 0) + 1;
  const m = /zippopotam\\.us\\/([a-z]{2})\\/(.+)$/.exec(String(url));
  const hit = m && (globalThis.__ZIPDB || {})[m[1] + "/" + decodeURIComponent(m[2])];
  if (!hit) return { ok: false };
  return { ok: true, json: async () => ({ places: [{ "place name": hit[0],
    "state abbreviation": hit[1], latitude: "41.9", longitude: "-87.6" }] }) };
};
`;

const api = new Function(`${stub}\n${source}\nreturn {
  SC_GEO_COUNTRIES, SC_POSTAL_FORMATS, scPostalShape, scPostalCandidates,
  scNormalizePostal, scRankPlaces, scZipReady, scDetectCountry, scTzCountry,
  scPlaceLabel, SC_PLACE_LABEL_MAX, SC_PLACE_MERGE_MI, haversineMi,
  scCountryOptions, scZippo };`)();

// ── harness ─────────────────────────────────────────────────────────────────
let pass = 0;
const fails = [];
const eq = (got, want, what) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; return; }
  fails.push(`${what}\n      expected ${w}\n      got      ${g}`);
};
const ok = (cond, what) => eq(!!cond, true, what);
const section = (name) => console.log(`\n${name}`);

// ── 1. the truncations, which are the whole reason this works ───────────────
// zippopotam wants a SHORTER key than the code people actually write for five
// of these. Getting one wrong is the difference between "Canada works" and
// "every Canadian postal code is not found", which is how this shipped.
section("1. scNormalizePostal — what actually goes in the URL");
for (const [typed, cc, want] of [
  // Canada: the 3-char Forward Sortation Area, however it was spaced or cased.
  ["M5V 3L9", "CA", "M5V"],
  ["M5V3L9",  "CA", "M5V"],
  ["m5v 3l9", "CA", "M5V"],
  ["M5V",     "CA", "M5V"],
  // UK: the outward code. The inward half is always the last 3 characters, so
  // this has to work for every outward length from 2 to 4.
  ["M1 1AE",   "GB", "M1"],
  ["CR2 6XH",  "GB", "CR2"],
  ["DN55 1PT", "GB", "DN55"],
  ["EC1A 1BB", "GB", "EC1A"],
  ["SW1A 1AA", "GB", "SW1A"],
  ["sw1a 1aa", "GB", "SW1A"],
  // Netherlands: the letters are not part of zippopotam's key.
  ["1012 AB", "NL", "1012"],
  ["1012AB",  "NL", "1012"],
  // Sweden prints a space and stores none.
  ["111 20", "SE", "11120"],
  ["11120",  "SE", "11120"],
  // Brazil needs the hyphen back; Poland and Portugal need theirs kept.
  ["01001-000", "BR", "01001-000"],
  ["01001000",  "BR", "01001-000"],
  ["00-001",    "PL", "00-001"],
  ["1000-001",  "PT", "1000-001"],
  // Everyone else is sent exactly what was typed.
  ["60614", "US", "60614"],
  ["10115", "DE", "10115"],
  ["75001", "FR", "75001"],
  ["2000",  "AU", "2000"],
]) eq(api.scNormalizePostal(typed, cc), want, `"${typed}" for ${cc}`);

// A code is only normalised for a country that format could belong to —
// otherwise a fall-through would send Canada's FSA to Germany and get a hit on
// something unrelated.
section("2. a code is never normalised for a country it cannot belong to");
for (const [typed, cc] of [["M5V 3L9", "US"], ["60614", "CA"], ["2000", "US"],
                           ["00-001", "PT"], ["1000-001", "PL"], ["60614", "GB"]])
  eq(api.scNormalizePostal(typed, cc), null, `"${typed}" is not a ${cc} code`);

// ── 3. candidates ───────────────────────────────────────────────────────────
section("3. scPostalCandidates — who is worth asking");
const cands = (q, home) => api.scPostalCandidates(q, home);
ok(cands("60614", "US").includes("US"), "a 5-digit code asks the US");
for (const cc of ["DE", "FR", "ES", "IT", "MX", "FI", "SE"])
  ok(cands("60614", "US").includes(cc), `a 5-digit code also asks ${cc}`);
ok(!cands("60614", "US").includes("CA"), "a 5-digit code does not ask Canada");
ok(!cands("60614", "US").includes("GB"), "a 5-digit code does not ask the UK");
for (const cc of ["AU", "NL", "BE", "CH", "AT", "DK", "NZ"])
  ok(cands("2000", "AU").includes(cc), `a 4-digit code asks ${cc}`);
// ⚠ A bare 4-digit code is NOT a US ZIP, and probing the US for one would spend
// the very first request (the US is the default inference) on a guaranteed miss.
ok(!cands("2000", "US").includes("US"), "a 4-digit code does not ask the US");
// ⚠ Portugal and Poland 404 on the bare digits — the hyphen is the key.
ok(!cands("1000", "AU").includes("PT"), "a bare 4-digit code does not ask Portugal");
ok(!cands("00001", "US").includes("PL"), "a bare 5-digit code does not ask Poland");
eq(cands("M5V 3L9", "US"), ["CA"], "a full Canadian code asks only Canada");
eq(cands("SW1A 1AA", "US"), ["GB"], "a full UK postcode asks only the UK");

section("4. the two 'no candidates' cases, which are NOT the same");
// Postal-shaped but unlookupable: zippopotam has no Irish data at all, so the
// resolver must fall straight through to the place lookup rather than spending
// twenty requests proving it.
eq(cands("D02 AF30", "IE"), [], "an Eircode is postal-shaped with nobody to ask");
ok(!api.SC_GEO_COUNTRIES.includes("IE"), "IE is not a probe candidate");
// ⚠ And the failure message has to branch on `cands !== null`, not on its
// length — with `.length` an Eircode falls into the "not a postal code" arm and
// the box tells someone who just typed a postal code to try a postal code.
ok(/throw new Error\(cands !== null/.test(SRC),
   "the 'no luck' message branches on shape, not on candidate count");
// Not postal-shaped at all -> straight to the place lookup. `null`, not `[]`.
for (const q of ["Naperville", "Chicago", "Dublin", "São Paulo", "Bangkok",
                 "Zürich", "Stoke-on-Trent", "New York"])
  eq(cands(q, "US"), null, `"${q}" is a place name, not a postal code`);

section("5. the inferred country goes first");
eq(cands("60614", "DE")[0], "DE", "a German browser asks Germany first");
eq(cands("60614", "US")[0], "US", "a US browser asks the US first");
eq(cands("2000", "NZ")[0], "NZ", "a NZ browser asks New Zealand first");
eq(cands("60614", "CA")[0], "US",
   "an inferred country the format rules out does not jump the queue");
// Below the inferred one, order is the market order of SC_GEO_COUNTRIES, so a
// fall-through tries the likeliest real answer next.
const rest = cands("60614", "DE").slice(1);
eq(rest, rest.slice().sort((a, b) =>
     api.SC_GEO_COUNTRIES.indexOf(a) - api.SC_GEO_COUNTRIES.indexOf(b)),
   "the rest keep market order");

section("6. every listed country is reachable by some format");
// A country in the probe list that no pattern names can never be asked — a dead
// entry that looks like coverage.
for (const cc of api.SC_GEO_COUNTRIES)
  ok(api.SC_POSTAL_FORMATS.some(f => f.cc.includes(cc)), `${cc} is reachable`);
// ...and nothing is named that is not in the list.
for (const f of api.SC_POSTAL_FORMATS)
  for (const cc of f.cc)
    ok(api.SC_GEO_COUNTRIES.includes(cc), `${cc} (in ${f.re}) is a listed country`);

// ── 7. place ranking ────────────────────────────────────────────────────────
section("7. scRankPlaces — one place per place");
const row = (city, state, country, latitude, longitude) =>
  ({ city, state, country, latitude, longitude });
// Real shapes out of lorcana_events: the same spot spelled several ways.
const dublins = [
  row("Dublin 8", "D", "IE", 53.34, -6.27),
  row("Dublin", "D", "IE", 53.35, -6.27),
  row("Dublin", "OH", "US", 40.10, -83.12),
  row("Dublin", "CA", "US", 37.70, -121.93),
];
const ranked = api.scRankPlaces(dublins, "dublin", "IE");
eq(ranked.length, 3, "Dublin 8 merges into Dublin; Ohio and California survive");
eq(ranked[0].city, "Dublin", "the exact name wins over 'Dublin 8' for the same spot");
eq(ranked[0].country, "IE", "and it keeps that spot's own country");
// ⚠ All three Dublins match the typed name equally well, so without the country
// tiebreak the winner is whatever order the rows happened to arrive in — which
// is how an Irish visitor first landed on Dublin, California.
eq(api.scRankPlaces(dublins, "dublin", "IE")[0].country, "IE",
   "an Irish browser gets the Irish Dublin");
eq(api.scRankPlaces(dublins, "dublin", "US")[0].country, "US",
   "a US browser gets a US Dublin");
// ...but an exact name still beats a home-country near-miss.
eq(api.scRankPlaces([row("Dublin 8", "D", "IE", 53.34, -6.27),
                     row("Dublin", "OH", "US", 40.10, -83.12)], "dublin", "IE")[0].state,
   "OH", "an exact match abroad beats an inexact one at home");
ok(ranked.some(p => p.state === "OH"), "Dublin OH is a different place");
ok(ranked.some(p => p.state === "CA"), "Dublin CA is a different place");
// ⚠ The merge is by DISTANCE, not by name: these three are one Bangkok.
const bangkoks = api.scRankPlaces([
  row("Bangkok, Thailand", "", "TH", 13.71, 100.60),
  row("Bangkok", "TH", "TH", 13.77, 100.54),
  row("Bangkok", "", "TH", 13.82, 100.67),
], "bangkok");
eq(bangkoks.length, 1, "three spellings of one Bangkok are one choice");
eq(bangkoks[0].city, "Bangkok", "and the plain spelling is the one shown");
// Rows with no coordinates cannot be an origin and must not occupy a slot.
eq(api.scRankPlaces([row("Nowhere", "", "US", null, null),
                     row("Somewhere", "", "US", 40, -80)], "s").length,
   1, "a row with no coordinates is dropped");
eq(api.scRankPlaces([], "x"), [], "no rows is no places, not a throw");
eq(api.scRankPlaces(null, "x"), [], "null rows is no places, not a throw");
// Two towns just outside the merge radius stay separate.
ok(api.scRankPlaces([row("A", "", "US", 40, -80),
                     row("B", "", "US", 40.5, -80)], "a").length === 2,
   "genuinely separate towns are not merged");

section("8. scPlaceLabel — names short enough to print");
// ⚠ These are REAL answers from the two sources, not invented ones. zippopotam
// names a Canadian FSA by listing its neighbourhoods, which wrapped the results
// heading onto three lines the first time a Canadian postal code worked.
eq(api.scPlaceLabel("Downtown Toronto (CN Tower / King and Spadina / Railway Lands / Harbourfront West / Bathurst Quay / South Niagara / YTZ)"),
   "Downtown Toronto", "a Canadian FSA keeps only the place");
eq(api.scPlaceLabel("Chicago"), "Chicago", "an ordinary name is untouched");
eq(api.scPlaceLabel("Bangkok, Thailand"), "Bangkok, Thailand", "a comma is not a cut point");
eq(api.scPlaceLabel("Paris 01 Louvre"), "Paris 01 Louvre", "nor is a number");
eq(api.scPlaceLabel("Lausanne 26"), "Lausanne 26", "nor a postal district");
eq(api.scPlaceLabel("København K"), "København K", "diacritics survive");
ok(api.scPlaceLabel("Amsterdam Binnenstad en Oostelijk Havengebied").length <= api.SC_PLACE_LABEL_MAX + 1,
   "a very long name is capped");
ok(!/\s…$/.test(api.scPlaceLabel("Amsterdam Binnenstad en Oostelijk Havengebied")),
   "and the ellipsis does not follow a stray space");
eq(api.scPlaceLabel(""), "", "empty in, empty out");
eq(api.scPlaceLabel(null), "", "null in, empty out");

section("9. scZipReady only stops a search firing on one keystroke");
eq(api.scZipReady("6"), false, "one character is not a search");
eq(api.scZipReady(""), false, "empty is not a search");
eq(api.scZipReady("  "), false, "whitespace is not a search");
eq(api.scZipReady("60614"), true, "a ZIP is");
eq(api.scZipReady("M5V 3L9"), true, "so is a Canadian code");
eq(api.scZipReady("Dublin"), true, "so is a town");

section("10. country inference");
// The index is built from Intl at runtime rather than hardcoded, so the only
// thing worth pinning is that it answers, and answers with a listed country.
const tz = api.scTzCountry();
ok(tz === null || api.SC_GEO_COUNTRIES.includes(tz),
   "the timezone index only ever names a country we can probe");
ok(api.SC_GEO_COUNTRIES.includes(api.scDetectCountry()),
   "detection always lands on a probeable country");

// ── 10. the render sites ────────────────────────────────────────────────────
// This is the part that makes the change stick: the point was to REMOVE the
// picker, and nothing else in the file would notice it coming back.
section("11. no render site asks for a country any more");
eq(SRC.includes("sc-country-select"), false, "the country <select> is gone");
// Mentions in a comment are fine and wanted — it is the definition and any live
// call that must be gone.
eq(/const\s+geocodeZip/.test(SRC), false, "the old US-shaped geocoder is gone");
eq(/await\s+geocodeZip\s*\(/.test(SRC), false, "and nothing still calls it");
eq((SRC.match(/class="sc-zip-input"/g) || []).length, 2,
   "both search boxes still exist");
eq((SRC.match(/placeholder="Postal code or town"/g) || []).length, 2,
   "and both take a postal code or a town");
// ⚠ The Elo box used to strip everything but digits, which silently ate the
// letters out of every non-US postal code as they were typed.
eq(/onInput=\$\{e=>setZip\(e\.target\.value\.replace\(\/\[\^0-9\]/.test(SRC), false,
   "neither box strips non-digits from what you type");

// ── 12. a search must never fire while you are still typing ────────────────
// ⚠ This is the regression that shipped with the box itself. Both search boxes
// carry an effect meaning "auto-run once on mount when a search is already
// saved", and both listed `zip` in their deps. That was only ever safe because
// scZipReady was `/^\d{5}$/` for US — true at a complete ZIP and nowhere before
// it. Loosening it to `length >= 2` so it could accept town names and non-US
// postal formats turned those effects into search-as-you-type: for anyone with
// no saved search, "60" on the way to "60625" ran a real geocode, and because
// nothing ordered the two requests its failure landed on top of the good one's
// results — `Nothing matching "60"` sitting over 94 correct events.
//
// Nothing throws, nothing logs, and the search that matters still works if you
// try again, so only a test can keep this from coming back.
section("12. the mount auto-run cannot re-fire as you type");

// The finder's effect, and the Elo box's.
const mountEffects = [
  ["finder", slice("  useEffect(() => {\n    if(!didSearch.current && scZipReady(zip))",
                   "}, []);", "the finder's mount auto-run")],
  ["Elo box", slice("  useEffect(() => { if(scZipReady(zip)) runGeo(zip); }, []);",
                    "}, []);", "the Elo box's mount geocode")],
];
for (const [who, src] of mountEffects) {
  ok(/\}, \[\]\);\s*$/.test(src.trim()),
     `${who}: the mount effect has EMPTY deps, so typing cannot re-fire it`);
  eq(/\}, \[[^\]]*\bzip\b/.test(src), false,
     `${who}: \`zip\` is not in its deps`);
}

// ⚠ Empty deps alone are not enough: two searches can still overlap (Search
// pressed twice, a radius chip tapped mid-search, a "did you mean" button), and
// the loser must not write its answer over the winner's. Every async path that
// commits state carries a sequence guard.
section("13. the loser of two overlapping searches writes nothing");
const guarded = [
  ["runSearch", slice("  const runSearch = useCallback(async (z, r, forceCc) => {",
                      "}, [mode, fetchNear]);", "runSearch")],
  ["useAltPlace", slice("  const useAltPlace = useCallback(async (p) => {",
                        "}, [zip, radius, origin, fetchNear]);", "useAltPlace")],
  ["searchAtRadius", slice("  const searchAtRadius = useCallback(async (r) => {",
                           "}, [zip, origin, country, runSearch, fetchNear]);", "searchAtRadius")],
  ["runGeo", slice("  const runGeo = useCallback(async (z) => {",
                   "  }, []);", "runGeo")],
];
for (const [who, src] of guarded) {
  ok(/\+\+(searchSeq|geoSeq)\.current/.test(src),
     `${who}: takes a sequence number before it awaits`);
  // Every branch that writes state has to be behind the check, the catch most
  // of all — a stale FAILURE overwriting a good result is the reported bug.
  ok(/catch\s*\([^)]*\)\s*\{\s*if\s*\(/.test(src),
     `${who}: its catch only writes when it is still the live search`);
}

// ⚠ Changing only the DISTANCE must not re-resolve the typed text: that throws
// away a place picked off the "Not Dublin?" row and silently moves you to the
// other Dublin, and spends a geocode round trip to do it.
eq((SRC.match(/searchAtRadius\(/g) || []).length, 3,
   "all three radius controls re-query from the origin already resolved");
eq(/onClick=\$\{\(\)=>pickRadius\(r\)\}/.test(SRC), true, "the radius chips still call pickRadius");

// ── 14. the country control is built from what RESOLVES, not what could ────
// The old correction offered the FORMAT's candidates: eight countries for any
// bare 5-digit code, whether or not the code meant anything in them. Measured
// over 40 real US ZIPs, 72% collide with at least one other country and 28%
// collide with NONE — and nothing on screen separated those two cases, so a
// correct answer still carried seven guesses under it.
//
// Every failure here is silent. Offer too much and the control is back to
// guessing; offer too little and someone whose code really is ambiguous has no
// way to say so.
section("14. scCountryOptions — only countries that really hold the code");

// 60640 is Chicago, and genuinely also a postal code in France, Mexico and
// Finland. It is NOT one in Germany, Spain, Italy or Sweden, which share the
// same five-digit shape and are therefore candidates.
globalThis.__ZIPDB = {
  "us/60640": ["Chicago", "IL"],
  "fr/60640": ["Muirancourt", "B6"],
  "mx/60640": ["Aviacion", "MIC"],
  "fi/60640": ["Isokoski", ""],
};
const FOUND_US = { country: "US", city: "Chicago", state: "IL" };
const CANDS = ["DE", "FR", "ES", "IT", "MX", "FI", "SE"];

globalThis.__ZIPHITS = 0;
const opts = await api.scCountryOptions("60640", CANDS, FOUND_US);
eq(opts.map((o) => o.cc), ["US", "FR", "MX", "FI"],
   "only the countries that answered are offered");
eq(opts.map((o) => o.city), ["Chicago", "Muirancourt", "Aviacion", "Isokoski"],
   "each option names the town it would land in");
// ⚠ Market order (SC_GEO_COUNTRIES), NOT the resolved country first. A <select>
// already marks which is active, and a list that reshuffles under the click
// that used it is the one thing a picker must not do.
// ⚠ Asserting "already sorted" against THIS fixture proves nothing: resolving
// US first happens to yield market order anyway. The sort only shows up when
// the resolved country is not the market-first one, on a code the cache has
// never seen.
globalThis.__ZIPDB = { "fi/12345": ["Tampere", ""], "us/12345": ["Schenectady", "NY"] };
const fiFirst = await api.scCountryOptions("12345", ["US"],
  { country: "FI", city: "Tampere", state: "" });
eq(fiFirst.map((o) => o.cc), ["US", "FI"],
   "market order wins over the order they were resolved in");
eq(fiFirst.map((o) => o.city), ["Schenectady", "Tampere"],
   "and each option keeps its own town through the sort");

// Switching country must reuse the cached set, not re-probe six countries to
// rebuild the identical list. Same code, different country resolved first.
const before = globalThis.__ZIPHITS;
const asFr = await api.scCountryOptions(
  "60640", ["DE", "US", "ES", "IT", "MX", "FI", "SE"],
  { country: "FR", city: "Muirancourt", state: "B6" });
eq(globalThis.__ZIPHITS, before, "switching country costs no new lookups");
eq(asFr.map((o) => o.cc), opts.map((o) => o.cc),
   "and the list is identical whichever country was resolved first");

// ⚠ 28% of real US ZIPs are unique to the US. One option means the caller
// renders nothing at all — no control, no question, no row.
globalThis.__ZIPDB = { "us/80202": ["Denver", "CO"] };
const lone = await api.scCountryOptions("80202", CANDS,
  { country: "US", city: "Denver", state: "CO" });
eq(lone.length, 1, "a code unique to one country yields a single option");
ok(/countryOpts\.length > 1 &&/.test(SRC),
   "and the render site is gated on there being more than one");

// A shape with no candidates at all (an Eircode) probes nothing.
globalThis.__ZIPDB = {};
eq((await api.scCountryOptions("D02 AF30", [], { country: "IE", city: "Dublin", state: "" })).length, 1,
   "no candidates means nothing to probe");
// ...and a resolver result with no country cannot produce a control.
eq((await api.scCountryOptions("60640", CANDS, null)).length, 0,
   "no origin means no options");

// ⚠ The probe must never gate the SEARCH. It is fired from runSearch without
// being awaited, so results are on screen before the countries are known.
ok(/scCountryOptions\([^)]*\)\s*\n?\s*\.then\(/.test(SRC),
   "the probe is fired and not awaited");
// ⚠ And it must only clear on a NEW code — clearing on every search makes the
// dropdown vanish for the second the event query takes, under the click that
// just used it.
ok(/probedZip\.current !== z/.test(SRC),
   "the control is only cleared when the typed code changed");

// The pre-search country picker stays gone: this control appears AFTER a
// search and only on real ambiguity, which is a different thing entirely.
eq(SRC.includes("sc-country-select"), false, "the old pre-search picker is still gone");

// ── report ──────────────────────────────────────────────────────────────────
console.log(`\n${"-".repeat(60)}`);
if (fails.length) {
  console.log(`FAIL  ${pass} passed, ${fails.length} failed\n`);
  for (const f of fails) console.log(`  x  ${f}`);
  process.exit(1);
}
console.log(`PASS  ${pass} checks`);
