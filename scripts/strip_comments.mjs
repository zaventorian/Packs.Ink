// Strips comments out of the DEPLOY copy of Index.html and styles.css.
//
// Comments are ~28% of Index.html and ~30% of styles.css (measured 2026-09-30:
// 1.06 MB and 248 KB), and every visitor downloaded them. The source files keep
// every comment; only dist/ loses them, so the guards (which read the source)
// and the Discord bot's sitecode extraction are unaffected.
//
// Two rules make this safe:
//   1. A real tokenizer finds the comments (acorn for JS). A regex cannot: the
//      file is full of `//` inside URLs, regex literals and htm templates, and
//      `// proxied to /img-proxy/*` reads as a block-comment opener.
//   2. Line numbers are preserved — a comment is replaced by the newlines it
//      contained — so a Sentry stack trace from prod still points at the right
//      line of the source file.
//
// stripIndexHtml() re-tokenizes its own output and throws if the token stream
// changed; build_dist.mjs then ships the unstripped file instead.
import * as acorn from "./vendor/acorn.mjs";

const JS_OPTS = { ecmaVersion: "latest", sourceType: "script", allowReturnOutsideFunction: true };

const newlinesOf = (s) => s.replace(/[^\n]/g, "");

export function stripJsComments(src) {
  const comments = [];
  acorn.parse(src, { ...JS_OPTS, onComment: (block, text, start, end) => comments.push({ start, end }) });
  let out = "", pos = 0;
  for (const c of comments) {
    let s = c.start;
    const body = src.slice(c.start, c.end);
    let e = c.end;
    while (e < src.length && (src[e] === " " || src[e] === "\t")) e++;
    const toEol = e >= src.length || src[e] === "\n" || src[e] === "\r";
    // a comment that ends its line takes the blanks in front of it too
    if (toEol) { while (s > pos && (src[s - 1] === " " || src[s - 1] === "\t")) s--; }
    else e = c.end;
    out += src.slice(pos, s);
    const nl = newlinesOf(body);
    // a comment between two tokens on one line must still separate them
    out += nl || (toEol ? "" : " ");
    pos = e;
  }
  return out + src.slice(pos);
}

function tokenSig(src) {
  const sig = [];
  for (const t of acorn.tokenizer(src, JS_OPTS)) {
    const v = t.value;
    sig.push(t.type.label + "\u0001" + (v === undefined ? "" : (v && typeof v === "object") ? (v.pattern !== undefined ? "/" + v.pattern + "/" + v.flags : JSON.stringify(v)) : String(v)));
  }
  return sig;
}

export function sameJsTokens(a, b) {
  const x = tokenSig(a), y = tokenSig(b);
  if (x.length !== y.length) return false;
  for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return false;
  return true;
}

// The app is one big inline <script>; the small ones around it are left alone.
export function stripIndexHtml(html) {
  const re = /<script(\s[^>]*)?>([\s\S]*?)<\/script>/g;
  let m, main = null;
  while ((m = re.exec(html))) {
    const start = m.index + m[0].indexOf(">") + 1;
    if (!main || m[2].length > main.body.length) main = { start, body: m[2] };
  }
  if (!main || main.body.length < 100000) throw new Error("strip_comments: main script not found");
  const stripped = stripJsComments(main.body);
  if (!sameJsTokens(main.body, stripped)) throw new Error("strip_comments: token stream changed");
  if (newlinesOf(main.body).length !== newlinesOf(stripped).length) throw new Error("strip_comments: line count changed");
  return html.slice(0, main.start) + stripped + html.slice(main.start + main.body.length);
}

// CSS: comments are /* */ only, but must be skipped inside strings and url().
export function stripCssComments(css) {
  let out = "", i = 0;
  const n = css.length;
  while (i < n) {
    const ch = css[i];
    if (ch === '"' || ch === "'") {
      let j = i + 1;
      while (j < n && css[j] !== ch) { if (css[j] === "\\") j++; j++; }
      out += css.slice(i, j + 1); i = j + 1; continue;
    }
    if (ch === "/" && css[i + 1] === "*") {
      const end = css.indexOf("*/", i + 2);
      const e = end < 0 ? n : end + 2;
      let nl = newlinesOf(css.slice(i, e));
      let k = e;
      while (k < n && (css[k] === " " || css[k] === "\t")) k++;
      if (k >= n || css[k] === "\n" || css[k] === "\r") out = out.replace(/[ \t]+$/, "");
      else { k = e; if (!nl) nl = " "; }
      out += nl; i = k; continue;
    }
    if ((ch === "u" || ch === "U") && css.slice(i, i + 4).toLowerCase() === "url(") {
      const end = css.indexOf(")", i);
      const inner = css.slice(i + 4, end < 0 ? n : end).trim();
      if (inner[0] !== '"' && inner[0] !== "'" && end >= 0) { out += css.slice(i, end + 1); i = end + 1; continue; }
    }
    out += ch; i++;
  }
  return out;
}
