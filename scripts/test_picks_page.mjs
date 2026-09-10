// test_picks_page.mjs — guards the unlisted /picks affiliate page.
//
//     node scripts/test_picks_page.mjs
//
// Extracts the real link builder and the real catalogue out of picks.html
// rather than restating them, so the test cannot drift from what ships.
//
// Everything here fails SILENTLY in production, which is why it is worth a
// test at all for a page this small:
//
//   * picks.html cannot reach Index.html's module, so AMAZON_TAG is
//     DUPLICATED. A tag that drifts — or one dropped in an edit — produces
//     links that work perfectly, land on the right products and earn nothing.
//     Nothing warns. This reads the tag back out of BOTH files and compares.
//   * The page is meant to be handed to people, which makes the FTC
//     disclosure more load-bearing here than anywhere else on the site, not
//     less. It is a required string, not copy to polish.
//   * "Unlisted" is three separate mechanisms — a noindex meta, a robots
//     Disallow, and nothing linking to it. Lose any one quietly and the page
//     is in Google. Two of the three are checkable from here.
//   * A page shipping without a build_dist entry 404s in prod while working
//     perfectly in dev.
import { readFileSync } from "node:fs";

const here = (f) => readFileSync(new URL("../" + f, import.meta.url), "utf8");
const page = here("picks.html");
const index = here("Index.html");
const robots = here("robots.txt");
const build = here("scripts/build_dist.mjs");
const NL = String.fromCharCode(10);

function grab(src, start, end) {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
}

const moduleSrc = [
  grab(page, "var AMAZON_TAG = ", ";"),
  grab(page, "function amazonSearchUrl(query, dept){", NL + "}"),
  grab(page, "var PICKS = [", NL + "];"),
  "export {AMAZON_TAG, amazonSearchUrl, PICKS};",
].join(NL);
const m = await import("data:text/javascript," + encodeURIComponent(moduleSrc));

let failed = 0;
const ok = (name, cond, detail) => {
  if (!cond) failed++;
  console.log((cond ? "PASS  " : "FAIL  ") + name + (cond || !detail ? "" : "  " + detail));
};

// ── The duplicated tag ──────────────────────────────────────────────────────
const appTag = (index.match(/const AMAZON_TAG = "([^"]+)"/) || [])[1];
ok("Index.html still declares a tag", !!appTag, "none found");
ok("the page's tag matches the app's", m.AMAZON_TAG === appTag,
  "page " + JSON.stringify(m.AMAZON_TAG) + " vs app " + JSON.stringify(appTag));

// ── The link builder ────────────────────────────────────────────────────────
const u = m.amazonSearchUrl("dragon shield matte", "toys-and-games");
ok("a search URL carries the tag", u.includes("tag=" + appTag), u);
ok("…points at Amazon's search", u.startsWith("https://www.amazon.com/s?k="), u);
ok("…scopes the department", u.includes("i=toys-and-games"), u);
ok("terms are URL-escaped", m.amazonSearchUrl("a b&c=d").includes("a%20b%26c%3Dd"),
  m.amazonSearchUrl("a b&c=d"));
ok("a missing department still yields a usable search",
  m.amazonSearchUrl("x").includes("i=toys-and-games"));

// ── The catalogue ───────────────────────────────────────────────────────────
const items = m.PICKS.flatMap((s) => s.items.map((it) => ({ ...it, dept: s.dept })));
ok("there are sections", m.PICKS.length >= 4, "only " + m.PICKS.length);
ok("every section has a title, a department and items",
  m.PICKS.every((s) => s.title && s.dept && s.items && s.items.length > 0));
ok("every item has a name and search terms",
  items.every((it) => it.name && it.q && it.q.trim().length > 3),
  JSON.stringify(items.filter((it) => !it.name || !it.q).slice(0, 3)));
// A typo'd department is the quiet one: Amazon serves the page anyway, just
// filtered to a category the product isn't in, so the link looks fine and
// returns nothing useful.
const DEPTS = new Set(["toys-and-games", "videogames", "electronics", "computers"]);
ok("every department is a real Amazon slug",
  m.PICKS.every((s) => DEPTS.has(s.dept)),
  m.PICKS.map((s) => s.dept).filter((d) => !DEPTS.has(d)).join(", "));
ok("every item builds a tagged link",
  items.every((it) => m.amazonSearchUrl(it.q, it.dept).includes("tag=" + appTag)));
const names = items.map((it) => it.name);
ok("no two rows share a name", new Set(names).size === names.length,
  names.filter((n, i) => names.indexOf(n) !== i).join(", "));

// ── The compliance boundary (same rule as the app's catalogue) ──────────────
// An Amazon price or image may only come from Amazon's own API, and we hold no
// Creators API keys — so either one appearing in this static file means it was
// hand-copied off a listing, the unlicensed use that actually costs accounts.
const blob = JSON.stringify(m.PICKS);
ok("the catalogue stores no prices", !/\$[0-9]/.test(blob));
ok("the catalogue stores no URLs", !/https?:\/\//i.test(blob));

// ── Disclosure and unlisting ────────────────────────────────────────────────
ok("the required Associate disclosure is present, verbatim",
  page.includes("As an Amazon Associate I earn from qualifying purchases"));
ok("every affiliate anchor is marked sponsored + nofollow",
  /rel = "noopener nofollow sponsored"/.test(page));
ok("the page is noindex", /<meta name="robots" content="noindex,nofollow">/.test(page));
ok("robots.txt disallows the pretty path", /^Disallow: \/picks$/m.test(robots));
ok("robots.txt disallows the .html path", /^Disallow: \/picks\.html$/m.test(robots));
ok("the page ships in dist", /"picks\.html"/.test(build));
// It says so on the page too: undiscoverable is not access-controlled, and a
// reader who thinks otherwise will treat the link as safer than it is.
ok("the page says unlisted is not private", /unlisted, not private/i.test(page));

console.log(NL + (failed ? failed + " FAILED" : "all passed"));
process.exit(failed ? 1 : 0);
