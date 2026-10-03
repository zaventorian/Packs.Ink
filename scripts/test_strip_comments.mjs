// Guards scripts/strip_comments.mjs, which rewrites the deploy copy of
// Index.html and styles.css. Every way it can go wrong is silent in a build
// and total in a browser, so it is replayed over the real files.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { stripJsComments, stripCssComments, stripIndexHtml, sameJsTokens } from "./strip_comments.mjs";

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
let fails = 0;
const ok = (cond, msg) => { if (cond) console.log("PASS  " + msg); else { fails++; console.log("FAIL  " + msg); } };
const lines = (s) => s.split("\n").length;

// 1. the traps
const trap = [
  "const a = 'http://x/y'; // proxied to /img-proxy/*",
  "const re = /\\/\\/foo\\/\\*/g; /* gone */ const b = `// kept ${a /* gone */} /* kept */`;",
  "function f(){ return /* a",
  "  b */ 1 }",
  "const h = html`<a href=\"//cdn\">// text</a>`; const c = a/**/+b;",
].join("\n");
const t = stripJsComments(trap);
ok(!t.includes("proxied") && !t.includes("gone"), "real comments are removed");
ok(/`\/\/ kept \$\{a\s*\} \/\* kept \*\/`/.test(t), "comment-looking text inside a template survives");
ok(t.includes("'http://x/y'") && t.includes("/\\/\\/foo\\/\\*/g") && t.includes("// text</a>"), "URLs, regex literals and htm text survive");
ok(lines(t) === lines(trap), "line count preserved");
ok(sameJsTokens(trap, t), "token stream unchanged");
ok(t.includes("a +b"), "a comment between two tokens leaves a separator");
ok(!sameJsTokens("a+b", "a-b") && !sameJsTokens("a+b", "a+b+c"), "sameJsTokens can tell two programs apart");

// 2. the real Index.html
const html = readFileSync(join(repo, "Index.html"), "utf8");
let out = null;
try { out = stripIndexHtml(html); } catch (e) { console.log(String(e)); }
ok(!!out, "Index.html strips and re-tokenizes identically");
if (out) {
  ok(lines(out) === lines(html), "Index.html line count preserved (Sentry line numbers)");
  ok(out.length < html.length * 0.85, `Index.html shrinks meaningfully (${html.length} -> ${out.length})`);
  const head = (s) => s.slice(0, s.indexOf("</head>"));
  ok(head(out) === head(html), "the <head> is untouched (deploy verify reads styles.css?v= there)");
  ok(out.includes("/img-proxy") && out.includes("/tcg-img-proxy"), "proxy markers survive");
  ok(stripIndexHtml(out) === out, "stripping twice changes nothing");
}

// 3. CSS
const cssTrap = 'a{b:url(data:x/*y*/z);c:"/* s */"}/* gone */\n/* gone\n two */.d{e:1 /* gone */;f:2}';
const ct = stripCssComments(cssTrap);
ok(ct.includes("url(data:x/*y*/z)") && ct.includes('"/* s */"') && !ct.includes("gone"), "CSS: strings and url() survive, comments go");
ok(lines(ct) === lines(cssTrap), "CSS: line count preserved");
const css = readFileSync(join(repo, "styles.css"), "utf8");
const cs = stripCssComments(css);
ok(lines(cs) === lines(css), "styles.css line count preserved");
ok(cs.length < css.length * 0.85, `styles.css shrinks meaningfully (${css.length} -> ${cs.length})`);
// Independent check: with whitespace ignored, the result must equal a plain
// regex strip. (The regex is only wrong inside strings/url(), and if the two
// disagree that is worth a human look either way.)
const squash = (s) => s.replace(/\s+/g, "");
ok(squash(cs) === squash(css.replace(/\/\*[\s\S]*?\*\//g, " ")), "styles.css body matches an independent comment strip");
ok(stripCssComments(cs) === cs, "CSS: stripping twice changes nothing");

if (fails) { console.log(`\n${fails} failed`); process.exit(1); }
console.log("\nall passed");
