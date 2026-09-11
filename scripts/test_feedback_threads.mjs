// test_feedback_threads.mjs — guards feedback replies (migration 138).
//
//     node scripts/test_feedback_threads.mjs
//
// Extracts the pure helpers out of Index.html so they can't drift from what
// ships, then checks that the client and the migration agree with each other.
//
// Every way this breaks is silent. A reply token swept by the aux-cache wipe
// strands an anonymous sender's conversation with no error anywhere. A notice
// that re-shows for a reply already dismissed is nagging; one that never shows
// is a reply nobody reads. And an RPC the client calls but the migration never
// defines, or never grants, reads to the user exactly like "no replies yet".
import { readFileSync } from "node:fs";

const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8").replace(/\r\n/g, "\n");
const src = read("../Index.html");
const sql = read("../supabase/138_feedback_threads.sql");
const sql106 = read("../supabase/106_feedback.sql");
const NL = "\n";

function grab(start, end) {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
}
function grabLine(prefix) {
  const line = src.split(NL).find((l) => l.startsWith(prefix));
  if (!line) throw new Error("missing line: " + prefix);
  return line;
}

const moduleSrc = [
  grabLine("const FEEDBACK_TOKENS_KEY = "),
  grabLine("const FEEDBACK_NOTICE_KEY = "),
  grabLine("const FEEDBACK_TOKEN_RE = "),
  grab("const normalizeFeedbackTokens = (v) =>", "  : [];"),
  grab("const feedbackThreadsUnavailable = (err) => {", NL + "};"),
  grabLine("const feedbackTime = "),
  grab("const feedbackThreadMessages = (t) => [", NL + "];"),
  grab("const feedbackReplyState = (t) => {", NL + "};"),
  grab("const pickUnreadFeedbackThread = (threads) => {", NL + "};"),
  grab("const feedbackNoticeVisible = (state, dismissed) => {", NL + "};"),
  grab("const AUX_EVICTABLE_PREFIXES = [", NL + "];"),
  grab("const isPriceDerivedAuxKey = (k) =>", "k.startsWith(p));"),
  "export {FEEDBACK_TOKENS_KEY, FEEDBACK_NOTICE_KEY, FEEDBACK_TOKEN_RE, normalizeFeedbackTokens,",
  "  feedbackThreadsUnavailable, feedbackTime, feedbackThreadMessages, feedbackReplyState,",
  "  pickUnreadFeedbackThread, feedbackNoticeVisible, isPriceDerivedAuxKey};",
].join(NL);

const m = await import("data:text/javascript," + encodeURIComponent(moduleSrc));

let failed = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(
    (ok ? "PASS  " : "FAIL  ") + name +
    (ok ? "" : "  (got " + JSON.stringify(got) + ", want " + JSON.stringify(want) + ")"),
  );
};
const ok = (name, cond) => check(name, !!cond, true);

// ── tokens ────────────────────────────────────────────────────────────────
const tok = (c) => c.repeat(22);
check("tokens: a non-array reads as none", m.normalizeFeedbackTokens({a: 1}), []);
check("tokens: junk is dropped, real ones kept",
  m.normalizeFeedbackTokens(["short", 42, null, "has space in it 1234567", tok("a"), "AbC-dEf_0123456789xyZQ"]),
  [tok("a"), "AbC-dEf_0123456789xyZQ"]);
check("tokens: duplicates collapse", m.normalizeFeedbackTokens([tok("b"), tok("b"), tok("c")]), [tok("b"), tok("c")]);
{
  const many = Array.from({length: 130}, (_, i) => ("t" + String(i).padStart(3, "0")).repeat(6));
  const kept = m.normalizeFeedbackTokens(many);
  check("tokens: capped at 100", kept.length, 100);
  check("tokens: the cap keeps the NEWEST", kept[kept.length - 1], many[many.length - 1]);
}
// A genTradeToken token is 22 base64url chars; the server's shape check must accept it.
ok("tokens: a trade-link-shaped token matches", m.FEEDBACK_TOKEN_RE.test("q9Z_-x0123456789ABCDEFg"));
ok("tokens: a 21-char token does not", !m.FEEDBACK_TOKEN_RE.test("x".repeat(21)));

// ── the aux-cache wipe must never reach them ─────────────────────────────
ok("the aux wipe never sweeps reply tokens", !m.isPriceDerivedAuxKey(m.FEEDBACK_TOKENS_KEY));
ok("the aux wipe never sweeps the notice dismissal", !m.isPriceDerivedAuxKey(m.FEEDBACK_NOTICE_KEY));
ok("both keys live under packsink:feedback:", m.FEEDBACK_TOKENS_KEY.startsWith("packsink:feedback:")
  && m.FEEDBACK_NOTICE_KEY.startsWith("packsink:feedback:"));

