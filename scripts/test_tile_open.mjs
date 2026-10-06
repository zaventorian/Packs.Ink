// A clickable tile is never a button that contains buttons.
//
//     node scripts/test_tile_open.mjs [Index.html] [styles.css]
//
// A card tile, a movers tile, an EV row… opens on a click anywhere in it AND
// holds controls of its own (the select box, the magnifier, the camera, the
// TCGplayer link, the Sim chip). They used to be role="button" on the wrapper,
// which nests interactive controls inside a button: a screen reader reads the
// whole tile as one long name, some cannot reach the inner controls at all, and
// axe reports it as "nested-interactive" (serious) — 150 times on /cards alone
// (2026-10-06). The fix (tileOpen in Index.html) leaves the wrapper a plain
// clickable box and gives keyboard and screen-reader users a real <button> as
// the tile's first child, covering the tile, clipped to nothing, and ignoring
// the pointer, so mouse and touch behave exactly as before.
//
// Every way this regresses is silent — the tile still opens on a click — so:
//   1. no element carrying role="button" may contain a control (a generic scan
//      over every role="button" in the file, so a NEW tile can't repeat it);
//   2. each known tile keeps its tileOpen() as its FIRST child and stays out of
//      the tab order itself (tabIndex -1, kept so a click still focuses it);
//   3. tileOpen stays a handler-free button (its click must BUBBLE to the
//      wrapper, so the two can never disagree about what opening means);
//   4. styles.css keeps it covering-but-invisible, every wrapper positioned
//      (or inset:0 covers some ancestor instead), and a focus ring on the tile.
import { readFileSync } from "node:fs";

const htmlPath = process.argv[2] || new URL("../Index.html", import.meta.url);
const cssPath = process.argv[3] || new URL("../styles.css", import.meta.url);
const rawSrc = readFileSync(htmlPath, "utf8").replace(/\r\n/g, "\n");
const rawCss = readFileSync(cssPath, "utf8").replace(/\r\n/g, "\n");

let passed = 0, failed = 0;
const check = (ok, msg) => {
  if (ok) passed++;
  else { failed++; console.log("FAIL  " + msg); }
};

