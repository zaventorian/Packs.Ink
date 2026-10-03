// i18n_audit.mjs - find on-screen English in Index.html that is not routed
// through _t() / _term(), and hold the line on it.
//
//   node scripts/i18n_audit.mjs                 # summary: untranslated strings per component
//   node scripts/i18n_audit.mjs --list [Comp]   # every finding (optionally one component)
//   node scripts/i18n_audit.mjs --check         # the guard: fail on anything NEW
//   node scripts/i18n_audit.mjs --update        # shrink the baseline to today (never grows it)
//   node scripts/i18n_audit.mjs --update --accept   # also record new findings (deliberate)
//
// Why it exists: `build_i18n.py --check` only knows about strings somebody
// already wrapped in _t(). Text that was never wrapped is invisible to it, and
// that is how a week of new features (news, the calendar page, the Screener's
// presets) shipped English-only with every guard green.
//
// What counts as on-screen English, inside html`` templates only:
//   * a text node with a run of 2+ letters             <div>Click here</div>
//   * a literal value of a visible attribute             title="Copy link"
//     (title / placeholder / aria-label / alt, plus the props our own
//     components render as text: label, emptyText, ...)
//   * a string literal sitting directly in a child or visible-attribute slot
//     ${open ? "Hide" : "Show"}, title=${"Open " + name}
//   * the first argument of flashToast("...")
// A string passed to ANY call (_t("x"), uiIcon("news"), cls("a")) is not
// counted, which is what makes _t() the way out.
//
// It does NOT see text that lives in data consts (EVENT_TILES, NEWS_ARTICLES,
// set names) - those need _t()/_term() at the render site, or a translated
// copy of the data. See docs/i18n.md.
//
// The baseline (i18n/src/untranslated_baseline.json) is a multiset: text ->
// how many times it appears. The guard fails when a text appears MORE often
// than recorded (new untranslated UI) or LESS often (the baseline is stale:
// run --update so the ratchet stays tight and a fixed string cannot quietly
// come back). English that is English on purpose - brand names, the Amazon
// sentence, the Elo pages, admin tools - lives in i18n/src/english_on_purpose.json.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const BASELINE = path.join(ROOT, "i18n", "src", "untranslated_baseline.json");
const ON_PURPOSE = path.join(ROOT, "i18n", "src", "english_on_purpose.json");

// Attributes / props whose value a reader sees or hears.
export const VISIBLE_ATTRS = new Set([
  "title", "placeholder", "aria-label", "alt",
  "label", "emptyText", "titleHint", "hint", "subtitle", "doneLabel", "skipLabel",
  "confirmLabel", "heading", "caption", "lede", "sub", "ariaLabel", "noun",
]);
const LETTERS = /[A-Za-z]{2,}/;

// ---------------------------------------------------------------- lexer ----
// A deliberately small JS lexer: enough to walk Index.html's one app script,
// telling code from strings, comments, regexes and template literals, and
// handing every html`` template to the htm walker below.

const isIdStart = (c) => /[A-Za-z_$]/.test(c);
const isId = (c) => /[A-Za-z0-9_$]/.test(c);
const MULTI_OPS = ["===", "!==", "=>", "==", "!=", "&&", "||", "??", "?.", "..."];
const REGEX_AFTER_KW =new Set(["return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw", "instanceof", "yield", "await"]);