// ── pre-138 detection ─────────────────────────────────────────────────────
ok("unavailable: PGRST202", m.feedbackThreadsUnavailable({code: "PGRST202"}));
ok("unavailable: 42883 undefined function", m.feedbackThreadsUnavailable({code: "42883"}));
ok("unavailable: the schema-cache message alone",
  m.feedbackThreadsUnavailable({message: "Could not find the function public.get_my_feedback(p_tokens) in the schema cache"}));
ok("available: a rate limit is a real error", !m.feedbackThreadsUnavailable({code: "P0001",
  message: "rate limited: too much feedback submitted — try again in an hour"}));
ok("available: 'feedback not found' is a real error", !m.feedbackThreadsUnavailable({code: "P0001", message: "feedback not found"}));
ok("available: no error at all", !m.feedbackThreadsUnavailable(null));

// ── time ──────────────────────────────────────────────────────────────────
check("time: microseconds parse to the same instant as milliseconds",
  m.feedbackTime("2026-09-10T21:14:09.123456+00:00"), Date.parse("2026-09-10T21:14:09.123+00:00"));
ok("time: whole seconds parse", Number.isFinite(m.feedbackTime("2026-09-10T21:14:09+00:00")));
ok("time: empty is NaN", Number.isNaN(m.feedbackTime(null)));

// ── the conversation ─────────────────────────────────────────────────────
const T0 = "2026-09-01T10:00:00.000001+00:00", T1 = "2026-09-02T10:00:00+00:00", T2 = "2026-09-03T10:00:00+00:00";
{
  const t = {id: "f1", created_at: T0, comment: "the Screener crashed",
    messages: [{id: "m1", created_at: T1, from_admin: true, body: "fixed"}, {id: "m2", created_at: T2, from_admin: false, body: "thanks"}]};
  check("thread: the original note is message one, then the rest in order",
    m.feedbackThreadMessages(t).map((x) => [x.from_admin, x.body]),
    [[false, "the Screener crashed"], [true, "fixed"], [false, "thanks"]]);
  check("thread: no messages is just the note", m.feedbackThreadMessages({id: "f2", created_at: T0, comment: "hi"}).length, 1);
}

check("state: no reply yet", m.feedbackReplyState({created_at: T0, last_user_at: T0, last_admin_at: null}), "none");
check("state: we spoke last", m.feedbackReplyState({last_user_at: T0, last_admin_at: T1}), "replied");
check("state: they answered our reply", m.feedbackReplyState({last_user_at: T2, last_admin_at: T1}), "followup");
check("state: a tie reads as replied", m.feedbackReplyState({last_user_at: T1, last_admin_at: T1}), "replied");

check("open on: nothing unread", m.pickUnreadFeedbackThread([{id: "a", unread: false, last_admin_at: T2}]), null);
check("open on: the newest unread reply, not the newest thread",
  m.pickUnreadFeedbackThread([
    {id: "read-newest", unread: false, last_admin_at: "2026-09-09T00:00:00+00:00"},
    {id: "unread-old", unread: true, last_admin_at: T1},
    {id: "unread-new", unread: true, last_admin_at: T2},
  ]), "unread-new");
check("open on: tolerates a missing list", m.pickUnreadFeedbackThread(null), null);

// ── the corner notice ────────────────────────────────────────────────────
ok("notice: hidden with nothing unread", !m.feedbackNoticeVisible({unread: 0, latest: T2}, null));
ok("notice: shows for a reply never dismissed", m.feedbackNoticeVisible({unread: 1, latest: T2}, null));
ok("notice: stays dismissed for that same reply", !m.feedbackNoticeVisible({unread: 1, latest: T2}, T2));
ok("notice: comes back for a NEWER reply", m.feedbackNoticeVisible({unread: 2, latest: T2}, T1));
// Two unread, notice dismissed at the newest, then the newest is read: the
// latest unread is now the older one, and it must not resurrect the notice.
ok("notice: reading the newer of two can't resurrect it", !m.feedbackNoticeVisible({unread: 1, latest: T1}, T2));
ok("notice: microsecond and millisecond spellings of one instant are equal",
  !m.feedbackNoticeVisible({unread: 1, latest: "2026-09-10T21:14:09.123456+00:00"}, "2026-09-10T21:14:09.123+00:00"));

// ── wiring the helpers can't see ─────────────────────────────────────────
const modal = grab("const FeedbackModal = ({user, onClose, onSeen})=>{", NL + "};");
ok("a token is minted only for an ANONYMOUS send", modal.includes("(!uid && !unavailable) ? genTradeToken() : null"));
ok("the token is stored only after the send succeeded",
  modal.indexOf("if(token) addFeedbackToken(token);") > modal.indexOf('if(error){ setErr(error.message'));
ok("a pre-138 database gets the send again, without the token", modal.includes("delete args.p_reply_token; token = null;"));
ok("marking read passes the reply that was on screen", modal.includes("p_until: openThread.last_admin_at"));
ok("the corner notice never sits over an open box",
  src.includes("feedbackNoticeVisible(feedbackUnread, feedbackNoticeDismissed) && !feedbackOpen"));
