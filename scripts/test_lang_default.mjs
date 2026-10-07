// test_lang_default.mjs — which language a visitor lands in, and the /ja/ links.
//
//     node scripts/test_lang_default.mjs
//
// Three things decide the site language before the first paint (Index.html's
// head boot): a ?hl= link, a STORED choice, and — since 2026-10-06 — the
// browser's own languages. Every way this goes wrong is silent: a visitor
// simply reads the wrong language, or a guess quietly overrides somebody's
// choice. So this runs the REAL boot script in a vm against stubbed
// navigator / localStorage / location, then checks:
//   1. the precedence (?hl= > stored > browser > English) and the walk down
//      navigator.languages (the first entry that is English or ours wins);
//   2. that a guess is NEVER stored (it is a default, not a choice);
//   3. that the account's saved language still beats a guess at sign-in
//      (the adoption test keys on the STORED value, not on SITE_LANG);
//   4. the /ja/ /de/ /fr/ /it/ /en/ (/jp/) shortcut in the worker AND the dev
//      server, case for case, including the protocol-relative trap;
//   5. that a deck's Copy link carries ?hl= only when the address bar does.
import fs from "node:fs";
import vm from "node:vm";
import { spawnSync } from "node:child_process";
import { langAliasTarget } from "../worker/lang_alias.mjs";
import worker from "../worker/index.js";

let failed = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) console.log(`        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`);
};

const html = fs.readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");

// ── 1–2. The boot script ────────────────────────────────────────────────────
const bootStart = html.indexOf("/* Pre-paint language boot.");
const bootEnd = html.indexOf("})();", bootStart);
check("found the language boot in Index.html's head", bootStart > 0 && bootEnd > bootStart && bootStart < 20000, true);
const boot = html.slice(bootStart, bootEnd + "})();".length);

const runBoot = ({ search = "", stored = null, storageThrows = false, languages, language } = {}) => {
  const written = [], attrs = {}, sets = [];
  const ctx = vm.createContext(Object.create(null));
  Object.assign(ctx, {
    URLSearchParams,
    String,
    location: { search },
    localStorage: {
      getItem: (k) => { if (storageThrows) throw new Error("blocked"); return k === "packsink:lang" ? stored : null; },
      setItem: (k, v) => { sets.push([k, v]); },
      removeItem: (k) => { sets.push([k, null]); },
    },
    navigator: { languages, language },
    document: {
      documentElement: { setAttribute: (k, v) => { attrs[k] = v; } },
      write: (s) => { written.push(s); },
    },
  });
  vm.runInContext(boot, ctx);
  const m = written.length ? /\/i18n\/(\w+)\.js/.exec(written[0]) : null;
  return { lang: m ? m[1] : "en", htmlLang: attrs.lang || null, sets };
};
const landsIn = (opts) => runBoot(opts).lang;

check("Japanese browser, nothing stored → Japanese", landsIn({ languages: ["ja-JP", "ja"] }), "ja");
check("English first, Japanese second → English", landsIn({ languages: ["en-US", "ja"] }), "en");
check("an unsupported first language is skipped → French", landsIn({ languages: ["es-ES", "fr-FR", "en"] }), "fr");
check("English ahead of a language we have stops the walk", landsIn({ languages: ["es-ES", "en-GB", "de-DE"] }), "en");
check("nothing we have → English", landsIn({ languages: ["zh-TW", "ko-KR"] }), "en");
check("case and region do not matter", landsIn({ languages: ["DE-at"] }), "de");
check("an underscore tag still reads", landsIn({ languages: ["it_IT"] }), "it");
check("no navigator.languages falls back to navigator.language", landsIn({ languages: [], language: "it-IT" }), "it");
check("no language information at all → English", landsIn({}), "en");
check("a stored English choice beats a Japanese browser", landsIn({ stored: "en", languages: ["ja-JP"] }), "en");
check("a stored German choice beats a Japanese browser", landsIn({ stored: "de", languages: ["ja-JP"] }), "de");
check("a junk stored value is ignored, so the browser decides", landsIn({ stored: "zz", languages: ["fr-FR"] }), "fr");
check("?hl= beats a stored choice", landsIn({ search: "?hl=it", stored: "de", languages: ["ja"] }), "it");
check("?hl=en beats a Japanese browser", landsIn({ search: "?hl=en", languages: ["ja"] }), "en");
check("an unknown ?hl= is ignored", landsIn({ search: "?hl=xx", languages: ["fr"] }), "fr");
check("blocked storage still lets the browser decide", landsIn({ storageThrows: true, languages: ["ja"] }), "ja");
check("<html lang> follows the guess", runBoot({ languages: ["ja-JP"] }).htmlLang, "ja");
check("a GUESS is never stored (it is a default, not a choice)", runBoot({ languages: ["ja-JP"] }).sets, []);
check("...nor is a ?hl= preview", runBoot({ search: "?hl=de" }).sets, []);

// ── 3. The account beats a guess ────────────────────────────────────────────
// A device that never CHOSE adopts the account's language at sign-in. A guess
// is not a choice, so the adoption test must read the STORED value: keyed on
// SITE_LANG it would treat a guessed Japanese page as a choice and keep it.
const hyd = html.indexOf("Site language follows the ACCOUNT");
const hydBody = html.slice(hyd, hyd + 1600);
check("account adoption reads the stored language", /localLang = localStorage\.getItem\(SITE_LANG_KEY\)/.test(hydBody), true);
check("...and adopts only when nothing is stored", hydBody.includes("if(!localLang && !hlPreview && metaLang && metaLang !== SITE_LANG){ setSiteLanguage(metaLang); return; }"), true);
check("...and only a STORED language is published to the account", hydBody.includes("if(localLang && localLang !== meta.siteLang){"), true);

