// test_i18n_coverage.mjs - no new on-screen English ships untranslated.
//
// 1. The scanner itself: planted samples it must catch, and samples it must
//    leave alone (a broken scanner fails by finding NOTHING, which reads as
//    "all translated").
// 2. The real Index.html against i18n/src/untranslated_baseline.json - see
//    scripts/i18n_audit.mjs for the rules and the way out.

import fs from "node:fs";
import { audit, appScript, lex, collect, counts, diff } from "./i18n_audit.mjs";

let fails = 0;
const check = (ok, msg) => { if(!ok) { fails++; console.log("FAIL " + msg); } };
const found = (src) => audit(src).map(f => f.v);

// ---- 1. scanner self-test
const MUST = [
  ["text node", 'html`<div>Click here</div>`', "Click here"],
  ["text around an expression", 'html`<p>Showing ${n} cards</p>`', "Showing"],
  ["visible attribute", 'html`<button title="Copy link">x</button>`', "Copy link"],
  ["aria-label", 'html`<a aria-label="Open the menu"/>`', "Open the menu"],
  ["placeholder expr", 'html`<input placeholder=${"Search cards"}/>`', "Search cards"],
  ["ternary in a child slot", 'html`<b>${open ? "Hide all" : "Show all"}</b>`', "Show all"],
  ["concatenation in a title", 'html`<a title=${"Open " + name}/>`', "Open"],
  ["grouped ternary", 'html`<i>${(x ? "Yes please" : "No thanks")}</i>`', "No thanks"],
  ["nested template in a map", 'html`<ul>${xs.map(x => html`<li>Each one</li>`)}</ul>`', "Each one"],
  ["component prop", 'html`<${Banner} label="Chase Movers"/>`', "Chase Movers"],
  ["toast", 'flashToast("Link copied")', "Link copied"],
  ["toast template", 'flashToast(`Saved ${n} cards`)', "Saved {} cards"],
  ["data field", 'const KINDS = [{key: "set", label: "Sets"}];', "Sets"],
  ["label map", 'const BANNER_LABELS = {chase: "Chase Movers"};', "Chase Movers"],
  ["preset tuple", 'const SCREEN_PRESETS = [["all", "All cards", "Every card we track"]];', "Every card we track"],
  ["news bullets", 'const A = [{items: ["Fri: 8 rounds Swiss"]}];', "Fri: 8 rounds Swiss"],
  ["after a regex", 'const r = /a\\/b`/; html`<p>Still found</p>`', "Still found"],
  ["after a comment with a backtick", '// a ` stray\nhtml`<p>Also found</p>`', "Also found"],
];
for(const [what, src, want] of MUST) check(found(src).includes(want), `scanner must catch (${what}): ${src}`);

const MUST_NOT = [
  ["_t() wrapped", 'html`<div>${_t("Click here")}</div>`'],
  ["_term() wrapped", 'html`<div>${_term("ink", "Amber")}</div>`'],
  ["_t() in an attribute", 'html`<a title=${_t("Copy link")}/>`'],
  ["class names", 'html`<div class="home-news-tile">${x}</div>`'],
  ["comparison", 'html`<div>${mode === "graded" ? n : m}</div>`'],
  ["call argument", 'html`<div>${uiIcon("news", 13)}</div>`'],
  ["index", 'html`<div>${labels["Amber"]}</div>`'],
  ["object key / arrow body", 'html`<div style=${{display: "block"}}/>`'],
  ["symbols only", 'html`<span>→ · ✓</span>`'],
  ["a url", 'html`<a title="https://packs.ink/x"/>`'],
  ["an html comment", 'html`<div><!-- not text --></div>`'],
  ["toast via _t", 'flashToast(_t("Link copied"))'],
];
for(const [what, src] of MUST_NOT) check(found(src).length === 0, `scanner must ignore (${what}): ${src} -> ${JSON.stringify(found(src))}`);

// Lexer stays in sync over the real file: every html` in the app script is
// walked as a template, and the lexer reaches the end of the script.
{
  const sc = appScript(fs.readFileSync(new URL("../Index.html", import.meta.url), "utf8"));
  let n = 0;
  const walk = (toks) => { for(const t of toks) { if(t.t === "html") { n++; for(const s of t.v.slots) walk(s.tokens); } else if(t.t === "tpl") t.v.exprs.forEach(walk); } };
  const r = lex(sc.body, 0, false); walk(r.tokens);
  const src = (sc.body.match(/\bhtml`/g) || []).length;
  check(r.end === sc.body.length, `lexer reached ${r.end} of ${sc.body.length} chars`);
  check(n === src, `lexer walked ${n} html templates, the source has ${src} - the scanner has fallen out of sync`);
  check(n > 1000, `only ${n} templates found - wrong script picked?`);
}

// ---- 2. the real file against the baseline
{
  const base = JSON.parse(fs.readFileSync(new URL("../i18n/src/untranslated_baseline.json", import.meta.url), "utf8"));
  const {kept, lineOf} = collect();
  const {added, removed} = diff(counts(kept), base);
  for(const [k] of added) {
    const f = kept.filter(x => x.v === k).slice(-1)[0];
    check(false, `NEW untranslated string at Index.html:${lineOf(f.pos)} [${f.comp}] ${JSON.stringify(k)} - wrap it in _t() and add it to i18n/src/ui.json`);
  }
  if(removed.length) check(false, `${removed.length} baseline entr${removed.length === 1 ? "y is" : "ies are"} no longer in the code (translated?) - run: node scripts/i18n_audit.mjs --update`);
}

console.log(fails ? `\n${fails} failure(s)` : "test_i18n_coverage: OK");
process.exit(fails ? 1 : 0);
