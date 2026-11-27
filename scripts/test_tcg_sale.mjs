// test_tcg_sale.mjs: guards the TEMPORARY TCGplayer Cyber Weekend 2026 notes.
//
//     node scripts/test_tcg_sale.mjs
//
// Window corrected 2026-11-27 to TCGplayer's promo terms: LIVE from 9am ET
// Fri 11/27 to 11pm ET Mon 11/30. Nothing before 11/27, "today" 00:00-09:00 ET 11/27.
// Extracts the real TCG_SALE + tcgSalePhase out of Index.html and feeds them
// explicit timestamps, never Date.now(), so the test keeps passing after the sale.
// Delete this file together with the TCG_SALE block.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
let fails = 0;
const ok = (cond, msg) => { if (!cond) { fails++; console.error("FAIL: " + msg); } };

function grab(start, end) {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
}

const code = grab("const TCG_SALE = {", "  : null;\n");
const { TCG_SALE, tcgSalePhase } = new Function(code + "\nreturn {TCG_SALE, tcgSalePhase};")();

// Every boundary, both sides. ET is EST (UTC-5) on all of these dates.
const ET = (mo, d, h) => Date.UTC(2026, mo - 1, d, h + 5);
const cases = [
  [ET(11, 24, 12), null, "11/24: nothing"],
  [ET(11, 27, 0) - 1, null, "1ms before 11/27 00:00 ET"],
  [ET(11, 27, 0), "today", "11/27 00:00 ET"],
  [ET(11, 27, 9) - 1, "today", "1ms before 9am ET 11/27"],
  [ET(11, 27, 9), "live", "11/27 9am ET"],
  [ET(11, 28, 12), "live", "11/28 noon ET"],
  [ET(11, 30, 23) - 1, "live", "1ms before 11/30 11pm ET"],
  [ET(11, 30, 23), null, "11/30 11pm ET"],
  [ET(12, 1, 12), null, "12/1 noon ET: over"],
  [ET(12, 25, 0), null, "Christmas"],
];
for (const [t, want, label] of cases) {
  const got = tcgSalePhase(t);
  ok(got === want, `${label}: expected ${want}, got ${got}`);
}
ok(TCG_SALE.startMs === Date.UTC(2026, 10, 27, 14), "start is 14:00 UTC on 11/27");
ok(TCG_SALE.endMs === Date.UTC(2026, 11, 1, 4), "end is 04:00 UTC on 12/1");

// The teaser must carry no link; the live link must be the affiliate hop,
// marked sponsored, with its disclosure label beside it.
const strip = grab("const TcgSaleStrip = () => {", "\n};\n");
const liveLink = strip.slice(strip.indexOf("${live && html`"));
ok(/\$\{live && html`<a /.test(strip), "the strip's only link is gated on live");
ok((strip.match(/<a /g) || []).length === 1, "the strip has exactly one link");
ok(/rel="noopener nofollow sponsored"/.test(liveLink), "live link is rel=sponsored");
ok(/_t\("affiliate link"\)/.test(liveLink), "live link carries the affiliate disclosure");
ok(/href=\$\{tcgSaleShopUrl\(\)\}/.test(liveLink), "live link goes through tcgSaleShopUrl");
ok(/const tcgSaleShopUrl = \(\) => TCG_AFFILIATE_BASE \+/.test(src), "tcgSaleShopUrl wraps TCG_AFFILIATE_BASE");
ok(/"live" : "soon"/.test(strip), "dismissal is stored per stage, so closing the teaser still shows LIVE");
const note = grab("const TcgSaleDeckNote = () => {", "\n};\n");
ok(!/<a /.test(note), "the deck note has no link of its own (it sits under the Buy the deck tile)");

// Both placements are mounted.
ok(src.includes("${!editing && html`<${TcgSaleStrip}/>`}"), "Home mounts the strip (hidden while editing)");
ok(src.includes("${massEntryUrl && html`<${TcgSaleDeckNote}/>`}"), "the deck page mounts the note under Buy the deck");

if (fails) { console.error(`\n${fails} failure(s)`); process.exit(1); }
console.log(`test_tcg_sale: ${cases.length} phase checks + markup checks OK`);
