// verify_amazon_asins.mjs — checks every curated Amazon ASIN still points at
// the product we think it does.
//
//     node scripts/verify_amazon_asins.mjs            # check all
//     node scripts/verify_amazon_asins.mjs --limit 10 # check the first 10
//
// RUN THIS FROM A MACHINE WITH ORDINARY INTERNET ACCESS. It is deliberately
// NOT wired into CI: the CI runner (and the agent sandbox the catalog was
// compiled in) cannot reach amazon.com, and Amazon rate-limits and
// bot-challenges anything that looks automated. A red CI job that everybody
// learns to ignore is worse than a script you run when you touch the catalog.
//
// What it is actually for: the ASINs in Index.html were read off public
// product listings, not verified against the live catalogue. A wrong one is
// not dangerous — it lands on some other real Ravensburger product — but it
// costs the click, and nothing else in the codebase can tell. This prints a
// per-ASIN verdict:
//
//   OK        the title contains "lorcana" and every token we expect
//   CHECK     the page loaded but the title is not what we expect
//   BLOCKED   Amazon served a captcha / 503 — rerun later, not a real failure
//   GONE      404 / 410, the listing is dead and the entry should be removed
//
// A CHECK is the interesting one. Read the printed title: if it is a different
// product, fix the ASIN in Index.html; if Ravensburger merely renamed the
// listing, widen or fix the expected tokens here.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const NL = String.fromCharCode(10);
const grab = (start, end) => {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing marker: " + start);
  const b = src.indexOf(end, a);
  return src.slice(a, b + end.length);
};
const mod = await import("data:text/javascript," + encodeURIComponent([
  grab("const AMAZON_ASIN_BY_SET = {", NL + "};"),
  grab("const AMAZON_SEALED_RULES = [", NL + "];"),
  grab("const AMAZON_PUZZLE_ASINS = {", NL + "};"),
  grab("const LORCANA_GEAR = [", NL + "];"),
  "export {AMAZON_ASIN_BY_SET, AMAZON_SEALED_RULES, AMAZON_PUZZLE_ASINS, LORCANA_GEAR};",
].join(NL)));

const PUZZLE_NAMES = {
  12001621: "amber", 12001622: "amethyst", 12001623: "emerald",
  12001624: "ruby", 12001625: "sapphire", 12001626: "steel",
};
// A display type maps to the words Amazon actually prints in its titles —
// they call a booster box a "Booster Pack Display", which is exactly the kind
// of mismatch that makes a naive title check useless.
const TYPE_WORDS = {
  "Booster Boxes": ["display"],
  "Illumineer's Troves": ["trove"],
  "Booster Packs": ["booster"],
};
const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

const targets = [];
for (const [type, bySet] of Object.entries(mod.AMAZON_ASIN_BY_SET))
  for (const [set, asin] of Object.entries(bySet))
    targets.push({asin, what: type + " / " + set,
      expect: [...norm(set).split(" ").filter((w) => w.length > 3), ...(TYPE_WORDS[type] || [])]});
for (const r of mod.AMAZON_SEALED_RULES)
  targets.push({asin: r.asin, what: "rule " + r.tokens.join(" + "),
    expect: r.tokens.flatMap((t) => t.split(" ")).filter((w) => w.length > 3)});
for (const [sku, asin] of Object.entries(mod.AMAZON_PUZZLE_ASINS))
  targets.push({asin, what: "puzzle " + sku, expect: ["puzzle", PUZZLE_NAMES[sku]].filter(Boolean)});
// A third-party entry is a search (`q`), not a product page: nothing to verify,
// and fetching /dp/undefined would report it as a dead listing.
for (const sec of mod.LORCANA_GEAR)
  for (const it of sec.items) if (it.asin)
    targets.push({asin: it.asin, what: "gear / " + it.name,
      expect: norm(it.name).split(" ").filter((w) => w.length > 4).slice(0, 2)});

const limitArg = process.argv.indexOf("--limit");
const list = limitArg > -1 ? targets.slice(0, Number(process.argv[limitArg + 1]) || 10) : targets;

const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const tally = {OK: 0, CHECK: 0, BLOCKED: 0, GONE: 0, ERROR: 0};

console.log("Verifying " + list.length + " ASINs against amazon.com …" + NL);
for (const t of list) {
  let verdict = "ERROR", detail = "";
  try {
    const res = await fetch("https://www.amazon.com/dp/" + t.asin, {
      headers: {"user-agent": UA, "accept-language": "en-US,en;q=0.9"},
      redirect: "follow",
    });
    if (res.status === 404 || res.status === 410) { verdict = "GONE"; detail = "HTTP " + res.status; }
    else if (!res.ok) { verdict = "BLOCKED"; detail = "HTTP " + res.status; }
    else {
      const html = await res.text();
      const title = norm((html.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [, ""])[1]);
      if (!title || /robot|captcha|sorry/.test(title)) { verdict = "BLOCKED"; detail = title.slice(0, 60); }
      else {
        const missing = t.expect.filter((w) => !title.includes(w));
        const lorcana = title.includes("lorcana");
        if (lorcana && missing.length === 0) verdict = "OK";
        else {
          verdict = "CHECK";
          detail = (lorcana ? "" : "not a Lorcana title; ") +
            (missing.length ? "missing [" + missing.join(", ") + "]; " : "") +
            title.slice(0, 90);
        }
      }
    }
  } catch (e) { detail = String(e && e.message || e); }
  tally[verdict]++;
  console.log(verdict.padEnd(8) + t.asin + "  " + t.what + (detail ? "  — " + detail : ""));
  await sleep(1500);  // Amazon challenges anything faster.
}

console.log(NL + Object.entries(tally).filter(([, n]) => n).map(([k, n]) => k + ": " + n).join("  "));
// Exit 0 even with CHECKs: this is a report to read, not a gate. Only a hard
// GONE is unambiguous enough to fail on.
process.exit(tally.GONE ? 1 : 0);
