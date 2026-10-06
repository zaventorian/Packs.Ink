// test_admin_checks_caller.mjs - an admin check only answers for the caller.
//
//     node scripts/test_admin_checks_caller.mjs
//
// is_tournament_admin(uuid) and is_elo_admin(uuid) are executable by every
// signed-in user (RLS policies call them as the querying role) and user ids
// are public, so until migration 191 any account could ask "is <user> an
// admin" for anybody. 191 makes them answer false for another user's id when
// the request comes from anon / authenticated. That is only safe because
// every caller passes the caller's OWN id; this pins both halves:
//
//   1. the newest definition of every role check that takes a user id keeps
//      the caller-only guard (a later CREATE OR REPLACE that drops it is
//      silent: the check just starts answering for everyone again);
//   2. every SQL call site passes auth.uid() (directly, through (select ...),
//      or through a v_uid assigned from it), and every client call passes the
//      signed-in user's own id. A caller asking about SOMEONE ELSE would now
//      get false and silently lock an admin out of something.
import { readFileSync, readdirSync } from "node:fs";

const root = new URL("../", import.meta.url);
const dir = new URL("supabase/", root);
const files = readdirSync(dir).filter(f => /^\d+_.*\.sql$/.test(f))
  .sort((a, b) => parseInt(a) - parseInt(b) || a.localeCompare(b));
const read = (f) => readFileSync(new URL(f, dir), "utf8").replace(/\r\n/g, "\n");
// Comments out, so a sentence that names a function cannot satisfy or trip anything.
const code = (s) => s.replace(/--[^\n]*/g, "");
const src = readFileSync(new URL("Index.html", root), "utf8").replace(/\r\n/g, "\n");

let fails = 0;
const ok = (name, cond) => { if(!cond) fails++; console.log(`${cond ? "  ok  " : "  FAIL"} ${name}`); };

// ---- 1. newest definition of every user-id role check
const latest = new Map();          // name -> {file, body}
for(const f of files){
  const s = code(read(f));
  const re = /create\s+or\s+replace\s+function\s+public\.((?:is|can|has)_\w+)\s*\(\s*p_\w+\s+uuid\s*\)/gi;
  let m;
  while((m = re.exec(s))){
    const open = s.indexOf("$$", m.index), close = s.indexOf("$$", open + 2);
    latest.set(m[1], {file: f, body: s.slice(m.index, close + 2)});
  }
}
ok("found is_tournament_admin and is_elo_admin", latest.has("is_tournament_admin") && latest.has("is_elo_admin"));
for(const [name, {file, body}] of latest){
  ok(`${name} (${file}) answers only for the caller`,
    /p_user = \(select auth\.uid\(\)\)/.test(body)
    && /coalesce\(current_setting\('role', true\), 'none'\) not in \('anon', 'authenticated'\)/.test(body));
}

// ---- 2. every SQL caller passes the caller's own id
const SELF = /^\s*(?:\(\s*select\s+auth\.uid\(\)\s*(?:as\s+uid\s*)?\)|auth\.uid\(\)|v_uid)\s*$/i;
let calls = 0;
for(const f of files){
  const s = code(read(f));
  for(const name of latest.keys()){
    const re = new RegExp("(?<![\\w.])(?:public\\.)?" + name + "\\s*\\(", "g");
    let m;
    while((m = re.exec(s))){
      // the argument, balancing parentheses
      let i = m.index + m[0].length, depth = 1;
      const start = i;
      while(i < s.length && depth){ if(s[i] === "(") depth++; else if(s[i] === ")") depth--; i++; }
      const arg = s.slice(start, i - 1);
      if(/^\s*(?:p_\w+\s+)?uuid\s*$/i.test(arg)) continue;   // a declaration / grant / revoke
      calls++;
      ok(`${f}: ${name}(${arg.trim()}) passes the caller's own id`, SELF.test(arg));
      if(/^\s*v_uid\s*$/.test(arg))
        ok(`${f}: v_uid there is assigned from auth.uid()`, /v_uid\s+uuid\s*:=\s*\(?\s*(?:select\s+)?auth\.uid\(\)/i.test(s)
          && !/v_uid\s*:=\s*(?!\(?\s*(?:select\s+)?auth\.uid\(\))/i.test(s.replace(/v_uid\s+uuid\s*:=/gi, "")));
    }
  }
}
ok(`found the SQL call sites (${calls})`, calls >= 20);

// ---- 2b. the client only ever asks about the signed-in user
const clientCalls = [...src.matchAll(/rpc\("(is_tournament_admin|is_elo_admin)",\s*\{p_user:\s*([^}]*)\}/g)];
ok(`found the client calls (${clientCalls.length})`, clientCalls.length >= 2);
for(const [, fn, arg] of clientCalls) ok(`client ${fn}({p_user: ${arg.trim()}}) is the signed-in user`, arg.trim() === "user.id");

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
