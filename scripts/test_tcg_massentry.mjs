// test_tcg_massentry.mjs — guards the TCGplayer mass-entry link splitter.
//
//     node scripts/test_tcg_massentry.mjs
//
// A mass-entry cart carries the whole list in its URL, and TCGplayer refuses
// anything past ~8 KB (measured 2026-09-25: 7,843 chars loads, 8,291 is a 414).
// A full-set "Buy bulk" of Reign of Jafar (202 lines, 623 copies) crashed with a
// raw server-error page. Nothing on our side errors when this regresses — the
// link just stops working on TCGplayer's end — so the splitter is pinned here.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const a = src.indexOf("const TCG_AFFILIATE_BASE");
const b = src.indexOf("\n};\n", src.indexOf("const tcgMassEntryParts")) + 4;
const { tcgMassEntryParts, TCG_MASSENTRY_MAX } = await import("data:text/javascript," +
  encodeURIComponent(src.slice(a, b) + "\nexport {tcgMassEntryParts, TCG_MASSENTRY_MAX};"));

let failed = 0;
const check = (name, ok) => { if (!ok) failed++; console.log((ok ? "PASS  " : "FAIL  ") + name); };
const destOf = (url) => decodeURIComponent(new URL(url).searchParams.get("u"));
const linesOf = (url) => new URL(destOf(url)).searchParams.get("c").split("||");

const names = ["Louie - One Cool Duck", "Ludwig Von Drake - All-Around Expert",
  "Charlotte La Bouff - Mardi Gras Princess", "Antonio's Jaguar - Faithful Companion"];
const big = Array.from({ length: 230 }, (_, i) => `${1 + (i % 5)} ${names[i % names.length]} ${i}`);
const parts = tcgMassEntryParts(big);
check("a 230-card list splits into several carts", parts.length > 1);
check("every cart's destination is under the cap", parts.every((p) => destOf(p.url).length <= TCG_MASSENTRY_MAX));
check("the cap sits well under TCGplayer's ~8 KB limit", TCG_MASSENTRY_MAX <= 7000);
check("no line is lost or reordered", JSON.stringify(parts.flatMap((p) => linesOf(p.url))) === JSON.stringify(big));
check("copies are counted per part", parts.reduce((n, p) => n + p.copies, 0) === big.reduce((n, l) => n + parseInt(l, 10), 0));
check("a small list is one cart", tcgMassEntryParts(big.slice(0, 20)).length === 1);
check("an empty list is no carts", tcgMassEntryParts([]).length === 0);
check("links go through the affiliate wrapper", parts.every((p) => p.url.startsWith("https://partner.tcgplayer.com/")));
check("no call site builds a mass-entry URL of its own",
  (src.match(/tcgplayer\.com\/massentry/g) || []).length === 1);

console.log(failed ? "\n" + failed + " FAILED" : "\nall passed");
process.exit(failed ? 1 : 0);
