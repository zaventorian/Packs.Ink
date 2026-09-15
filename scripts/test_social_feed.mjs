// test_social_feed.mjs — guards the home page's community feed.
//
//     node scripts/test_social_feed.mjs
//
// Every failure this catches is SILENT in the browser:
//
//   * a panel key that normalizeHomeLayout drops (the feed just never appears)
//   * a read that trusts RLS instead of filtering `confirmed`, which would show
//     an admin a feed nobody else can see — the documented consequence of
//     migration 153's admin-read policy, and the exact trap the curated
//     calendar's read note describes
//   * a single-policy `is_graded_admin()` SELECT, which raises 42501 for anon
//     rather than returning false (migration 134) and hides the whole feed from
//     every signed-out visitor
//   * raw markup reaching the DOM, on a surface whose text is written by
//     strangers
//
// It reads the real code out of Index.html / the migration rather than
// duplicating it, so it cannot drift from what ships.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
const sql = readFileSync(new URL("../supabase/153_social_feed.sql", import.meta.url), "utf8");
const headers = readFileSync(new URL("../_headers", import.meta.url), "utf8");

let pass = 0, fail = 0;
const ok = (name, cond) => {
  if (cond) { pass++; console.log("  PASS  " + name); }
  else { fail++; console.log("  FAIL  " + name); }
};

function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("missing start marker: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("missing end marker: " + endMarker);
  return src.slice(a, b + endMarker.length);
}

console.log("\n── the panel is registered everywhere it has to be ──");