ok("the footer is told both counts",
  src.includes("feedbackUnread=${feedbackUnread.unread}") && src.includes("feedbackAdminUnread=${feedbackAdminUnread}"));

// ── the client and the migration agree ──────────────────────────────────
const created = new Map();  // name → {params, body}
for (const mm of sql.matchAll(/create or replace function public\.(\w+)\(([\s\S]*?)\)\s*\nreturns[\s\S]*?\n\$\$;/g)) {
  created.set(mm[1], {params: mm[2], block: mm[0]});
}
const defined106 = new Set([...sql106.matchAll(/create or replace function public\.(\w+)\(/g)].map((x) => x[1]));
const called = new Set([...src.matchAll(/sbClient\.rpc\("(\w*feedback\w*)"/g)].map((x) => x[1]));
check("the client calls the expected feedback RPCs", [...called].sort(), [
  "admin_reply_feedback", "delete_feedback", "get_feedback", "get_feedback_admin_unread", "get_feedback_threads",
  "get_my_feedback", "get_my_feedback_unread", "mark_feedback_seen_admin", "mark_my_feedback_seen",
  "reply_my_feedback", "set_feedback_resolved", "submit_feedback",
]);
for (const name of called) {
  ok("rpc exists in 138 or 106: " + name, created.has(name) || defined106.has(name));
}

// The signature a grant names has to be the one the function was declared with,
// or the migration errors half-way through the paste.
const sigOf = (params) => params.split(",").map((p) => p.trim()).filter(Boolean)
  .map((p) => p.replace(/\s+default\s+[\s\S]*$/i, "").split(/\s+/).slice(1).join(" ")).join(", ");
const ANON = ["submit_feedback", "get_my_feedback", "get_my_feedback_unread", "reply_my_feedback", "mark_my_feedback_seen"];
const ADMIN = ["get_feedback_threads", "get_feedback_admin_unread", "admin_reply_feedback", "mark_feedback_seen_admin"];
const HELPERS = ["_feedback_tokens", "_feedback_rate_limit"];
check("138 defines exactly the expected functions", [...created.keys()].sort(), [...ANON, ...ADMIN, ...HELPERS].sort());
for (const [name, {params, block}] of created) {
  const sig = `public.${name}(${sigOf(params)})`;
  ok("search_path pinned: " + name, /\nset search_path/.test(block));
  ok("revoked from public, anon, authenticated: " + name,
    sql.includes(`revoke all on function ${sig}`) &&
    new RegExp(`revoke all on function ${sig.replace(/[()[\]]/g, "\\$&")}\\s+from public, anon, authenticated;`).test(sql));
  const grant = sql.split(NL).find((l) => l.startsWith(`grant execute on function ${sig}`));
  if (ANON.includes(name)) {
    ok("granted to anon + authenticated: " + name, grant && /to anon, authenticated;$/.test(grant));
    ok("security definer: " + name, /\nsecurity definer\n/.test(block));
  } else if (ADMIN.includes(name)) {
    ok("granted to authenticated only: " + name, grant && /to authenticated;$/.test(grant));
    ok("gated on is_graded_admin: " + name, block.includes("if not public.is_graded_admin() then raise exception 'not authorized'"));
    ok("security definer: " + name, /\nsecurity definer\n/.test(block));
  } else {
    ok("never granted to anyone: " + name, !grant);
    ok("not security definer: " + name, !/security definer/.test(block));
  }
}

// One token shape, client and server, everywhere the server checks it.
const shapes = [...sql.matchAll(/!?~ '([^']+)'/g)].map((x) => x[1]);
check("the server checks the token shape twice (helper + submit)", shapes.length, 2);
ok("every server-side shape check matches the client's", shapes.every((s) => s === m.FEEDBACK_TOKEN_RE.source));

ok("the 3-argument submit_feedback is dropped first",
  sql.indexOf("drop function if exists public.submit_feedback(text, text, text);") > -1 &&
  sql.indexOf("drop function if exists public.submit_feedback(text, text, text);") < sql.indexOf("create or replace function public.submit_feedback("));
ok("follow-ups share submit's rate limit", created.get("reply_my_feedback").block.includes("perform public._feedback_rate_limit();")
  && created.get("submit_feedback").block.includes("perform public._feedback_rate_limit();"));
ok("marking seen never runs ahead of now()", (sql.match(/least\(coalesce\(p_until, now\(\)\), now\(\)\)/g) || []).length === 2);
ok("an admin reply leaves admin_seen_at alone", !created.get("admin_reply_feedback").block.includes("admin_seen_at"));
ok("the sender's reads never return the email, agent or token",
  !/'(user_email|user_agent|reply_token)'/.test(created.get("get_my_feedback").block));
ok("service_role can read follow-ups", sql.includes("grant select on public.feedback_messages to service_role;"));
ok("ends by reloading PostgREST's schema", sql.trimEnd().endsWith("notify pgrst, 'reload schema';"));

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