// ── 4. /ja/ shortcuts: worker and dev server agree ──────────────────────────
const ALIAS_CASES = [
  ["/ja", "", "/?hl=ja"],
  ["/ja/", "", "/?hl=ja"],
  ["/ja/decks", "deck=8e6afb21&token=_1Bw9", "/decks?deck=8e6afb21&token=_1Bw9&hl=ja"],
  ["/jp/decks", "deck=1", "/decks?deck=1&hl=ja"],
  ["/JP/screener", "", "/screener?hl=ja"],
  ["/de/cards", "card=x", "/cards?card=x&hl=de"],
  ["/fr", "", "/?hl=fr"],
  ["/it/calendar", "cv=map", "/calendar?cv=map&hl=it"],
  ["/en/decks", "hl=ja&s=discover", "/decks?s=discover&hl=en"],
  // The ?v= and ?g= codecs use ~ ; : , — they must survive byte for byte.
  ["/ja/screener", "v=p0:5;w:1~x,y", "/screener?v=p0:5;w:1~x,y&hl=ja"],
  ["/ja/history", "g=c~123~N,s~9", "/history?g=c~123~N,s~9&hl=ja"],
  // A doubled slash must not turn into a protocol-relative URL off-site.
  ["/ja//evil.example", "", "/evil.example?hl=ja"],
  ["/ja///evil.example/x", "", "/evil.example/x?hl=ja"],
  ["/jam", "", null],
  ["/japan", "", null],
  ["/i18n/ja.js", "", null],
  ["/decks", "deck=1", null],
  ["/", "", null],
  ["/zz/x", "", null],
  ["/es/decks", "", null],
];
for (const [path, query, want] of ALIAS_CASES) {
  const got = langAliasTarget(new URL("https://packs.ink" + path + (query ? "?" + query : "")));
  check(`worker ${path}${query ? "?" + query : ""}`, got, want === null ? null : "https://packs.ink" + want);
}
// A backslash is a slash to a browser; the URL parser folds it the same way.
check("worker /ja/\\evil.example stays on packs.ink",
  langAliasTarget(new URL("https://packs.ink/ja/\\evil.example")), "https://packs.ink/evil.example?hl=ja");

const py = (() => {
  for (const exe of ["python", "python3"]) {
    const code = "import json,sys; sys.path.insert(0,'scripts'); import dev_server as d; "
      + "cases=json.load(sys.stdin); print(json.dumps([d.lang_alias_target(p,q) for p,q,_ in cases]))";
    const r = spawnSync(exe, ["-c", code], { input: JSON.stringify(ALIAS_CASES), encoding: "utf8",
      cwd: new URL("..", import.meta.url) });
    if (r.status === 0) return JSON.parse(r.stdout);
  }
  return null;
})();
check("dev server's alias could be run", Array.isArray(py), true);
if (py) ALIAS_CASES.forEach(([path, query, want], i) => check(`dev server ${path}${query ? "?" + query : ""}`, py[i], want));

// The worker actually answers with the redirect, before the asset fall-through.
const assets = { fetch: async () => new Response("shell", { status: 404 }) };
const r1 = await worker.fetch(new Request("https://packs.ink/ja/decks?deck=1&token=t"), { ASSETS: assets });
check("worker answers /ja/decks with a 302", r1.status, 302);
check("...to the same page in Japanese", r1.headers.get("Location"), "https://packs.ink/decks?deck=1&token=t&hl=ja");
const r2 = await worker.fetch(new Request("https://packs.ink/decks?deck=1"), {
  ASSETS: { fetch: async (req) => new Response("shell", { status: new URL(req.url).pathname === "/" ? 200 : 404 }) },
});
check("an ordinary route still gets the shell", [r2.status, await r2.text()], [200, "shell"]);

// ── 5. Deck Copy links carry ?hl= only when the address bar does ────────────
const wl = html.indexOf("const withLinkLang = ");
const wlEnd = html.indexOf("\n};\n", wl);
const wlSrc = html.slice(wl, wlEnd + 3);
const runWithLinkLang = (search) => {
  const ctx = vm.createContext({ URL, URLSearchParams, SITE_LANGS: [{ k: "en" }, { k: "ja" }, { k: "de" }, { k: "fr" }, { k: "it" }],
    window: { location: { search } } });
  vm.runInContext(wlSrc + "\nthis.out = withLinkLang(new URL('https://packs.ink/decks?deck=1&token=t')).toString();", ctx);
  return ctx.out;
};
check("found withLinkLang", wl > 0 && wlEnd > wl, true);
check("no ?hl= in the bar → language-neutral link", runWithLinkLang(""), "https://packs.ink/decks?deck=1&token=t");
check("?hl=ja in the bar → the link carries it", runWithLinkLang("?a=1&hl=ja"), "https://packs.ink/decks?deck=1&token=t&hl=ja");
check("an unknown ?hl= is not copied", runWithLinkLang("?hl=xx"), "https://packs.ink/decks?deck=1&token=t");
check("all three deck Copy links go through it", (html.match(/withLinkLang\((url|u)\)\.toString\(\)/g) || []).length, 3);

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