// Lex JS starting at i. Stops at an unmatched `}` when `stopAtBrace`, else at
// the end of `s`. Returns {tokens, end}. Tokens: {t:"str"|"tpl"|"html"|"id"|"num"|"p", v, pos}.
export function lex(s, i, stopAtBrace) {
  const toks = [];
  let depth = 0;
  const prevSig = () => toks.length ? toks[toks.length - 1] : null;
  const regexAllowed = () => {
    const p = prevSig();
    if(!p) return true;
    if(p.t === "id") return REGEX_AFTER_KW.has(p.v);
    if(p.t === "num" || p.t === "str" || p.t === "tpl" || p.t === "html") return false;
    if(p.t === "p") return !(p.v === ")" || p.v === "]" || p.v === "}");
    return true;
  };
  while(i < s.length) {
    const c = s[i];
    if(c === " " || c === "\t" || c === "\n" || c === "\r") { i++; continue; }
    if(c === "/" && s[i + 1] === "/") { while(i < s.length && s[i] !== "\n") i++; continue; }
    if(c === "/" && s[i + 1] === "*") { const e = s.indexOf("*/", i + 2); i = e < 0 ? s.length : e + 2; continue; }
    if(c === "'" || c === '"') {
      const st = i; let v = ""; i++;
      while(i < s.length && s[i] !== c) {
        if(s[i] === "\\" && s[i + 1] === "u" && /^[0-9a-fA-F]{4}$/.test(s.slice(i + 2, i + 6))) {
          v += String.fromCharCode(parseInt(s.slice(i + 2, i + 6), 16)); i += 6; continue;
        }
        if(s[i] === "\\") { v += unesc(s[i + 1]); i += 2; continue; }
        if(s[i] === "\n") break;
        v += s[i++];
      }
      i++;
      toks.push({t: "str", v, pos: st, end: i, raw: s.slice(st, i)});
      continue;
    }
    if(c === "`") {
      const p = prevSig();
      const isHtml = p && p.t === "id" && p.v === "html";
      const st = i;
      const r = isHtml ? walkHtml(s, i + 1) : walkTpl(s, i + 1);
      i = r.end;
      if(isHtml) { toks.pop(); toks.push({t: "html", v: r, pos: st}); }
      else toks.push({t: "tpl", v: r, pos: st});
      continue;
    }
    if(c === "/" && regexAllowed()) {
      i++; let inCls = false;
      while(i < s.length) {
        const d = s[i];
        if(d === "\\") { i += 2; continue; }
        if(d === "\n") break;
        if(inCls) { if(d === "]") inCls = false; }
        else if(d === "[") inCls = true;
        else if(d === "/") { i++; break; }
        i++;
      }
      while(i < s.length && isId(s[i])) i++;
      toks.push({t: "num", v: "/re/", pos: i});
      continue;
    }
    if(isIdStart(c)) {
      const st = i; while(i < s.length && isId(s[i])) i++;
      toks.push({t: "id", v: s.slice(st, i), pos: st});
      continue;
    }
    if(/[0-9]/.test(c) || (c === "." && /[0-9]/.test(s[i + 1]))) {
      const st = i; i++;
      while(i < s.length && /[0-9A-Za-z_.]/.test(s[i])) i++;
      toks.push({t: "num", v: s.slice(st, i), pos: st});
      continue;
    }
    if(c === "{") { depth++; toks.push({t: "p", v: c, pos: i}); i++; continue; }
    if(c === "}") {
      if(depth === 0 && stopAtBrace) return {tokens: toks, end: i + 1};
      depth--; toks.push({t: "p", v: c, pos: i}); i++; continue;
    }
    const op = MULTI_OPS.find(o => s.startsWith(o, i));
    if(op) { toks.push({t: "p", v: op, pos: i}); i += op.length; continue; }
    toks.push({t: "p", v: c, pos: i}); i++;
  }
  return {tokens: toks, end: i};
}

function unesc(c) {
  return c === "n" ? "\n" : c === "t" ? "\t" : c === "u" ? "" : c;
}

// A plain template literal: static parts + nested expressions.
function walkTpl(s, i) {
  const quasis = []; const exprs = []; let cur = "";
  while(i < s.length) {
    const c = s[i];
    if(c === "\\") { cur += s[i + 1] || ""; i += 2; continue; }
    if(c === "`") { quasis.push(cur); return {quasis, exprs, end: i + 1}; }
    if(c === "$" && s[i + 1] === "{") {
      quasis.push(cur); cur = "";
      const r = lex(s, i + 2, true);
      exprs.push(r.tokens); i = r.end; continue;
    }
    cur += c; i++;
  }
  return {quasis, exprs, end: i};
}

