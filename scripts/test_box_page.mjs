// test_box_page.mjs — guards the invite-only /box page (Ink.Box companion app).
//
//     node scripts/test_box_page.mjs
//
// box.html is GENERATED in the Ink.Box repo (tools/packsink.py build) with this
// site's client constants inlined, so everything it depends on here can drift
// without anything erroring:
//
//   * It carries COPIES of SUPABASE_URL, SUPABASE_KEY and the deck codec key.
//     Rotate any of them in Index.html and /box keeps working against the old
//     value until it quietly doesn't (decks that won't decode, 401s).
//   * "Not for normal people" is several separate mechanisms: a noindex meta,
//     a robots Disallow, nothing linking to it, and the allow-list check
//     (is_inkbox_user, migration 177) before any UI is shown. Lose one quietly
//     and the page is either in Google or usable by anyone who signs in.
//   * A page shipping without a build_dist entry 404s in prod while working
//     perfectly in dev.
import { readFileSync } from "node:fs";

const here = (f) => readFileSync(new URL("../" + f, import.meta.url), "utf8");
const page = here("box.html");
const index = here("Index.html");
const robots = here("robots.txt");
const build = here("scripts/build_dist.mjs");
const sitemap = here("sitemap.xml");
const migration = here("supabase/177_inkbox.sql");

let failed = 0;
const ok = (name, cond, detail) => {
  if (!cond) failed++;
  console.log((cond ? "PASS  " : "FAIL  ") + name + (cond || !detail ? "" : "  " + detail));
};

// ── The duplicated constants ─────────────────────────────────────────
const cfg = JSON.parse((page.match(/window\.INKBOX_CONFIG = (\{[^\n]*?\});<\/script>/) || [])[1] || "{}");
const constOf = (name) => (index.match(new RegExp('^const ' + name + '\\s*=\\s*"([^"]+)"', "m")) || [])[1];
ok("the page is the hosted build", cfg.mode === "hosted", JSON.stringify(cfg.mode));
ok("its Supabase URL matches the app's", !!cfg.supabaseUrl && cfg.supabaseUrl === constOf("SUPABASE_URL"));
ok("its publishable key matches the app's", !!cfg.supabaseKey && cfg.supabaseKey === constOf("SUPABASE_KEY"));
ok("its deck codec key matches the app's", !!cfg.deckKey && cfg.deckKey === constOf("DECK_ENC_KEY_B64"));
ok("it never carries a service key", !/service_role|sb_secret_/.test(page));
ok("it loads the vendored supabase-js (shares the site's sign-in)", page.includes('<script src="/vendor/supabase.js"></script>'));

// ── Invite-only ───────────────────────────────────────────────────────
ok("it asks the database whether this account is allowed", page.includes('sbRpc("is_inkbox_user")'));
ok("…and that function exists in the migration", migration.includes("function public.is_inkbox_user()"));
ok("nothing is allowed by default on the hosted build", page.includes('allowed = CFG.mode !== "hosted"'));
ok("the gate runs before any tab is shown",
  page.indexOf("if (!allowed) {") > 0 && page.indexOf("if (!allowed) {") < page.indexOf("showTab(params.get"));
ok("the allow-list has no client access", /revoke all on public\.inkbox_testers from anon, authenticated/.test(migration));
ok("pairing checks the allow-list", /inkbox_pair_device[\s\S]*?is_inkbox_user\(\)/.test(migration));
ok("sending checks the allow-list", /inkbox_send_job[\s\S]*?is_inkbox_user\(\)/.test(migration));

// ── Unlisted ──────────────────────────────────────────────────────────
ok("noindex meta", /<meta name="robots" content="noindex">/.test(page));
ok("robots.txt disallows /box", /^Disallow: \/box$/m.test(robots) && /^Disallow: \/box\.html$/m.test(robots));
ok("not in the sitemap", !/packs\.ink\/box\b/.test(sitemap));
// The one way in from the app is the settings-menu item an allow-listed account sees (asked for
// 2026-11-08). Take that block out and nothing else may link to the page.
const LINKS_TO_BOX = /["'`(\/]box\.html|href=["'`$]{0,3}\/box\b|packs\.ink\/box\b|location\.href\s*=\s*["'`]\/box\b/;
const gated = index.match(/\$\{isInkboxUser && html`[\s\S]*?<\/button>`\}/g) || [];
ok("the app's one link to it is the owners' menu item", gated.length === 1 && LINKS_TO_BOX.test(gated[0]));
ok("…which only shows when is_inkbox_user() says yes",
  /sbClient\.rpc\("is_inkbox_user"\)[\s\S]{0,120}setIsInkboxUser\(!!data\)/.test(index)
  && /if\(!user\)\{ setIsInkboxUser\(false\); return; \}/.test(index));
ok("nothing else in the app links to it", !LINKS_TO_BOX.test(gated.reduce((s, g) => s.replace(g, ""), index)));
ok("build_dist publishes it", /^\s*"box\.html",$/m.test(build));

console.log(failed ? `\n${failed} FAILED` : "\nall box-page guards passed");
process.exit(failed ? 1 : 0);
