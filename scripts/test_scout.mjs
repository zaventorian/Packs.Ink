// test_scout.mjs — guards the team scouting feature (migration 143).
//
//     node scripts/test_scout.mjs
//
// Three classes of silent failure live here, and none of them raise anything a
// reader would see:
//
//   1. ACCESS. Scouting notes are the team's own intel. A gate that quietly
//      widens — a surface re-gated on canViewStore (the broader store-report
//      allowlist), or an RPC that forgets its can_scout() check — shows one
//      team's notes to another with no error anywhere.
//   2. SCOPE. Every read and write is meant to be confined to stores the
//      Chicagoland Elo board tracks. Drop the `tracked` test and pasting an
//      event id starts logging notes on shops in another state.
//   3. THE TAB ROW. The reported bug was the Elo strip WRAPPING on a phone and
//      orphaning the fifth tab, which happened to be Scout. A `flex-wrap:wrap`
//      reintroduced later brings the bug back and nothing fails.
//
// Plus the usual migration/client contract: an RPC the client calls that the
// migration never defines (or never grants) reads to the user exactly like
// "scouting isn't set up yet".
import { readFileSync } from "node:fs";

const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8").replace(/\r\n/g, "\n");
const src = read("../Index.html");
const css = read("../styles.css");
const sql = read("../supabase/143_scout_team.sql");
const sql144 = read("../supabase/144_scout_off_roster.sql");
const sql147 = read("../supabase/147_scout_window_24h.sql");
const fn = read("../supabase/functions/refresh-elo-rosters/index.ts");
const NL = "\n";

function grab(start, end) {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
}

const moduleSrc = [
  grab("const scoutErrText = (e) => {", NL + "};"),
  grab("const scoutShortDate = (iso, tz) => {", NL + "};"),
  grab("const SCOUT_LIVE_HOURS = 24;",
       "return `Started ${Math.floor(mins / 60)}h ago`;" + NL + "};"),
  "export {scoutErrText, scoutShortDate, SCOUT_LIVE_HOURS, scoutStartedAgo};",
].join(NL);
const m = await import("data:text/javascript," + encodeURIComponent(moduleSrc));

let failed = 0;
const check = (name, got, want) => {
  const pass = JSON.stringify(got) === JSON.stringify(want);
  if (!pass) failed++;
  console.log((pass ? "PASS  " : "FAIL  ") + name +
    (pass ? "" : "  (got " + JSON.stringify(got) + ", want " + JSON.stringify(want) + ")"));
};
const ok = (name, cond) => check(name, !!cond, true);

// ── error copy ────────────────────────────────────────────────────────────
// A pre-143 database and a real refusal are different situations and must not
// read the same: one is a deploy step, the other is "you aren't on the team".
ok("pre-143 reads as a deploy step",
  /migration 143/.test(m.scoutErrText({code: "PGRST202", message: 'Could not find the function public.get_scout_event'})));
ok("a refusal reads as team-only",
  /team-only/.test(m.scoutErrText({message: "not authorized"})));
ok("a postgres permission denial reads as team-only too",
  /team-only/.test(m.scoutErrText("permission denied for function get_roster_scout")));
ok("an out-of-scope event says so",
  /store we track/i.test(m.scoutErrText({message: "event 12345 is not one we scout"})));
ok("a plain string error survives", m.scoutErrText("boom") === "boom");