// An htm template. Walks the markup as one state machine across the static
// parts, recording text nodes, literal attribute values and the SLOT each
// ${expr} sits in: {kind:"child"} or {kind:"attr", name}.
function walkHtml(s, i) {
  const out = {texts: [], attrs: [], slots: [], end: 0};
  let state = "TEXT"; let text = ""; let runStart = i; let runFrom = "start"; let esc = false;
  let attrName = null; let lastName = ""; let quote = null; let qval = ""; let qpos = 0;
  // A text RUN is the raw source between two boundaries (a tag, a ${slot},
  // the template's ends). Its trimmed core is the finding; the boundaries say
  // whether it can be wrapped on its own (scripts/i18n_wrap.mjs).
  const flushText = (to, at) => {
    const t = text.replace(/\s+/g, " ").trim();
    if(t) out.texts.push({v: t, pos: runStart, start: runStart, end: at, from: runFrom, to,
      prevSlot: out.slots.length - 1, esc});
    text = ""; esc = false;
  };
  while(i < s.length) {
    const c = s[i];
    if(c === "\\" && s[i + 1] === "`") { if(state === "TEXT") { text += "`"; esc = true; } i += 2; continue; }
    if(c === "\\") { if(state === "TEXT") { text += s[i + 1]; esc = true; } else if(quote) qval += s[i + 1]; i += 2; continue; }
    if(c === "`") { if(state === "TEXT") flushText("end", i); out.end = i + 1; return out; }
    if(c === "$" && s[i + 1] === "{") {
      let slot;
      if(state === "TEXT") { flushText("slot", i); slot = {kind: "child"}; }
      else if(state === "QUOTE") slot = {kind: "attr", name: attrName, inQuote: true};
      else if(state === "TAG" && attrName) { slot = {kind: "attr", name: attrName}; attrName = null; }
      else slot = {kind: "other"};
      const r = lex(s, i + 2, true);
      out.slots.push({slot, tokens: r.tokens, pos: i, end: r.end});
      i = r.end;
      if(state === "TEXT") { runStart = i; runFrom = "slot"; }
      continue;
    }
    if(state === "TEXT") {
      if(c === "<") {
        flushText("tag", i);
        if(s.startsWith("<!--", i)) { const e = s.indexOf("-->", i); i = e < 0 ? s.length : e + 3; runStart = i; runFrom = "tag"; continue; }
        state = "TAG"; attrName = null; lastName = ""; i++; continue;
      }
      text += c; i++; continue;
    }
    if(state === "TAG") {
      if(c === ">") { state = "TEXT"; runStart = i + 1; runFrom = "tag"; i++; continue; }
      if(c === "=") { attrName = lastName; i++; continue; }
      if((c === '"' || c === "'") && attrName) { state = "QUOTE"; quote = c; qval = ""; qpos = i; i++; continue; }
      if(/[A-Za-z_:@-]/.test(c) || /[0-9]/.test(c)) {
        const st = i; while(i < s.length && /[A-Za-z0-9_:@.-]/.test(s[i])) i++;
        const name = s.slice(st, i);
        if(attrName) { attrName = null; } else lastName = name;
        continue;
      }
      i++; continue;
    }
    if(state === "QUOTE") {
      if(c === quote) {
        out.attrs.push({name: attrName, v: qval, pos: qpos, start: qpos, end: i + 1,
          pure: out.slots.length === 0 || out.slots[out.slots.length - 1].pos < qpos});
        state = "TAG"; attrName = null; quote = null; i++; continue;
      }
      qval += c; i++; continue;
    }
  }
  out.end = i;
  return out;
}

// ------------------------------------------------------------ analysis ----

