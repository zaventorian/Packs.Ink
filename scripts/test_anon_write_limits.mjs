// test_anon_write_limits.mjs - one abuser cannot use up the anonymous write
// limits for everybody else.
//
//     node scripts/test_anon_write_limits.mjs
//
// create_trade and the feedback box (submit_feedback / reply_my_feedback, via
// _feedback_rate_limit) carry a per-bucket limit and a global backstop. Until
// migration 190 the backstop was one pool for every caller, so 10 addresses
// (12 for feedback) filled it with writes the per-address limit allowed and
// locked out the whole site, signed-in users included, for the rest of every
// hour. Reads the NEWEST migration that defines each function, so a later
// re-definition that quietly drops a guard fails here.
import { readFileSync, readdirSync } from "node:fs";

const dir = new URL("../supabase/", import.meta.url);
const files = readdirSync(dir).filter(f => /^\d+_.*\.sql$/.test(f))
  .sort((a, b) => parseInt(a) - parseInt(b) || a.localeCompare(b));
// The body of the last `create or replace function <name>(` across the
// migrations, up to its closing $$.
function latest(name){
  let best = null;
  for(const f of files){
    const s = readFileSync(new URL(f, dir), "utf8").replace(/\r\n/g, "\n");
    const re = new RegExp("create or replace function public\\." + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\(", "gi");
    let m;
    while((m = re.exec(s))){
      const open = s.indexOf("$$", m.index);
      const close = s.indexOf("$$", open + 2);
      best = {file: f, body: s.slice(m.index, close + 2)};
    }
  }
  return best || {file: "no definition", body: ""};
}

let fails = 0;
const ok = (name, cond) => { if(!cond) fails++; console.log(`${cond ? "  ok  " : "  FAIL"} ${name}`); };

const bucket = latest("_rate_bucket");
ok(`_rate_bucket (${bucket.file}) keys a signed-in caller on the account`,
  /auth\.uid\(\)/.test(bucket.body) && /'\|u:' \|\| v_uid::text/.test(bucket.body));
ok("_rate_bucket folds IPv6 to its /64", /family\(v_ip::inet\) = 6/.test(bucket.body) && /set_masklen\(v_ip::inet, 64\)/.test(bucket.body));
ok("_rate_bucket reads the address through _client_ip() (cf-connecting-ip)", /public\._client_ip\(\)/.test(bucket.body));
ok("_rate_bucket hashes an IPv4 address as before (scope || '|' || ip)", /p_scope \|\| '\|' \|\| coalesce\(v_net, 'unknown'\)/.test(bucket.body));
const ip = latest("_client_ip");
ok(`_client_ip (${ip.file}) prefers cf-connecting-ip`, ip.body.indexOf("cf-connecting-ip") > 0
  && ip.body.indexOf("cf-connecting-ip") < ip.body.indexOf("x-forwarded-for"));

for(const [fn, scope, per, soft, hard, eventsTable] of [
  ["create_trade", "packsink-trade", 30, 150, 300, "trade_create_events"],
  ["_feedback_rate_limit", "packsink-feedback", 10, 60, 120, "feedback_submit_events"],
]){
  const {file, body} = latest(fn);
  ok(`${fn} (${file}) buckets through _rate_bucket('${scope}')`, body.includes(`public._rate_bucket('${scope}')`));
  ok(`${fn}: per-bucket limit ${per}`, new RegExp(`if v_recent >= ${per} then`).test(body));
  ok(`${fn}: the global count is per pool (signed in vs anonymous)`,
    /where signed_in = v_signed and created_at > now\(\) - interval '1 hour'/.test(body));
  ok(`${fn}: fair share past ${soft}, hard cap ${hard}`,
    new RegExp(`v_total >= ${hard} or \\(v_total >= ${soft} and v_recent >= 2\\)`).test(body));
  const ins = body.indexOf(`insert into public.${eventsTable} (ip_hash, signed_in) values (v_hash, v_signed)`);
  const lastRaise = body.lastIndexOf("raise exception 'rate limited");
  ok(`${fn}: records the pool, and only after every check passed`, ins > 0 && lastRaise > 0 && ins > lastRaise);
  ok(`${fn}: the user-facing message is unchanged`,
    (body.match(/raise exception 'rate limited: (too many trade links created|too much feedback submitted) % try again in an hour', chr\(8212\);/g) || []).length === 2);
}
// The functions that call the limiter must still call it.
for(const fn of ["submit_feedback", "reply_my_feedback"]){
  const {file, body} = latest(fn);
  ok(`${fn} (${file}) still goes through _feedback_rate_limit()`, body.includes("perform public._feedback_rate_limit();"));
}

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