// The reminder shape Zaven asked for is "9/12 <store> <deck>", so the date has
// to render month/day, not an ISO prefix.
check("history dates read as 9/12", m.scoutShortDate("2026-09-12T18:00:00Z", "UTC"), "9/12");
check("a missing date renders nothing", m.scoutShortDate(null), "");
// Two "9/12"s a year apart would read as a duplicate entry, so an older season
// carries its year — and the current one does not, or every row pays for it.
const slashes = (x) => (String(x).match(/\//g) || []).length;
check("a previous season carries its year", slashes(m.scoutShortDate("2025-09-12T18:00:00Z", "UTC")), 2);
check("this season does not", slashes(m.scoutShortDate(new Date().toISOString(), "UTC")), 1);

// ── 1. ACCESS ─────────────────────────────────────────────────────────────
const created = new Map();
{
  const re = /create (?:or replace )?function public\.([a-z_0-9]+)\(([^)]*)\)([\s\S]*?)\n\$\$;/g;
  let mm;
  while ((mm = re.exec(sql))) created.set(mm[1], {args: mm[2], body: mm[3]});
}
ok("143 defines can_scout", created.has("can_scout"));

// Every scout RPC the client calls must exist in 143 and be granted.
const clientRpcs = [...src.matchAll(/sbClient\.rpc\("([a-z_0-9]+)"/g)].map((x) => x[1]);
const scoutRpcs = ["can_scout", "get_scout_event", "save_scout_note", "get_scout_player",
  "scout_members_list", "scout_member_add", "scout_member_remove"];
for (const name of scoutRpcs) {
  ok(`client calls ${name}`, clientRpcs.includes(name));
  ok(`143 defines ${name}`, created.has(name));
  ok(`${name} is granted to authenticated`,
    new RegExp(`grant execute on function public\\.${name}\\(`).test(sql));
  ok(`${name} is revoked from anon`,
    new RegExp(`revoke all on function public\\.${name}\\([^)]*\\)\\s+from public, anon;`).test(sql));
}

// Every scout RPC gates itself. The client's ScoutContext only decides what to
// OFFER — it is not a security boundary, and must never be treated as one.
for (const name of ["get_scout_event", "save_scout_note", "get_scout_player"]) {
  ok(`${name} checks can_scout() itself`,
    /if not public\.can_scout\(\) then\s*\n\s*raise exception 'not authorized';/.test(created.get(name).body));
}
for (const name of ["scout_members_list", "scout_member_add", "scout_member_remove"]) {
  ok(`${name} is admin-only`, created.get(name).body.includes("is_tournament_admin"));
}

// The tables are definer-only: RLS on, no policies. A policy here would expose
// one team's notes through PostgREST directly, bypassing every check above.
for (const t of ["scout_notes", "scout_members"]) {
  ok(`${t} has RLS on`, sql.includes(`alter table public.${t} enable row level security;`));
  ok(`${t} has no RLS policy`, !new RegExp(`create policy[^;]*on public\\.${t}`).test(sql));
  ok(`${t} is not granted to anon or authenticated`,
    !new RegExp(`grant [^;]*on public\\.${t} to [^;]*(anon|authenticated)`).test(sql));
}

// ⚠ The scout surfaces are gated on canScout, NEVER on canViewStore — those are
// two different allowlists and the store report's is the wider one.
ok("the Scout tab renders on canScout", /\$\{tab==="scout" && canScout &&/.test(src));
ok("the Scout tab button renders on canScout", /\$\{canScout && html`<button class=\$\{"elo-tab-scout"/.test(src));
ok("the scout modal renders on canScout", /\$\{scoutEvent && canScout && html`<\$\{ScoutEventModal\}/.test(src));
ok("the calendar's Scout tab renders on canScout", /const canScout = useContext\(ScoutContext\);\n  const tracked = useTrackedStoreIds\(canScout\);/.test(src));
ok("no scout surface is gated on canViewStore",
  !/(scout|Scout)[^\n]*\bcanViewStore\b[^\n]*ScoutEvent/.test(src));

// can_view_store_report is deliberately untouched — the store report keeps its
// own, wider gate.
ok("143 never redefines can_view_store_report",
  !/create (or replace )?function public\.can_view_store_report/.test(sql));

// ── 2. SCOPE ──────────────────────────────────────────────────────────────
ok("scout_event_meta reports whether the store is tracked",
  /exists \(select 1 from public\.elo_tracked_stores t where t\.store_id = s\.store_id\)/.test(sql));
ok("get_scout_event refuses an untracked store",
  /if not v_meta\.tracked then[\s\S]{0,200}untracked_store/.test(created.get("get_scout_event").body));
ok("save_scout_note refuses an untracked store",
  /if v_meta\.event_id is null or not v_meta\.tracked then[\s\S]{0,120}raise exception/.test(created.get("save_scout_note").body));
ok("the edge function refuses an untracked store for a single event",
  /meta\.tracked !== true/.test(fn));
ok("the edge function resolves a single event through scout_event_meta",
  /rpc\("scout_event_meta", \{ p_event_id: onlyEventId \}\)/.test(fn));
// ⚠ …with its SERVICE key, and service_role does NOT inherit the `authenticated`
// grant. Miss this and the per-event refresh fails with "permission denied for
// function scout_event_meta" — the matview-grant trap, in function form.
ok("scout_event_meta is executable by service_role",
  /grant execute on function public\.scout_event_meta\(bigint\) to service_role;/.test(sql));
ok("the edge function accepts either credential",
  /gate\("can_view_store_report"\), gate\("can_scout"\)/.test(fn));

// One row per (event, player): a deck is a fact about the table, not an opinion,
// so a teammate amending yours is the wanted behaviour. Losing the constraint
// would silently start stacking duplicate rows and the panel would show one at
// random.
ok("one note per player per event",
  /constraint scout_notes_one_per_player unique \(event_id, player_key\)/.test(sql));
ok("saving upserts onto that key",
  /on conflict \(event_id, player_key\) do update/.test(created.get("save_scout_note").body));

// ⚠ The event label is denormalised on purpose — lorcana_events prunes what has
// already happened, and a note you read next month must still say where it came
// from. Normalising these away is the tempting cleanup that breaks the feature.
for (const col of ["event_name", "event_date", "store_name"]) {
  ok(`scout_notes stores ${col} on the row`, new RegExp(`\\n  ${col} +\\w`).test(sql));
}
ok("the history read touches only scout_notes",
  !/from public\.(lorcana_events|set_championships)/.test(created.get("get_scout_player").body));

// Emptying both fields DELETES rather than storing two blanks — an empty note
// would still count toward "you have seen this player before", which is the one
// thing the prior-notes badge must not lie about.
ok("clearing both fields deletes the row",
  /if v_deck is null and v_note is null then\s*\n\s*delete from public\.scout_notes/.test(created.get("save_scout_note").body));

// The player key: RPH's account id when there is one, the lowercased name when
// there is not. Computed SERVER-side in both directions so it cannot drift.
ok("scout_player_key prefers the RPH account id",
  /when p_rph_user_id is not null then 'rph:' \|\| p_rph_user_id::text/.test(sql));
ok("scout_player_key falls back to a folded name",
  /else 'name:' \|\| lower\(btrim\(coalesce\(p_identifier, ''\)\)\)/.test(sql));
ok("the client never computes a player key", !/['"]rph:['"]\s*\+/.test(src));

// ── 3. THE TAB ROW ────────────────────────────────────────────────────────
const block = (sel) => {
  const i = css.indexOf(sel + "{");
  if (i < 0) throw new Error("missing CSS rule: " + sel);
  return css.slice(i, css.indexOf("}", i));
};
// ⚠ This is the reported bug. Five tabs wrapped to a third row on a narrow
// phone and Scout was the one that fell off it.
ok("the Elo tab row never wraps", /flex-wrap:nowrap/.test(block(".elo-innertabs")));
ok("the Elo tab row scrolls instead", /overflow-x:auto/.test(block(".elo-innertabs")));
ok("its trailing gutter is on a CHILD (container padding is dropped at the end of a scroll range)",
  css.includes(".elo-innertabs::after{content:\"\";flex:0 0 6px;}"));
ok("the active Elo tab is scrolled into view",
  /tabsRef\.current\.querySelector\("button\.active"\)[\s\S]{0,200}scrollIntoView/.test(src));
ok("the active Analytics tab is scrolled into view",
  /subtabsRef\.current\.querySelector\("\.market-subtab\.active"\)[\s\S]{0,200}scrollIntoView/.test(src));
ok("the Analytics strip still scrolls on a phone",
  /@media \(max-width:640px\)\{\s*\n\s*\.market-subtabs\{flex-wrap:nowrap;overflow-x:auto/.test(css));

// Renames Zaven asked for — pinned because the tab label is the only place the
// distinction between "results" and "status" is made.
ok("Tournaments reads Tournament Results", src.includes(">Tournament Results</button>"));
ok("Stores reads Store Status", src.includes(">Store Status</button>"));

// ── the rest of the contract ──────────────────────────────────────────────
ok("the roster FK to set_championships is dropped (a league night can carry a roster)",
  /alter table public\.elo_event_roster drop constraint if exists elo_event_roster_event_id_fkey;/.test(sql));
ok("get_roster_scout LEFT JOINs the roster, so an unpulled event is still listed",
  /left join public\.elo_event_roster r on r\.event_id = sc\.event_id/.test(created.get("get_roster_scout").body));
ok("get_roster_scout accepts a scout as well as a report viewer",
  /public\.can_view_store_report\(\) or public\.can_scout\(\)/.test(created.get("get_roster_scout").body));
ok("every definer function pins search_path",
  [...created.values()].every((f) => /set search_path/.test(f.body) || /search_path to/.test(f.body)));
ok("ends by reloading PostgREST's schema", sql.trimEnd().endsWith("notify pgrst, 'reload schema';"));

// ── 144: a note is never invisible on its own event ───────────────────────
// ⚠ The roster scrape is delete-then-insert, so a dropped registration removes
// the member row. 143 listed the roster and nothing else, which meant every note
// written about that player STOPPED RENDERING on the event it described — with
// the row still in the table and still in their history. No error, nothing to
// notice. The union is the fix; losing it brings the silence back.
ok("144 re-creates get_scout_event",
  /create or replace function public\.get_scout_event\(p_event_id bigint\)/.test(sql144));
ok("the panel unions the roster with this event's notes",
  /mem as \(\s*\n\s*select \* from roster union all select \* from extra/.test(sql144));
ok("the off-roster half is exactly the notes with no roster row",
  /from public\.scout_notes n\s*\n\s*where n\.event_id = p_event_id\s*\n\s*and not exists \(select 1 from roster r where r\.player_key = n\.player_key\)/.test(sql144));
ok("each player says which side it came from", /'off_roster',\s+r\.off_roster/.test(sql144));
// "Signed up" is RPH's number. Folding our own hand-added rows into it would
// quietly restate a fact about their roster as something it is not.
ok("Signed up still counts only the roster",
  /'n_signed_up', count\(\*\) filter \(where not r\.off_roster\)/.test(sql144));
ok("off-roster players are counted separately",
  /'n_off_roster',count\(\*\) filter \(where r\.off_roster\)/.test(sql144));
ok("144 keeps the scout gate", /if not public\.can_scout\(\) then/.test(sql144));
ok("144 keeps the tracked-store scope", /untracked_store/.test(sql144));
ok("144 re-grants get_scout_event after replacing it",
  /grant execute on function public\.get_scout_event\(bigint\) to authenticated;/.test(sql144));
ok("144 ends by reloading PostgREST's schema", sql144.trimEnd().endsWith("notify pgrst, 'reload schema';"));

// The client can add a player RPH never recorded; the key is the folded name,
// which is what scout_player_key produces when there is no RPH id.
ok("the panel can add an off-roster player", /const addPlayer = async \(\) => \{/.test(src));
ok("adding one passes no RPH id", /p_player_name: nm, p_rph_user_id: null/.test(src));
ok("an off-roster row is marked, not hidden", /class="scout-offroster"/.test(src));

// ⚠ The refresh toast must not report a site-wide total as this event's count.
// An edge function deployed before 143 ignores {event_id} and refreshes every
// tracked SC; it echoes event_id back only when it understood us.
ok("the refresh distinguishes per-event from refresh-everything",
  /const perEvent = d && d\.event_id != null;/.test(src));
ok("the edge function echoes the event id back", /event_id: onlyEventId \?\? undefined,/.test(fn));
ok("an un-redeployed function says so", /Redeploy refresh-elo-rosters/.test(src));

// Removing a member added by user_id — 143 could only remove by email, so that
// row carried a button that silently did nothing.
ok("144 can remove a member by id",
  /create or replace function public\.scout_member_delete\(p_id uuid\)/.test(sql144));
ok("scout_member_delete is admin-only and granted",
  /is_tournament_admin/.test(sql144) &&
  /grant execute on function public\.scout_member_delete\(uuid\) to authenticated;/.test(sql144));
ok("the client falls back to removing by email pre-144",
  /scout_member_remove", \{p_email: m2\.email\}/.test(src));

// ── the sheet ─────────────────────────────────────────────────────────────
// Type, Tab, saved. No Edit/Save/Cancel — logging 24 people one modal at a time
// is what makes a scouting tool go unused.
ok("a cell commits on blur", /const commit = \(\) => \{[\s\S]{0,200}onCommit\(v\);/.test(src));
ok("an unchanged cell writes nothing", /if\(v === base\.current\) return;/.test(src));
ok("there is no Save button left in the sheet", !/ScoutNoteEditor|scout-btn--log/.test(src));

// ⚠ save_scout_note writes BOTH fields, and each save triggers a reload. Tab from
// Deck into Notes fast enough and the second save is built from the pre-save row,
// sending the OLD deck back and undoing the edit. Verified against a 600ms server:
// without `inflight` the second write carries deck:"".
ok("a cell edit sends its sibling back", /field === "deck"  \? value :/.test(src));
ok("the in-flight value beats the last loaded row",
  /const inflight = useRef\(new Map\(\)\);/.test(src) &&
  /held\.deck  != null \? held\.deck/.test(src));
ok("and is dropped once its reload lands", /inflight\.current\.delete\(p\.player_key\)/.test(src));

// ⚠ There is a GLOBAL button{border;background;padding;border-radius} rule, so
// anything meant to read as plain text in the sheet must unset all of it — this
// is exactly what broke when the old card-row styles were swapped out.
ok("the name and Elo buttons reset the global button chrome",
  /\.scout-namebtn,\.scout-elobtn\{background:none;border:none;padding:0/.test(css));
// The sheet SCROLLS sideways on a phone rather than collapsing to stacked cards
// (the site's usual mobile-table pattern) — collapsing puts you back at one
// player per screenful, which is the thing the sheet exists to fix.
ok("the sheet scrolls rather than collapsing", /\.scout-sheet-wrap\{overflow-x:auto/.test(css));
ok("the player column pins only where it scrolls",
  /@media \(max-width:760px\)\{\s*\n\s*\.scout-sheet \.ss-name\{position:sticky/.test(css));

// The event row IS the way in now — no intermediate expand, no separate button.
ok("the Scout tab's event row opens the sheet",
  /class="elo-scout-ev-row" onClick=\$\{\(\)=>onOpenScout && onOpenScout\(\{/.test(src));
ok("the old inline expand is gone", !/elo-scout-ev-roster|toggleEvent|openEvents/.test(src));

// One master refresh, in the Scout tab where you look for it.
ok("the master refresh lives in the Scout tab", /const refreshAll = async \(\) => \{/.test(src));
ok("it is admin-only", /\$\{isEloAdmin && html`<button class="scout-btn scout-btn--refresh"/.test(src));
ok("it is not duplicated on Upcoming SCs", !/refreshingRosters/.test(src));

// Removed outright — no orphan state, props, RPC args or CSS left behind.
ok("exclude-org is gone from the client", !/excludeOrg|eloExcludeOrg/.test(src));
ok("exclude-org is gone from the styles", !/elo-exclude-toggle|elo-scout-orgtoggle/.test(css));

// ── 147: the slate keeps an event for 24 hours past its start ─────────────
// Reported from the floor 2026-09-12: three 3:00 PM Set Championships were on
// the Scout tab at 2:59 and gone at 3:00. 143 scoped the slate to
// `start_datetime >= now()`, so an event left the list at the exact moment it
// became the one you were standing in — and a sheet is filled in DURING the
// event and finished on the drive home.
const rosterBody = (sqlText) => {
  const a = sqlText.indexOf("create or replace function public.get_roster_scout(");
  if (a < 0) throw new Error("missing get_roster_scout");
  return sqlText.slice(a, sqlText.indexOf(NL + "$$;", a));
};
ok("147 re-creates get_roster_scout", /create or replace function public\.get_roster_scout\(/.test(sql147));
ok("the slate keeps an event for 24 hours past its start",
  /where sc\.start_datetime >= now\(\) - interval '24 hours'/.test(rosterBody(sql147)));
ok("the start-line cutoff is gone", !/start_datetime >= now\(\)\s*$/m.test(rosterBody(sql147)));
// ⚠ The window is the ONLY thing 147 may change. Re-typing a 120-line function
// to move one predicate is exactly how a gate, a join or an aggregate quietly
// goes missing, and every one of those failures is silent: a widened gate shows
// one team's slate to another, a dropped LEFT JOIN hides every event whose
// roster has not been pulled yet.
check("nothing else about 143's body changed",
  rosterBody(sql147).replace(" - interval '24 hours'", ""), rosterBody(sql));
ok("147 keeps the grant it needs",
  /grant execute on function public\.get_roster_scout\(boolean\) to authenticated;/.test(sql147));
ok("147 reloads PostgREST's schema", sql147.trimEnd().endsWith("notify pgrst, 'reload schema';"));

// ⚠ The BULK sweep is deliberately NOT widened to match. It replaces a roster
// delete-then-insert, so pointing the automatic pull at events that have already
// been played risks overwriting the roster of the very sheet somebody is filling
// in. What makes that safe is the PER-EVENT refresh — the ↻ inside the sheet —
// which has never had a date filter and is how you re-pull the event you are
// sitting in. Put one there and the in-room workflow dies with no error.
{
  const i = fn.indexOf("if (onlyEventId != null) {");
  ok("the edge function has a single-event branch", i > 0);
  ok("the per-event refresh is not date-filtered",
    !/start_datetime/.test(fn.slice(i, fn.indexOf("} else {", i))));
}

// The chip that says a row has already begun. Before 147 the slate was all
// future, so the list needed no marker; now it does, or a Sunday-morning tab
// headed "Saturday, Sep 12" reads as stale data rather than as the event you
// were just at.
const ago = (mins) => m.scoutStartedAgo(new Date(Date.now() - mins * 60000).toISOString());
check("an event that has not started carries no chip", ago(-90), null);
check("the first hour just says it started", ago(30), "Started");
check("on the hour it starts counting", ago(60), "Started 1h ago");
check("after that it says how long ago", ago(190), "Started 3h ago");
check("a junk timestamp renders nothing", m.scoutStartedAgo("not a date"), null);
check("a missing timestamp renders nothing", m.scoutStartedAgo(null), null);
// The chip explains a window the database enforces. Two numbers, one fact.
ok("the client's stated window is the one the migration enforces",
  m.SCOUT_LIVE_HOURS === 24 && /interval '24 hours'/.test(sql147));
ok("the Scout row marks an event that has already begun",
  /began=scoutStartedAgo\(ev\.start_datetime\)/.test(src) && /class="elo-scout-began"/.test(src));
// It sits inside the .muted meta line, so it has to take its colour back or the
// one thing separating a live row from a listing is the grey of the address.
ok("the chip is not muted grey", /\.elo-scout-began\{color:var\(--accent\)/.test(css));

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