// String literals sitting directly in a slot: not inside a call's arguments,
// not an index, not compared, not an object key. Grouping parens and the
// ternary / && / || / + operators are transparent.
export function slotStrings(tokens) {
  const found = [];
  const stack = [];
  for(let k = 0; k < tokens.length; k++) {
    const tk = tokens[k];
    if(tk.t === "p" && (tk.v === "(" || tk.v === "[" || tk.v === "{")) {
      const prev = tokens[k - 1];
      const call = tk.v === "(" && prev && (prev.t === "id" || (prev.t === "p" && (prev.v === ")" || prev.v === "]")) || (prev && prev.t === "tpl"));
      const isArrowBody = tk.v === "{";
      stack.push(tk.v === "(" ? (call && !(prev && prev.t === "id" && ["if", "while", "for", "switch", "return", "typeof"].includes(prev.v)) ? "call" : "group") : (isArrowBody ? "brace" : "index"));
      continue;
    }
    if(tk.t === "p" && (tk.v === ")" || tk.v === "]" || tk.v === "}")) { stack.pop(); continue; }
    if(stack.some(x => x !== "group")) continue;
    if(tk.t !== "str" && tk.t !== "tpl") continue;
    const prev = tokens[k - 1]; const next = tokens[k + 1];
    const cmp = (t) => t && t.t === "p" && ["===", "!==", "==", "!="].includes(t.v);
    if(cmp(prev) || cmp(next)) continue;
    if(prev && prev.t === "id" && (prev.v === "in" || prev.v === "case")) continue;
    if(next && next.t === "p" && (next.v === "." || next.v === "[" || next.v === "?.")) continue;
    if(next && next.t === "id" && next.v === "in") continue;
    const v = tk.t === "str" ? tk.v : tk.v.quasis.join("{}");
    found.push({v, pos: tk.pos, tok: tk, prev, next});
  }
  return found;
}

const VISIBLE_TPL = (v) => LETTERS.test(v.replace(/\{\}/g, " "));

// Slots that are pure decoration: a text run beside one of these is still a
// whole phrase on its own ("${uiIcon('news')} News"), so it can be wrapped
// without splitting a sentence.
const ICON_CALLS = new Set(["uiIcon", "extIcon", "_navSvg", "_deckSvg", "LorcanaGlyph"]);
const isIconSlot = (sl) => !!sl && sl.tokens.length > 0 && sl.tokens[0].t === "id" && ICON_CALLS.has(sl.tokens[0].v);
// Object-literal fields whose string value is shown on screen somewhere.
export const DATA_FIELDS = new Set(["label", "title", "text", "note", "kicker", "dateLabel", "caption", "hint",
  "desc", "sub", "short", "long", "lbl", "heading", "dek", "lede", "tip", "subtitle", "help", "explain", "empty", "cta"]);
// Lookup tables of display strings: HOME_BANNER_LABELS, SC_KIND_PLURAL, CAL_KIND_SHORT...
export const LABEL_MAP_RE = /^[A-Z][A-Z0-9_]*_(LABELS?|SHORT|PLURAL|LANES|LONG|BADGE|TITLES?|NAMES|NOUNS?)$/;
const INLINE_TAGS = new Set(["b", "i", "a", "strong", "em", "code", "kbd", "u", "mark", "abbr", "sup", "sub", "small"]);
const wrapCall = (v) => "_t(" + JSON.stringify(v) + ")";

