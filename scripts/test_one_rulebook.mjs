// test_one_rulebook.mjs — every deck format tag comes from checkDeckLegality.
//
//     node scripts/test_one_rulebook.mjs
//
// The home Following feed tagged decks Core / Inf from a private copy of the
// legality rules, and the copy drifted (review, 2026-10-06): exact-name reprint
// lookup ("HeiHei" vs "Heihei" read Infinity), no copy limit (5 copies read
// Core), no Gather-the-Party ink exemption, and a promo could re-legalise a
// rotated card. A rule fixed in checkDeckLegality must reach every surface, so
// no surface may carry its own.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
let failed = 0;
const check = (name, ok) => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}`); };

const a = src.indexOf("const FollowingFeed = ");
const feed = a >= 0 ? src.slice(a, src.indexOf("\n};\n", a)) : "";
check("FollowingFeed is found", feed.length > 1000);
check("FollowingFeed tags formats with checkDeckLegality", /checkDeckLegality\(\{cards, coconut_card: d\.coconut_card\}, cardRowsById, setsByFamily\)\.format/.test(feed));
check("...with set families keyed by cardFamilyKey", /const key = cardFamilyKey\(name\);/.test(feed));
check("...and carries no private 60-card / 2-ink rule", !/totalQty < 60|inkSet\.size > 2/.test(feed));
check("...nor its own Core-set test", !/computeCoreSets\(\)/.test(feed));

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