// HOME_PANELS is the list normalizeHomeLayout validates against; a key missing
// from any one of these four places makes the panel silently unreachable.
const panels = grab("const HOME_PANELS = [", "\n];");
ok("HOME_PANELS carries the `social` key", /\{key:"social"/.test(panels));
ok("it defaults to the left rail", /\{key:"social",\s*label:"[^"]+",\s*col:"left"\}/.test(panels));
ok("panelDest has an entry (so panelCta cannot read undefined)",
   /social:\s*null,/.test(src));
ok("panelNode renders it", /case "social":\s*return html`<\$\{SocialFeed\}/.test(src));
ok("the component exists", /const SocialFeed = \(\{/.test(src));

console.log("\n── the one-shot placement stamp ──");

// normalizeHomeLayout APPENDS an unknown key, so every browser that has ever
// loaded the site would get this at the FOOT of its column without a stamp.
ok("a stamp key is declared", /const HOME_LAYOUT_SOCIAL_KEY = "packsink:homeLayoutSocialRail";/.test(src));
ok("the stamp is read once and written back",
   /placeSocial = !localStorage\.getItem\(HOME_LAYOUT_SOCIAL_KEY\)/.test(src) &&
   /if\(placeSocial\) localStorage\.setItem\(HOME_LAYOUT_SOCIAL_KEY, "1"\)/.test(src));
ok("`placeSocial` is declared before use (no implicit global)",
   /let fixNews = false[^;]*placeSocial = false;/s.test(src));
// Stamped, never coerced: a standing rewrite in normalizeHomeLayout would snap
// the panel back every reload and make a deliberate move impossible.
const normalize = grab("const normalizeHomeLayout = (val) => {", "\n};");
ok("normalizeHomeLayout does NOT special-case it (stamped, not coerced)",
   !/social/.test(normalize));

console.log("\n── the read filters explicitly, and does not trust RLS ──");

const comp = grab("const SocialFeed = ({", "\n};");
ok("filters confirmed = true", /\.eq\("confirmed",\s*true\)/.test(comp));
ok("filters dead = false", /\.eq\("dead",\s*false\)/.test(comp));
ok("orders newest first", /\.order\("posted_at",\s*\{ascending:\s*false\}\)/.test(comp));
ok("caps the row count", /\.limit\(SOCIAL_FEED_LIMIT\)/.test(comp));
// The oEmbed `html` blob is never stored, so it must never be selected either.
ok("never selects an html column", !/\bhtml\b\s*[,"]/.test(
     (comp.match(/\.select\("([^"]+)"\)/) || ["", ""])[1]));
ok("degrades rather than throwing on a missing table",
   /socialFeedUnavailable/.test(src));

console.log("\n── no markup from strangers reaches the DOM ──");

// The whole file has never assigned raw markup into the DOM. This is the
// property that makes storing post text safe at all.
ok("Index.html contains no innerHTML at all", !/innerHTML/.test(src));
ok("...nor outerHTML / insertAdjacentHTML", !/outerHTML|insertAdjacentHTML/.test(src));
ok("...nor dangerouslySetInnerHTML", !/dangerouslySetInnerHTML/.test(src));

console.log("\n── migration 153 ──");

// Two SELECT policies, never one with an OR: migration 134 revoked EXECUTE on
// is_graded_admin() from anon, so a single policy raises 42501 for a
// signed-out reader instead of returning false.
const readPolicies = [...sql.matchAll(/create policy (\S+) on public\.social_posts\s+for select to ([^\n]+)\s+using \(([^;]+)\);/g)];
ok("social_posts has exactly two SELECT policies", readPolicies.length === 2);
const anonPolicy = readPolicies.find(m => /anon/.test(m[2]));
const adminPolicy = readPolicies.find(m => !/anon/.test(m[2]));
ok("the anon-visible policy never calls is_graded_admin()",
   !!anonPolicy && !/is_graded_admin/.test(anonPolicy[3]));
ok("the anon-visible policy gates on confirmed AND not dead",
   !!anonPolicy && /confirmed/.test(anonPolicy[3]) && /not dead/.test(anonPolicy[3]));
ok("the admin policy is scoped to authenticated only",
   !!adminPolicy && /authenticated/.test(adminPolicy[2]) && !/anon/.test(adminPolicy[2]));

// A new relation grants nothing implicitly — the migration-126 lesson, where a
// correct RLS policy still 403s because the table grant is missing.
ok("grants select to anon + authenticated",
   /grant select on public\.social_posts to anon, authenticated;/.test(sql));
ok("grants service_role (the ingest script's identity)",
   /grant select, insert, update, delete on public\.social_posts to service_role;/.test(sql));
ok("reloads the PostgREST schema cache", /NOTIFY pgrst, 'reload schema';/.test(sql));
ok("confirmed defaults false", /confirmed\s+boolean not null default false/.test(sql));
ok("auto_confirm defaults false (nothing publishes by accident)",
   /auto_confirm\s+boolean not null default false/.test(sql));
ok("(platform, source_id) is unique, so the hourly sweep is idempotent",
   /unique \(platform, source_id\)/.test(sql));
// The file is pasted by hand into the SQL editor; migration 142 failed twice
// with no error text and pure ASCII is what fixed it.
ok("the migration is pure ASCII (the 142 paste lesson)",
   // eslint-disable-next-line no-control-regex
   !/[^\x00-\x7F]/.test(sql));

console.log("\n── CSP ──");

const policies = headers.split("\n").filter(l => /^\s+Content-Security-Policy:/.test(l));
const full = policies.filter(l => /img-src/.test(l));
// ⚠ Count the copies rather than hardcoding a number. _headers carries one full
// policy per framed standalone page (/*, /swiss, /ticker as of PR #66) and
// test_csp_headers.mjs asserts they stay IDENTICAL apart from frame-ancestors —
// so a host added to some-but-not-all fails there with "one copy was edited
// without the other". Asserting `every` here catches the same defect from this
// side, and does not need editing when a fourth page appears.
ok("there is more than one full policy to keep in step", full.length >= 2);
ok("EVERY full policy allows the thumbnail host in img-src",
   full.every(l => /img-src[^;]*i\.ytimg\.com/.test(l)));
// The SW re-fetches images through fetch(), which is connect-src, so an
// img-src-only entry works on a first load and goes blank on every reload.
ok("EVERY full policy allows it in connect-src too",
   full.every(l => /connect-src[^;]*i\.ytimg\.com/.test(l)));
ok("script-src is NOT widened for it (no widgets.js)",
   full.every(l => !/script-src[^;]*(ytimg|platform\.x\.com|platform\.twitter\.com)/.test(l)));

console.log("\n── CSS ──");

ok("the panel has its own rules", /\.home-social-feed\{/.test(css));
ok("the title clamps rather than growing the rail",
   /\.home-social-title\{[^}]*-webkit-line-clamp/.test(css));
ok("the thumbnail reserves its box so a late image cannot reflow the row",
   /\.home-social-thumb\{[^}]*aspect-ratio/.test(css));

console.log(`\n${pass}/${pass + fail} checks passed.`);
process.exit(fail ? 1 : 0);
