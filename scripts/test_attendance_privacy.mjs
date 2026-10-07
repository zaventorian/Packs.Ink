// test_attendance_privacy.mjs - the Store Status tab reads attendance by
// pseudonym only.
//
//     node scripts/test_attendance_privacy.mjs
//
// rph_event_attendance holds a name, an RPH account id and a "First L."
// account name for every person at every scraped event. The tab only needs
// "how many distinct people", so migration 188 adds person_key (an HMAC of
// the old client key under a server-side secret) and `played` (the old
// filter, as a generated column), and 189 leaves anon exactly those plus
// event_id and registration_status. Every way this breaks is silent:
//
//   1. The client selects, filters or orders on a column 189 does not grant:
//      the tab 42501s for everybody the day 189 lands (or, before it lands,
//      quietly keeps reading names).
//   2. person_key drifts from the old key: one person becomes two, or two
//      become one, and Unique Fans moves with nobody noticing.
//   3. `played` drifts from PLAYED in report_store_tiers.py: the tab and the
//      offline tier report disagree about who played.
//   4. The key becomes a plain hash of the identity, which anyone can compute
//      from a name - the lookup this exists to stop.
//
// Reads the real code out of Index.html and the real migrations.
import { readFileSync, readdirSync } from "node:fs";

const root = new URL("../", import.meta.url);
const src = readFileSync(new URL("Index.html", root), "utf8").replace(/\r\n/g, "\n");
const mig = (re) => {
  const f = readdirSync(new URL("supabase/", root)).filter(n => re.test(n));
  if (f.length !== 1) throw new Error("expected one migration for " + re + ", got " + f.join(", "));
  return readFileSync(new URL("supabase/" + f[0], root), "utf8").replace(/\r\n/g, "\n");
};
const m188 = mig(/^188_.*\.sql$/);
const m189 = mig(/^189_.*\.sql$/);
const tiers = readFileSync(new URL("scripts/elo/report_store_tiers.py", root), "utf8");

let fails = 0;
const ok = (name, cond) => { if (!cond) fails++; console.log(`${cond ? "  ok  " : "  FAIL"} ${name}`); };

// ---- 189: what anon may read
const grantM = m189.match(/grant select \(([^)]*)\)\s+on public\.rph_event_attendance to anon, authenticated;/);
ok("189 grants a column list to anon + authenticated", !!grantM);
const granted = new Set(grantM ? grantM[1].split(",").map(s => s.trim()) : []);
ok("189 revokes the table-wide select first",
  /revoke select on public\.rph_event_attendance from anon, authenticated;/.test(m189)
  && m189.indexOf("revoke select") < m189.indexOf("grant select ("));
for (const c of ["best_identifier", "rph_user_id", "account_name", "final_place_in_standings",
                 "matches_won", "matches_lost", "matches_drawn", "total_match_points", "is_guest"])
  ok(`189 does not grant ${c}`, !granted.has(c));
ok("189 grants what the tab needs", ["event_id", "person_key", "played", "registration_status"].every(c => granted.has(c)));

// ---- Index.html: every read of the table stays inside the grant
const reads = [...src.matchAll(/sbFetchAll\("rph_event_attendance",\s*\{([\s\S]*?)\}\s*,\s*null\)/g)].map(m => m[1]);
ok("found the two attendance reads (played pass + fallback)", reads.length === 2);
const PARAMS = new Set(["select", "order", "or", "and", "limit", "offset"]);
for (const [i, body] of reads.entries()) {
  const cols = new Set();
  for (const m of body.matchAll(/(\w+):\s*("[^"]*"|[A-Za-z_][\w.]*)/g)) {
    const [, k, v] = m;
    if (k === "select") v.replace(/"/g, "").split(",").forEach(c => cols.add(c.trim()));
    else if (k === "order") v.replace(/"/g, "").split(",").forEach(c => cols.add(c.trim().split(".")[0]));
    else if (!PARAMS.has(k)) cols.add(k);        // a column filter: played: "is.true"
    else cols.add("<" + k + ">");                 // or= / and= would hide columns in a string
  }
  const bad = [...cols].filter(c => !granted.has(c));
  ok(`read ${i + 1} touches only granted columns (${[...cols].join(", ")})`, bad.length === 0);
}
ok("no other code reads the table", (src.match(/["'`]rph_event_attendance["'`?]/g) || []).length === 2);
ok("the old name-bearing select is gone", !/select:\s*"event_id,rph_user_id,best_identifier/.test(src));

// ---- rphPersonKey prefers the server's key, and its fallback is what 188 hashes
const pk = src.slice(src.indexOf("const rphPersonKey = (a) =>"), src.indexOf(".toLowerCase();", src.indexOf("const rphPersonKey = (a) =>")) + ".toLowerCase();".length);
const rphPersonKey = new Function(pk + "\nreturn rphPersonKey;")();
ok("person_key wins", rphPersonKey({ person_key: "abc", rph_user_id: 7, best_identifier: "X" }) === "k:abc");
ok("fallback: account id", rphPersonKey({ rph_user_id: 7, best_identifier: "X" }) === "u:7");
ok("fallback: folded guest name", rphPersonKey({ rph_user_id: null, best_identifier: "  Guesty " }) === "n:guesty");
ok("188 hashes 'u:' || id", /'u:' \|\| p_user_id::text/.test(m188));
ok("188 hashes 'n:' || lower(trimmed name)", /'n:' \|\| lower\(regexp_replace\(coalesce\(p_ident, ''\), '\^\\s\+\|\\s\+\$', '', 'g'\)\)/.test(m188));

// ---- the key is keyed, not a plain hash anyone can compute
const keyFn = m188.slice(m188.indexOf("create or replace function private.rph_person_key"), m188.indexOf("$$;", m188.indexOf("create or replace function private.rph_person_key")));
ok("key is an HMAC under the stored secret", /extensions\.hmac\(/.test(keyFn) && /private\.server_secrets/.test(keyFn) && /s\.secret/.test(keyFn));
ok("key is not md5/digest of the identity", !/md5\(|digest\(/.test(keyFn));
ok("secret table is closed to the API roles",
  /revoke all on private\.server_secrets from public, anon, authenticated, service_role;/.test(m188)
  && /revoke all on schema private from public, anon, authenticated;/.test(m188));
ok("key function is closed to the API roles",
  /revoke all on function private\.rph_person_key\(bigint, text\) from public, anon, authenticated, service_role;/.test(m188));
ok("person_key is NOT NULL (a null would merge everyone into one fan)", /alter column person_key set not null/.test(m188));

// ---- played == PLAYED in report_store_tiers.py
const opSql = { ">=": "gte", ">": "gt" };
const genM = m188.match(/played boolean\s+generated always as \(([\s\S]*?)\) stored/);
ok("188 defines played as a generated column", !!genM);
const fromSql = new Set([...(genM ? genM[1] : "").matchAll(/coalesce\((\w+) (>=|>) (\d+), false\)/g)].map(m => `${m[1]}.${opSql[m[2]]}.${m[3]}`));
const pyM = tiers.match(/PLAYED = \("or=\(([^"]*)"\s*\n\s*"([^"]*)\)"\)/);
const fromPy = new Set(pyM ? (pyM[1] + pyM[2]).split(",").map(s => s.trim()).filter(Boolean) : []);
ok(`played has PLAYED's four conditions (${[...fromSql].join(" | ")})`,
  fromSql.size === 4 && fromPy.size === 4 && [...fromSql].every(c => fromPy.has(c)));

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