// Every finding in one script body. Each carries `fix` when it is safe to
// wrap mechanically ({start, end, repl} in script offsets), else null - a
// fragment of a sentence, a concatenation, a template: those need a person
// to write one key with {placeholders}.
export function audit(src) {
  const findings = [];
  const add = (v, pos, kind, fix) => {
    const t = v.replace(/\s+/g, " ").trim();
    if(!t || !VISIBLE_TPL(t)) return;
    // bare URLs and anchors are not prose
    if(/^(https?:|mailto:|\/|#)/.test(t)) return;
    findings.push({v: t, pos, kind, fix: fix || null});
  };
  const strFix = (tk, prev, next) => (tk.t === "str" && tk.v === tk.v.trim() && !/^[a-z.,;:)]/.test(tk.v) && !/[\n\\]/.test(tk.raw)
      && !(prev && prev.v === "+") && !(next && next.v === "+"))
    ? {start: tk.pos, end: tk.end, repl: wrapCall(tk.v)} : null;
  const visitTokens = (tokens) => {
    for(let k = 0; k < tokens.length; k++) {
      const tk = tokens[k];
      if(tk.t === "html") visitHtml(tk.v);
      else if(tk.t === "tpl") tk.v.exprs.forEach(visitTokens);
      // DATA: {label: "Sets"} - a display string kept in a const and rendered
      // elsewhere. It cannot be wrapped where it stands (some labels are also
      // keys), so it counts as untranslated until ui.json has an entry for it.
      if(tk.t === "id" && DATA_FIELDS.has(tk.v) && tokens[k + 1] && tokens[k + 1].v === ":"
         && tokens[k - 1] && tokens[k - 1].t === "p" && (tokens[k - 1].v === "{" || tokens[k - 1].v === ",")) {
        const val = tokens[k + 2]; const after = tokens[k + 3];
        if(val && val.t === "str" && (!after || after.v === "," || after.v === "}")) add(val.v, val.pos, "data:" + tk.v, null);
      }
      // const X_LABELS = {chase: "Chase Movers", ...} - a lookup table of display
      // strings keyed by something internal; every value is data.
      if(tk.t === "id" && tk.v === "const" && tokens[k + 1] && tokens[k + 1].t === "id" && LABEL_MAP_RE.test(tokens[k + 1].v)
         && tokens[k + 2] && tokens[k + 2].v === "=" && tokens[k + 3] && tokens[k + 3].v === "{") {
        let depth = 0;
        for(let j = k + 3; j < tokens.length; j++) {
          const x = tokens[j];
          if(x.t === "p" && (x.v === "[" || x.v === "{" || x.v === "(")) depth++;
          else if(x.t === "p" && (x.v === "]" || x.v === "}" || x.v === ")")) { if(--depth === 0) break; }
          else if(depth === 1 && x.t === "str" && tokens[j - 1] && tokens[j - 1].v === ":") add(x.v, x.pos, "data:map", null);
        }
      }
      // items: ["...", "..."] - a list of display lines (a news article's bullets)
      if(tk.t === "id" && tk.v === "items" && tokens[k + 1] && tokens[k + 1].v === ":" && tokens[k + 2] && tokens[k + 2].v === "[") {
        let depth = 0;
        for(let j = k + 2; j < tokens.length; j++) {
          const x = tokens[j];
          if(x.t === "p" && (x.v === "[" || x.v === "{" || x.v === "(")) depth++;
          else if(x.t === "p" && (x.v === "]" || x.v === "}" || x.v === ")")) { if(--depth === 0) break; }
          else if(depth === 1 && x.t === "str") add(x.v, x.pos, "data:items", null);
        }
      }
      // flashToast("...") / flashToast(`...`)
      if(tk.t === "id" && tk.v === "flashToast" && tokens[k + 1] && tokens[k + 1].v === "(") {
        const a = tokens[k + 2];
        if(a && (a.t === "str" || a.t === "tpl")) {
          const after = tokens[k + 3];
          // "x" + y / "x" ? ... - still a literal message
          if(!after || after.v === "," || after.v === ")" || after.v === "+")
            add(a.t === "str" ? a.v : a.v.quasis.join("{}"), a.pos, "toast", a.t === "str" ? strFix(a, null, after) : null);
        }
      }
    }
  };
  const visitHtml = (h) => {
    for(const t of h.texts) {
      let fix = null;
      const okFrom = t.from !== "slot" || isIconSlot(h.slots[t.prevSlot]);
      const okTo = t.to !== "slot" || isIconSlot(h.slots[t.prevSlot + 1]);
      // a run that starts lower-case or with punctuation, or sits against
      // inline markup (<b>, <a>, <code>...), is part of a longer sentence
      const before = t.from === "tag" ? /<\/?\s*([A-Za-z]+)[^<>]*>\s*$/.exec(src.slice(Math.max(0, t.start - 200), t.start)) : null;
      const after = t.to === "tag" ? /^<\/?\s*([A-Za-z]+)/.exec(src.slice(t.end, t.end + 40)) : null;
      const inline = (m) => !!m && INLINE_TAGS.has(m[1].toLowerCase());
      const fragment = /^[a-z.,;:)\]–—-]/.test(t.v) || inline(before) || inline(after);
      if(okFrom && okTo && !fragment && !t.esc && !/&[#\w]+;/.test(t.v) && !/[{}]/.test(t.v)) {
        const raw = src.slice(t.start, t.end);
        const lead = raw.length - raw.trimStart().length;
        const trail = raw.length - raw.trimEnd().length;
        fix = {start: t.start + lead, end: t.end - trail, repl: "${" + wrapCall(t.v) + "}"};
      }
      add(t.v, t.pos, "text", fix);
    }
    for(const a of h.attrs) if(a.name && VISIBLE_ATTRS.has(a.name)) {
      const ok = a.pure && a.v === a.v.trim() && !/[\\{}]/.test(a.v) && !/&[#\w]+;/.test(a.v);
      add(a.v, a.pos, "attr:" + a.name, ok ? {start: a.start, end: a.end, repl: "${" + wrapCall(a.v) + "}"} : null);
    }
    for(const sl of h.slots) {
      if(sl.slot.kind === "child" || (sl.slot.kind === "attr" && VISIBLE_ATTRS.has(sl.slot.name))) {
        // RENDER: ${k.label} shows a data label - route it through _t()
        const tt = sl.tokens;
        const member = tt.length >= 3 && tt.length <= 5 && tt[0].t === "id" && tt.slice(1).every((x, j) => j % 2 === 0 ? (x.v === "." || x.v === "?.") : x.t === "id");
        if(member && tt.length % 2 === 1 && DATA_FIELDS.has(tt[tt.length - 1].v)) {
          const expr = src.slice(tt[0].pos, tt[tt.length - 1].pos + tt[tt.length - 1].v.length);
          findings.push({v: "${" + expr + "}", pos: tt[0].pos, kind: "render", fix: {start: tt[0].pos, end: tt[0].pos + expr.length, repl: "_t(" + expr + ")"}});
        }
        for(const f of slotStrings(sl.tokens))
          add(f.v, f.pos, sl.slot.kind === "child" ? "child" : "attr:" + sl.slot.name,
            f.tok.t === "str" ? strFix(f.tok, f.prev, f.next) : null);
      }
      visitTokens(sl.tokens);
    }
  };
  visitTokens(lex(src, 0, false).tokens);
  return findings;
}

// --------------------------------------------------------------- driver ----

export function appScript(html) {
  // The app is the one big inline script after scanner.js; take the largest.
  let best = null;
  const re = /<script>([\s\S]*?)\n\s*<\/script>/g;
  let m;
  while((m = re.exec(html))) {
    if(!best || m[1].length > best.body.length) best = {body: m[1], start: m.index + "<script>".length};
  }
  return best;
}

export function componentIndex(src) {
  // top-level declarations, in order: "function Name(" / "const Name ="
  const marks = [];
  const re = /^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|^const\s+([A-Za-z_$][\w$]*)\s*=/gm;
  let m;
  while((m = re.exec(src))) marks.push({pos: m.index, name: m[1] || m[2]});
  return (pos) => {
    let lo = 0, hi = marks.length - 1, ans = "(top)";
    while(lo <= hi) { const mid = (lo + hi) >> 1; if(marks[mid].pos <= pos) { ans = marks[mid].name; lo = mid + 1; } else hi = mid - 1; }
    return ans;
  };
}

export function loadOnPurpose() {
  const raw = JSON.parse(fs.readFileSync(ON_PURPOSE, "utf8"));
  const comps = (raw.components || []).map(c => new RegExp("^(?:" + c + ")$"));
  const strings = new Set(raw.strings || []);
  const patterns = (raw.patterns || []).map(p => new RegExp(p));
  return (f) => comps.some(r => r.test(f.comp)) || strings.has(f.v) || patterns.some(r => r.test(f.v));
}

export function collect(file = path.join(ROOT, "Index.html")) {
  const html = fs.readFileSync(file, "utf8");
  const sc = appScript(html);
  const compOf = componentIndex(sc.body);
  const lineStarts = [];
  const lineOf = (pos) => html.slice(0, sc.start + pos).split("\n").length;
  const skip = loadOnPurpose();
  // a data string is translated once ui.json has it ("" counts: deliberately English)
  const ui = JSON.parse(fs.readFileSync(path.join(ROOT, "i18n", "src", "ui.json"), "utf8"));
  const all = audit(sc.body).map(f => ({...f, comp: compOf(f.pos)}));
  const kept = all.filter(f => !skip(f) && !(f.kind.startsWith("data:") && f.v in ui));
  return {all, kept, lineOf};
}

export function counts(findings) {
  const m = {};
  for(const f of findings) m[f.v] = (m[f.v] || 0) + 1;
  return m;
}

export function diff(cur, base) {
  const added = []; const removed = [];
  for(const [k, n] of Object.entries(cur)) if(n > (base[k] || 0)) added.push([k, n - (base[k] || 0)]);
  for(const [k, n] of Object.entries(base)) if(n > (cur[k] || 0)) removed.push([k, n - (cur[k] || 0)]);
  return {added, removed};
}

function writeBaseline(c) {
  const keys = Object.keys(c).sort((a, b) => a.localeCompare(b));
  const body = "{\n" + keys.map(k => " " + JSON.stringify(k) + ": " + c[k]).join(",\n") + "\n}\n";
  fs.writeFileSync(BASELINE, body);
}

function main() {
  const args = process.argv.slice(2);
  const {kept, lineOf} = collect();
  const cur = counts(kept);
  const base = fs.existsSync(BASELINE) ? JSON.parse(fs.readFileSync(BASELINE, "utf8")) : {};
  if(args.includes("--check")) {
    const {added, removed} = diff(cur, base);
    if(added.length) {
      console.log(`${added.length} untranslated on-screen string(s) are NEW (not in i18n/src/untranslated_baseline.json):`);
      for(const [k] of added) {
        const f = kept.filter(x => x.v === k).slice(-1)[0];
        console.log(`  Index.html:${lineOf(f.pos)}  [${f.comp}] ${f.kind}  ${JSON.stringify(k)}`);
      }
      console.log("\nWrap each in _t(\"...\") (or _term for a game term) and add it to i18n/src/ui.json with");
      console.log("ja/de/fr/it, then `python scripts/build_i18n.py`. English on purpose (a brand, an admin");
      console.log("tool) goes in i18n/src/english_on_purpose.json. Only if it truly must ship English for now:");
      console.log("  node scripts/i18n_audit.mjs --update --accept");
    }
    if(removed.length) {
      console.log(`${removed.length} string(s) were translated or removed but are still in the baseline -`);
      console.log("run `node scripts/i18n_audit.mjs --update` so they cannot come back unnoticed:");
      for(const [k] of removed.slice(0, 40)) console.log("  " + JSON.stringify(k));
    }
    if(!added.length && !removed.length) console.log(`i18n audit: OK (${kept.length} known untranslated, ${Object.keys(cur).length} distinct)`);
    process.exit(added.length || removed.length ? 1 : 0);
  }
  if(args.includes("--update")) {
    const {added} = diff(cur, base);
    if(added.length && !args.includes("--accept")) {
      console.log(`refusing: ${added.length} NEW untranslated string(s); translate them, or pass --accept:`);
      for(const [k] of added.slice(0, 40)) console.log("  " + JSON.stringify(k));
      process.exit(1);
    }
    writeBaseline(cur);
    console.log(`baseline: ${kept.length} occurrences, ${Object.keys(cur).length} distinct`);
    return;
  }
  const only = args.includes("--list") ? (args[args.indexOf("--list") + 1] || null) : undefined;
  if(only !== undefined) {
    for(const f of kept) if(!only || f.comp === only) console.log(`${lineOf(f.pos)}\t${f.comp}\t${f.kind}\t${f.v}`);
    return;
  }
  const by = {};
  for(const f of kept) by[f.comp] = (by[f.comp] || 0) + 1;
  for(const [c, n] of Object.entries(by).sort((a, b) => b[1] - a[1])) console.log(String(n).padStart(5), c);
  console.log(`total ${kept.length}`);
}

if(process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
