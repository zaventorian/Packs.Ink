// i18n_wrap.mjs - wrap the mechanically-safe untranslated strings in _t().
//
//   node scripts/i18n_wrap.mjs                    # dry run: what would change
//   node scripts/i18n_wrap.mjs --apply            # rewrite Index.html
//   node scripts/i18n_wrap.mjs --apply --comp HomeView,CalendarView
//
// "Safe" is decided by scripts/i18n_audit.mjs (`fix` on a finding): a whole
// text node between tags, a whole quoted attribute, a string literal standing
// alone in a slot, a literal toast. Sentence fragments around ${values} and
// concatenations are NOT touched - they need one key with {placeholders},
// written by hand, or the translation comes out in English word order.
//
// After applying: add the new keys to i18n/src/ui.json (the printed list),
// `python scripts/build_i18n.py`, `node scripts/i18n_audit.mjs --update`, and
// run the guard suite - a wrap changes source text some guards anchor on.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { collect } from "./i18n_audit.mjs";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const FILE = path.join(ROOT, "Index.html");
const args = process.argv.slice(2);
const only = args.includes("--comp") ? new Set(args[args.indexOf("--comp") + 1].split(",")) : null;

const html = fs.readFileSync(FILE, "utf8");
const m = /<script>([\s\S]*?)\n\s*<\/script>/g;
let best = null, mm;
while((mm = m.exec(html))) if(!best || mm[1].length > best.body.length) best = {body: mm[1], start: mm.index + "<script>".length};

const {kept} = collect(FILE);
const fixes = kept.filter(f => f.fix && (!only || only.has(f.comp)))
  .sort((a, b) => b.fix.start - a.fix.start);
// no overlaps (a slot string inside an attribute already being wrapped)
const chosen = [];
let floor = Infinity;
for(const f of fixes) { if(f.fix.end <= floor) { chosen.push(f); floor = f.fix.start; } }

let out = html;
for(const f of chosen) {
  const a = best.start + f.fix.start, b = best.start + f.fix.end;
  out = out.slice(0, a) + f.fix.repl + out.slice(b);
}
const ui = JSON.parse(fs.readFileSync(path.join(ROOT, "i18n", "src", "ui.json"), "utf8"));
const newKeys = [...new Set(chosen.map(f => f.v))].filter(k => !(k in ui));
if(args.includes("--apply")) {
  fs.writeFileSync(FILE, out);
  console.log(`wrapped ${chosen.length} string(s); ${newKeys.length} key(s) need ui.json entries`);
} else {
  for(const f of chosen.slice().reverse()) console.log(`${f.comp}\t${f.kind}\t${f.v}`);
  console.log(`\n${chosen.length} to wrap, ${newKeys.length} new key(s) (dry run - pass --apply)`);
}
if(args.includes("--keys")) fs.writeFileSync(args[args.indexOf("--keys") + 1], JSON.stringify(newKeys, null, 1));
