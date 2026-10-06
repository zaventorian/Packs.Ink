// test_no_photo_credits.mjs — the site never credits where a photo came from.
//
//     node scripts/test_no_photo_credits.mjs
//
// Zaven, 2026-09-13: "PLEASE remove this from any mention on the site" (a pin
// photo source in the Help credits). The Great Hunny Rescue article (2026-10-05)
// still captioned its graphic with an Instagram account and the X user who
// shared it; removed 2026-10-06 on his say-so. privacy.html's takedown route is
// what covers sourcing. A card's ILLUSTRATOR is not a photo source and stays.
// Reads the news articles' visible text and every English UI string.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const ui = JSON.parse(readFileSync(new URL("../i18n/src/ui.json", import.meta.url), "utf8"));
let failed = 0;
const check = (name, ok, detail) => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}`); if (!ok && detail) console.log("        " + detail); };

// Phrasings a photo credit takes. Narrow on purpose: "on X" alone would match
// ordinary prose, so the platform words are required beside a sharing verb.
const CREDIT = /\b(on instagram|on x\b|on twitter|shared by|courtesy of|photo by|photo:|image:|via @|lorcanaplayer)/i;

const a = src.indexOf("const NEWS_ARTICLES = [");
const articles = a >= 0 ? src.slice(a, src.indexOf("\n];\n", a)) : "";
check("the news articles are found", articles.length > 500);
const texts = [...articles.matchAll(/(?:caption|alt|text):"((?:[^"\\]|\\.)*)"/g)].map(m => m[1]);
check("...and carry text to check", texts.length > 5);
const bad = texts.filter(t => CREDIT.test(t));
check("no news caption, alt or paragraph credits a photo source", bad.length === 0, bad.join(" | "));

const badUi = Object.keys(ui).filter(k => CREDIT.test(k));
check("no UI string credits a photo source", badUi.length === 0, badUi.slice(0, 5).join(" | "));

check("the pattern does catch the caption that was removed",
  CREDIT.test("Announcement graphic from illumineertales on Instagram, shared by @OhHeyItsBrando on X."));
check("...and leaves an illustrator credit alone", !CREDIT.test("Minnie Mouse - Amethyst Champion, LCP C2 #20, art by Max"));

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