// Comments blanked (newlines kept, so a hit still reports its real line): the
// comments that explain this very fix say role="button" and <button>, and must
// not trip the scan. Only the three shapes comments take in this file are
// blanked — a `${/* … */""}` note inside a template, a `//` line and a `/* … */`
// block that START a line. A free-floating "/*" is not a comment opener here:
// `accept="image/*"` in the deck-image importer's template would otherwise
// swallow 800 lines, the quick-add row among them (the one-pass stripper in
// test_no_emoji.mjs does exactly that, which is harmless for its purpose and
// fatal for this one).
const blank = (m) => m.replace(/[^\n]/g, " ");
const src = rawSrc
  .replace(/\$\{(\/\*[\s\S]*?\*\/)/g, (m, c) => "${" + blank(c))
  .replace(/^[ \t]*\/\*[\s\S]*?\*\//gm, blank)
  .replace(/^[ \t]*\/\/[^\n]*/gm, blank)
  .replace(/<!--[\s\S]*?-->/g, blank);
const css = rawCss.replace(/\/\*[\s\S]*?\*\//g, blank);
const lineOf = (i) => src.slice(0, i).split("\n").length;

// Skip a `${ … }` expression starting at i (pointing at "$"); returns the index
// after its closing brace. Strings and nested template literals are skipped
// whole — an arrow function's `=>` inside an attribute must not read as the
// end of the tag.
function skipExpr(s, i) {
  let depth = 0;
  for (let j = i + 1; j < s.length; j++) {
    const c = s[j];
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) return j + 1; }
    else if (c === '"' || c === "'") { j = s.indexOf(c, j + 1); if (j < 0) return s.length; }
    else if (c === "`") { j = skipTemplate(s, j) - 1; }
  }
  return s.length;
}
function skipTemplate(s, i) {
  for (let j = i + 1; j < s.length; j++) {
    const c = s[j];
    if (c === "\\") { j++; continue; }
    if (c === "`") return j + 1;
    if (c === "$" && s[j + 1] === "{") j = skipExpr(s, j) - 1;
  }
  return s.length;
}
// The opening tag starting at i ("<div …"): {end, self} — end is just past ">".
function openTag(s, i) {
  for (let j = i + 1; j < s.length; j++) {
    const c = s[j];
    if (c === "$" && s[j + 1] === "{") { j = skipExpr(s, j) - 1; continue; }
    if (c === '"') { j = s.indexOf('"', j + 1); continue; }
    if (c === ">") return { end: j + 1, self: s[j - 1] === "/" };
  }
  return { end: s.length, self: true };
}
// The element whose opening tag starts at i: {tag, attrs, body}.
function element(s, i) {
  const tag = /^<([a-z][a-z0-9]*)/.exec(s.slice(i, i + 20))[1];
  const ot = openTag(s, i);
  const attrs = s.slice(i, ot.end);
  if (ot.self) return { tag, attrs, body: "" };
  const re = new RegExp("<" + tag + "(?=[\\s>/])|</" + tag + ">", "g");
  re.lastIndex = ot.end;
  let depth = 1, m;
  while ((m = re.exec(s))) {
    if (m[0][1] === "/") { if (--depth === 0) return { tag, attrs, body: s.slice(ot.end, m.index) }; }
    else {
      const inner = openTag(s, m.index);
      if (!inner.self) depth++;
      re.lastIndex = inner.end;
    }
  }
  return { tag, attrs, body: s.slice(ot.end) };
}

// Anything that renders a control. The helpers are the ones these tiles hold.
const CONTROL = /<button[\s>]|<a[\s>]|<input[\s>/]|<select[\s>]|<textarea[\s>]|role="button"|role=\$\{[^}]*"button"|\btileOpen\(|\bcheckboxEl\b|\bbuildVariantChevron\(|\bamazonPill\(|<\$\{(PriceBadge|CostDateInputs|AmazonBuyLink)\}/;

// 1. Generic: no role="button" element (literal, or role=${… "button" …})
//    contains a control.
{
  const re = /role="button"|role=\$\{[^}]*"button"/g;
  let m, n = 0;
  while ((m = re.exec(src))) {
    const start = src.lastIndexOf("<", m.index);
    if (start < 0 || !/^<[a-z]/.test(src.slice(start, start + 2))) continue;
    const el = element(src, start);
    if (!el.attrs.includes(m[0])) continue;   // the "<" belonged to something else
    n++;
    const hit = CONTROL.exec(el.body);
    check(!hit, `line ${lineOf(start)}: <${el.tag} role="button"> contains a control (${hit && hit[0]}) — give the tile a tileOpen() button instead`);
  }
  check(n >= 5, `the role="button" scan found ${n} elements — the scanner broke, not the code`);
}

// 2. The known tiles: tileOpen() first, no role, out of the tab order.
const TILES = [
  ["card tile",           'class=${"card-tile"+(isSelected'],
  ["movers tile",         '<div class="mover-tile"\n'],
  ["sealed movers tile",  '<div class="mover-tile mover-tile--sealed"'],
  ["EV row",              'class=${"ev-row"+(openSetHistory?" ev-row-clickable":"")}'],
  ["pins checklist row",  'class=${"cb-row" + (qty > 0'],
  ["playmat card",        'class=${"gc-card gc-card-clickable playmat-card"'],
  ["graded goal",         'class="gc-goal gc-goal-clickable"'],
  ["deck list row name",  '<span class="deck-row-name"'],
];
for (const [name, anchor] of TILES) {
  const at = src.indexOf(anchor);
  check(at >= 0, `${name}: anchor not found (${JSON.stringify(anchor)}) — renamed? update TILES`);
  if (at < 0) continue;
  check(src.indexOf(anchor, at + 1) < 0, `${name}: anchor is not unique`);
  const start = src.lastIndexOf("<", at);
  const el = element(src, start);
  check(!/\brole=/.test(el.attrs), `${name}: the wrapper carries a role again`);
  check(!/tabIndex=(\{0\}|"0"|\$\{0\}|\$\{[^}]*\?\s*0\s*:)/.test(el.attrs), `${name}: the wrapper is back in the tab order (tabIndex 0) — Tab would stop twice per tile`);
  check(/tabIndex=("-1"|\$\{-1\}|\$\{[^}]*\?\s*-1\s*:)/.test(el.attrs), `${name}: the wrapper lost tabIndex -1 — a click no longer focuses the tile as it did`);
  check(/onClick=/.test(el.attrs), `${name}: the wrapper has no onClick for tileOpen's click to bubble to`);
  const first = el.body.trimStart();
  check(first.startsWith("${") && /tileOpen\(/.test(first.slice(0, skipExpr(first, 0))),
    `${name}: tileOpen() is not the tile's FIRST child — Tab must reach it before the tile's own controls`);
}

// 3. tileOpen itself: a handler-free <button type="button"> named by aria-label.
{
  const m = /const tileOpen = \(label\) => html`([^`]*)`;/.exec(src);
  check(!!m, "tileOpen definition not found");
  if (m) {
    const t = m[1];
    check(/^<button type="button" class="tile-open" aria-label=\$\{label\}><\/button>$/.test(t.trim()),
      "tileOpen must stay an EMPTY handler-free <button type=\"button\" class=\"tile-open\" aria-label> — " +
      "its click bubbles to the tile's onClick, and text inside it would turn up in find-in-page");
  }
}

// 4. styles.css
const rules = [];
{
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(css))) rules.push({ sels: m[1].split(",").map((s) => s.trim().replace(/\s+/g, " ")), body: m[2].replace(/\s+/g, "") });
}
const ruleFor = (sel) => rules.filter((r) => r.sels.includes(sel));
{
  const t = ruleFor(".tile-open").map((r) => r.body).join(";");
  for (const decl of ["position:absolute", "inset:0", "pointer-events:none", "clip-path:inset(50%)", "border:0", "padding:0"]) {
    check(t.includes(decl), `.tile-open lost "${decl}"`);
  }
  check(!/opacity:0[;}]|display:none|visibility:hidden/.test(t), ".tile-open must stay in the accessibility tree (no display:none / visibility:hidden)");
  for (const cls of ["card-tile", "mover-tile", "ev-row-clickable", "cb-row", "gc-card", "gc-goal", "deck-row-name"]) {
    check(ruleFor("." + cls).some((r) => r.body.includes("position:relative")),
      `.${cls} is not positioned — its tileOpen would cover some ancestor instead of the tile`);
  }
  for (const cls of ["card-tile", "mover-tile", "ev-row-clickable", "cb-row", "gc-card-clickable", "gc-goal-clickable", "deck-row-name"]) {
    const r = ruleFor(`.${cls}:has(> .tile-open:focus-visible)`);
    check(r.some((x) => /outline:2px/.test(x.body)), `.${cls} has no focus ring for its tileOpen — the tile would focus invisibly`);
  }
}

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
