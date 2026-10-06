// test_theme_contrast.mjs — guards the two theme-token readability fixes.
//
//     node scripts/test_theme_contrast.mjs
//
// Measured across all seven themes on 2026-09-26, two systemic gaps were fixed
// at the TOKEN (see CLAUDE.md, "Text on an accent fill is --on-accent"):
//
//   1. Text on the accent fill was a literal #fff in ~75 rules — fine on the
//      light themes' dark gold, 1.6-2.3:1 on the dark themes' bright gold.
//      Every such rule now uses var(--on-accent). A new rule reaching for #fff
//      again brings the bug back on three themes, silently.
//   2. --text-muted sat at 2.8:1 on parchment (3.3-3.8:1 elsewhere). It is now
//      sized to clear 4.5:1 on each theme's own solid background.
//
// This reads styles.css itself and does the WCAG arithmetic, so retuning a
// token that drops below the line fails here rather than on someone's screen.
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8").replace(/\r\n/g, "\n");

let pass = 0, fail = 0;
const ok = (name, cond, extra = "") => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "\n        " + extra : "")); }
};

// ── theme blocks ────────────────────────────────────────────────────────────
const THEMES = {
  parchment: ':root, html[data-theme="parchment"] {',
  sunrise: 'html[data-theme="sunrise"] {',
  watercolor: 'html[data-theme="watercolor"] {',
  daydream: 'html[data-theme="daydream"] {',
  velvet: 'html[data-theme="velvet"], html[data-theme="dark"] {',
  aurora: 'html[data-theme="aurora"] {',
  black: 'html[data-theme="black"] {',
};
const DARK = new Set(["velvet", "aurora", "black"]);
const block = (head) => {
  const a = css.indexOf(head);
  if (a < 0) throw new Error("theme block not found: " + head);
  const b = css.indexOf("\n}", a);
  return css.slice(a, b);
};
const tok = (body, name) => {
  const m = new RegExp("\\n\\s*" + name.replace(/[-]/g, "\\-") + ":\\s*([^;]+);").exec(body);
  return m ? m[1].trim() : null;
};
const root = block(THEMES.parchment);
const get = (theme, name) => tok(block(THEMES[theme]), name) ?? tok(root, name);

// ── colour maths ────────────────────────────────────────────────────────────
const parse = (c) => {
  c = c.trim();
  let m = /^#([0-9a-f]{3})$/i.exec(c);
  if (m) return [...m[1]].map(h => parseInt(h + h, 16)).concat(1);
  m = /^#([0-9a-f]{6})$/i.exec(c);
  if (m) return [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16)).concat(1);
  m = /^rgba?\(([^)]+)\)$/i.exec(c);
  if (m) { const p = m[1].split(",").map(s => parseFloat(s)); return [p[0], p[1], p[2], p[3] ?? 1]; }
  if (c === "white") return [255, 255, 255, 1];
  throw new Error("can't parse colour: " + c);
};
const over = (fg, bg) => fg.slice(0, 3).map((v, i) => v * fg[3] + bg[i] * (1 - fg[3]));
const lum = ([r, g, b]) => {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const contrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

// ── 1. muted and dim text clear 4.5:1 on each theme's solid background ─────
console.log("== muted / dim text ==");
for (const t of Object.keys(THEMES)) {
  const bg = parse(get(t, "--bg-solid"));
  const muted = over(parse(get(t, "--text-muted")), bg);
  const dim = over(parse(get(t, "--text-dim")), bg);
  const cm = contrast(muted, bg), cd = contrast(dim, bg);
  ok(`${t}: --text-muted ${cm.toFixed(2)}:1 >= 4.5`, cm >= 4.5);
  ok(`${t}: --text-dim is at least as strong as muted`, cd >= cm, `dim ${cd.toFixed(2)} < muted ${cm.toFixed(2)}`);
}

// ── 2. text on the accent fill ──────────────────────────────────────────────
console.log("\n== --on-accent ==");
for (const t of Object.keys(THEMES)) {
  const accent = parse(get(t, "--accent"));
  const on = get(t, "--on-accent");
  ok(`${t}: --on-accent is defined`, !!on);
  if (!on) continue;
  const c = contrast(parse(on), accent);
  ok(`${t}: --on-accent on --accent ${c.toFixed(2)}:1 >= 4.5`, c >= 4.5);
}
ok("dark themes override --on-accent (white fails on their bright gold)",
  [...DARK].every(t => tok(block(THEMES[t]), "--on-accent")));

// ── 2b. gold TEXT on the light themes' surfaces ────────────────────────────
// The light gold (#8a6d1b) measured 4.43:1 on Parchment's own background and
// 3.6:1 on a hovered panel (axe, 2026-10-06): every gold link, active nav
// label and active chip was under the line. #775e17 (Sunrise and Daydream,
// whose panels are darker and purple-tinted: #715916) clears it on the darkest
// surface gold text is drawn on: a panel (--bg-surface) over a hovered row
// (--bg-surface-hover) over the page. The active chip is --btn-active-text on
// --btn-active-bg over the page.
console.log("\n== gold text (light themes) ==");
for (const t of Object.keys(THEMES).filter(t => !DARK.has(t))) {
  const solid = parse(get(t, "--bg-solid"));
  const accent = parse(get(t, "--accent"));
  for (const bgName of ["--bg-solid", "--bg-card", "--bg-modal"]) {
    const c = contrast(accent, over(parse(get(t, bgName)), solid));
    ok(`${t}: --accent on ${bgName} ${c.toFixed(2)}:1 >= 4.5`, c >= 4.5);
  }
  const deep = over(parse(get(t, "--bg-surface")), over(parse(get(t, "--bg-surface-hover")), solid));
  const cd = contrast(accent, deep);
  ok(`${t}: --accent on a hovered panel ${cd.toFixed(2)}:1 >= 4.5`, cd >= 4.5);
  const chip = over(parse(get(t, "--btn-active-bg")), solid);
  const cc = contrast(parse(get(t, "--btn-active-text")), chip);
  ok(`${t}: active chip text ${cc.toFixed(2)}:1 >= 4.5`, cc >= 4.5);
}

// ── 3. no accent-filled rule goes back to a literal white ──────────────────
console.log("\n== accent fills ==");
const BG = /background(?:-color)?\s*:\s*var\(--accent\)/;
const FG = /(?<![-\w])color\s*:\s*(#fff(?:fff)?|white)\b/i;
const offenders = [];
for (const m of css.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
  if (BG.test(m[2]) && FG.test(m[2])) offenders.push(m[1].trim().split("\n").pop().slice(0, 80));
}
ok("no rule pairs background:var(--accent) with a literal white text colour",
  offenders.length === 0, offenders.slice(0, 8).join(" | "));
// ...nor with a literal DARK one: right on the dark themes' bright gold, about
// 3:1 on the light themes' dark gold (13 rules + one inline style, 2026-10-06).
const DARKFG = /(?<![-\w])color\s*:\s*#(?:[0-2][0-9a-f]{5}|000)\b/i;
const darkOffenders = [];
for (const m of css.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
  if (/background(?:-color)?\s*:\s*var\(--accent\b/.test(m[2]) && DARKFG.test(m[2])) darkOffenders.push(m[1].trim().split("\n").pop().slice(0, 80));
}
ok("no rule pairs an accent fill with a literal dark text colour",
  darkOffenders.length === 0, darkOffenders.slice(0, 8).join(" | "));
ok("the treatment is in use (the sweep didn't just delete the rules)",
  (css.match(/color:var\(--on-accent\)/g) || []).length > 50);

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
