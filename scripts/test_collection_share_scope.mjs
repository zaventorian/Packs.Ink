// test_collection_share_scope.mjs - an unlisted collection link opens only the
// sections it was made for.
//
//     node scripts/test_collection_share_scope.mjs
//
// One base token (profiles.collection_share_token) used to open every unlisted
// section, so a Cards link sent last month opened Graded the day Graded went
// unlisted. Migration 192 adds scoped tokens (an HMAC of the scope under the
// base token) that the five read functions accept for their own section only,
// and the share popover hands those out. Every way this breaks is silent:
//
//   1. a reader keeps the bare `collection_share_token = p_token` test, or
//      checks the wrong section - a scoped link opens nothing, or too much;
//   2. the client and the server disagree about how a scope is spelled
//      ("graded+raw" vs "raw+graded") - every multi-section link falls back
//      to the base token, which opens everything again;
//   3. the client keeps an old scope map after the base token rotates - every
//      link it copies is dead.
// Reads the real code out of Index.html and the newest migrations.
import { readFileSync, readdirSync } from "node:fs";

const root = new URL("../", import.meta.url);
const src = readFileSync(new URL("Index.html", root), "utf8").replace(/\r\n/g, "\n");
const dir = new URL("supabase/", root);
const files = readdirSync(dir).filter(f => /^\d+_.*\.sql$/.test(f))
  .sort((a, b) => parseInt(a) - parseInt(b) || a.localeCompare(b));
function latest(name){
  let best = null;
  for(const f of files){
    const s = readFileSync(new URL(f, dir), "utf8").replace(/\r\n/g, "\n").replace(/--[^\n]*/g, "");
    const re = new RegExp("create\\s+(?:or\\s+replace\\s+)?function\\s+public\\." + name + "\\s*\\(", "gi");
    let m;
    while((m = re.exec(s))){
      const open = s.indexOf("$$", m.index), close = s.indexOf("$$", open + 2);
      best = {file: f, body: s.slice(m.index, close + 2)};
    }
  }
  return best || {file: "no definition", body: ""};
}

let fails = 0;
const ok = (name, cond) => { if(!cond) fails++; console.log(`${cond ? "  ok  " : "  FAIL"} ${name}`); };
const grab = (a, b) => { const i = src.indexOf(a); if(i < 0) return ""; const j = src.indexOf(b, i); return j < 0 ? "" : src.slice(i, j + b.length); };

// ---- the client's token picker
const pick = grab("const COLLECTION_SHARE_SECTIONS = [", "\n}");
ok("collectionShareToken is in Index.html", /function collectionShareToken\(profile, keys\)/.test(pick));
let SECTIONS = [], shareToken = () => "";
try { [SECTIONS, shareToken] = new Function(pick + "\nreturn [COLLECTION_SHARE_SECTIONS, collectionShareToken];")(); } catch {}
const prof = {collection_share_token: "BASE", collection_scope_tokens: {
  raw: "R", sealed: "S", graded: "G", "raw+sealed": "RS", "raw+graded": "RG", "sealed+graded": "SG", "raw+sealed+graded": "RSG"}};
ok("one section -> its own token", shareToken(prof, ["graded"]) === "G");
ok("several sections -> the scope in raw, sealed, graded order", shareToken(prof, ["graded", "raw"]) === "RG");
ok("all three -> the all-three scope, not the base token", shareToken(prof, ["sealed", "graded", "raw"]) === "RSG");
ok("no scope map (a database before 192) -> the base token", shareToken({collection_share_token: "BASE"}, ["raw"]) === "BASE");
ok("a scope missing from the map -> the base token", shareToken({...prof, collection_scope_tokens: {raw: "R"}}, ["sealed"]) === "BASE");
ok("no profile -> empty, never 'undefined'", shareToken(null, ["raw"]) === "");

// ---- the panel builds every unlisted link through it
const panel = grab("function CollectionSharingPanel({profile, onChange, onRegenerate}){", "\n}\n");
ok("the panel's unlisted links go through collectionShareToken", /token=\$\{collectionShareToken\(profile, keys\)\}/.test(panel));
ok("the panel never puts the base token in a link itself", !/token=\$\{profile\.collection_share_token/.test(panel));
ok("the main link is scoped to what is unlisted now", /const unlistedUrl = unlistedUrlFor\(unlistedKeys\);/.test(panel));
ok("each row can copy a link to itself alone", /copy\(unlistedUrlFor\(\[s\.key\]\), s\.key\)/.test(panel));

// ---- the scope map follows the base token
const fetches = (src.match(/await fetchCollectionScopeTokens\(\)/g) || []).length;
ok(`scoped tokens are fetched on load, after a visibility change and after regenerate (${fetches})`, fetches === 3);
const regen = grab("const regenerateCollectionShareToken = useCallback(async () => {", "}, [user]);");
ok("regenerate replaces the scope map (null on failure, never the old one)",
  /const scopeTokens = await fetchCollectionScopeTokens\(\);/.test(regen) && /collection_scope_tokens: scopeTokens/.test(regen));
const save = grab("const saveCollectionVisibility = useCallback(async (section, level) => {", "}, [user]);");
ok("a visibility change (which may rotate the base) refreshes it in both branches",
  (save.match(/collection_scope_tokens: scopeTokens/g) || []).length === 2);

// ---- the server: every reader accepts a scoped token for ITS section only
const scopes = [];
for(let m = 1; m < 1 << SECTIONS.length; m++) scopes.push(SECTIONS.filter((_, i) => m & (1 << i)).join("+"));
const sqlScopes = (body) => { const m = body.match(/array\[([^\]]*)\]/); return m ? [...m[1].matchAll(/'([^']*)'/g)].map(x => x[1]).sort() : []; };
for(const fn of ["_collection_token_ok", "get_my_collection_share_tokens"]){
  const {file, body} = latest(fn);
  ok(`${fn} (${file}) knows the seven scopes the client spells`,
    scopes.length === 7 && JSON.stringify(sqlScopes(body)) === JSON.stringify([...scopes].sort()));
}
const tok = latest("_collection_scope_token");
ok(`_collection_scope_token (${tok.file}) is an HMAC under the base token`,
  /extensions\.hmac\(\s*convert_to\('packsink-collection-scope\|' \|\| p_scope, 'UTF8'\),\s*convert_to\(p_base, 'UTF8'\), 'sha256'\)/.test(tok.body));
for(const [fn, sections] of [
  ["get_collection_visibility", ["raw", "sealed", "graded"]],
  ["get_shared_collection_raw", ["raw"]],
  ["get_shared_collection_sealed", ["sealed"]],
  ["get_shared_collection_graded", ["graded"]],
  ["get_shared_collectible_boards", ["sealed"]],
]){
  const {file, body} = latest(fn);
  const used = [...body.matchAll(/_collection_token_ok\(p\.collection_share_token, p_token, '(\w+)'\)/g)].map(m => m[1]);
  ok(`${fn} (${file}) checks the token for ${sections.join(", ")}`, JSON.stringify(used) === JSON.stringify(sections));
  ok(`${fn}: no bare base-token comparison left`, !/collection_share_token\s*=\s*p_token/.test(body));
}

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
