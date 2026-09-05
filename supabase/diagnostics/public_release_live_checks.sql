-- public_release_live_checks.sql
--
-- READ-ONLY live checks for the 2026-09 pre-release schema audit. Paste into
-- the Supabase SQL editor section by section. Nothing here modifies the
-- database except the OPTIONAL, clearly marked, throwaway helper in section 7
-- (create, call once from the browser, drop).
--
-- These answer what the repository cannot:
--   1. Which RLS policies are LIVE on scan_samples and storage.objects
--      (audit H2 / migration 132: is the tester-allowlist write gate from
--      migration 98 still there, or was it dropped outside the repo?).
--   2. The bodies of the SECURITY DEFINER RPCs the client calls that no
--      migration defines (audit H3: get_store_report, get_tracked_store_strength)
--      and the out-of-repo event-trigger helper rls_auto_enable.
--   3. Event triggers present.
--   4. storage.buckets public flags + limits (scan-samples must be private;
--      card-art is expected to be public) and per-bucket size.
--   5. Functions in `public` still EXECUTE-able by PUBLIC (audit L1) with
--      per-role has_function_privilege() — re-run after migration 134 lands.
--   6. Privileges held by anon / authenticated / service_role on public tables,
--      the profiles column list (audit M2), default privileges (audit I6),
--      tables with RLS off, matview grants, market_index population (audit I1).
--   7. request.headers echo helper (audit H1 / migration 133 precondition).
--   8. Data checks: profile avatar_url shapes vs migration 134's CHECK
--      (audit M3), and whether non-allowlisted accounts have any scan_samples
--      rows since the 2026-08-04 public beta (audit H2, empirically — this is
--      the "section 8b" migration 132's header refers to).

-- ══════════════════════════════════════════════════════════════════════════
-- 1. Live RLS policies on scan_samples and storage.objects
--    (polroles = {0} means the policy applies to PUBLIC, i.e. every role).
-- ══════════════════════════════════════════════════════════════════════════
select n.nspname                                   as schema_name,
       c.relname                                   as table_name,
       p.polname                                   as policy_name,
       case p.polcmd when 'r' then 'select' when 'a' then 'insert'
                     when 'w' then 'update' when 'd' then 'delete'
                     else 'all' end                as command,
       p.polpermissive                             as permissive,
       coalesce((select array_agg(r.rolname::text order by r.rolname)
                   from pg_roles r where r.oid = any(p.polroles)),
                array['public'])                   as roles,
       pg_get_expr(p.polqual, p.polrelid)          as using_expr,
       pg_get_expr(p.polwithcheck, p.polrelid)     as with_check_expr
  from pg_policy p
  join pg_class c     on c.oid = p.polrelid
  join pg_namespace n on n.oid = c.relnamespace
 where (n.nspname = 'public'  and c.relname = 'scan_samples')
    or (n.nspname = 'storage' and c.relname = 'objects')
 order by 1, 2, 3;
-- Expected if migration 98 is live as written: scan_samples_insert /
-- scan_samples_update / scan_samples_obj_insert all mention is_scanner_tester().
-- Expected after migration 132: none of them do, and scan_samples_obj_insert
-- carries the `< 3000` rolling-24h count.

-- ══════════════════════════════════════════════════════════════════════════
-- 2. Out-of-repo function bodies (audit H3) — commit whatever this prints.
-- ══════════════════════════════════════════════════════════════════════════
select p.oid::regprocedure       as signature,
       p.prosecdef               as security_definer,
       p.proconfig               as function_settings,   -- expect a search_path pin
       p.proacl                  as acl,                 -- NULL = default (PUBLIC can execute)
       pg_get_functiondef(p.oid) as definition
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = 'public'
   and p.proname in ('get_store_report', 'get_tracked_store_strength', 'rls_auto_enable')
 order by 1;
-- For the two store RPCs the body must contain `can_view_store_report()` (or an
-- equivalent gate) BEFORE reading elo_* / roster data, and proconfig must pin
-- search_path. If either is missing, that is a Critical follow-up.

-- ══════════════════════════════════════════════════════════════════════════
-- 3. Event triggers (rls_auto_enable is expected here; anything else = review).
-- ══════════════════════════════════════════════════════════════════════════
select evtname, evtevent, evtenabled, evtfoid::regproc as trigger_function, evttags
  from pg_event_trigger
 order by 1;

-- ══════════════════════════════════════════════════════════════════════════
-- 4. Storage buckets: public flag, limits, size.
-- ══════════════════════════════════════════════════════════════════════════
select id, name, public, file_size_limit, allowed_mime_types, created_at, updated_at
  from storage.buckets
 order by id;
-- Expected: scan-samples public = false, file_size_limit = 2097152,
-- allowed_mime_types = {image/jpeg}; card-art public = true.

select o.bucket_id,
       count(*)                                                 as objects,
       pg_size_pretty(sum(coalesce((o.metadata->>'size')::bigint, 0))) as total_size,
       min(o.created_at)                                        as oldest,
       max(o.created_at)                                        as newest
  from storage.objects o
 group by o.bucket_id
 order by 1;

-- Per-user object counts in scan-samples (audit M4 — who is close to the
-- 3000 / 24 h cap migration 132 adds, and the all-time top uploaders).
select (storage.foldername(o.name))[1]                          as user_folder,
       count(*)                                                 as objects_all_time,
       count(*) filter (where o.created_at >= now() - interval '24 hours') as objects_24h,
       pg_size_pretty(sum(coalesce((o.metadata->>'size')::bigint, 0))) as total_size
  from storage.objects o
 where o.bucket_id = 'scan-samples'
 group by 1
 order by 2 desc
 limit 25;

-- ══════════════════════════════════════════════════════════════════════════
-- 5. Functions in public still executable by PUBLIC (audit L1).
--    has_function_privilege() does not accept the PUBLIC pseudo-role, so
--    PUBLIC is derived from the ACL (NULL acl = default = PUBLIC may execute;
--    grantee 0 in aclexplode = PUBLIC).
-- ══════════════════════════════════════════════════════════════════════════
select p.oid::regprocedure                                        as signature,
       p.prosecdef                                                as security_definer,
       p.prokind                                                  as kind,   -- f function, p procedure
       (p.proacl is null
        or exists (select 1 from aclexplode(p.proacl) a
                    where a.grantee = 0 and a.privilege_type = 'EXECUTE')) as public_can_execute,
       has_function_privilege('anon',          p.oid, 'EXECUTE')  as anon_exec,
       has_function_privilege('authenticated', p.oid, 'EXECUTE')  as authenticated_exec,
       has_function_privilege('service_role',  p.oid, 'EXECUTE')  as service_role_exec,
       p.proconfig                                                as function_settings,
       p.proacl                                                   as acl
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = 'public'
 order by public_can_execute desc, security_definer desc, 1;
-- Before 134 the audit expects public_can_execute = true for: is_graded_admin,
-- report_graded_sale, admin_update_graded_sale, admin_delete_graded_sale,
-- admin_list_graded_reports, admin_resolve_report, admin_add_private_sale,
-- accept_graded_tos, graded_tos_status, get_roster_scout, can_view_graded_premium,
-- gen_share_token, safe_local_ts, graded_sale_pkey, get_nearby_lorcana_events,
-- get_shared_collection_graded, is_scanner_tester, is_elo_admin,
-- is_tournament_admin, the six trigger functions, plus get_store_report /
-- get_tracked_store_strength if they were created without a revoke.
-- After 134: only functions deliberately granted to anon should show anon_exec.

-- ══════════════════════════════════════════════════════════════════════════
-- 6. Table / column privileges, default privileges, RLS coverage, matviews.
-- ══════════════════════════════════════════════════════════════════════════
-- 6a. What the API roles can do on every public table (audit section 2).
select t.tablename,
       has_table_privilege('anon',          format('public.%I', t.tablename), 'SELECT') as anon_select,
       has_table_privilege('anon',          format('public.%I', t.tablename), 'INSERT') as anon_insert,
       has_table_privilege('authenticated', format('public.%I', t.tablename), 'SELECT') as auth_select,
       has_table_privilege('authenticated', format('public.%I', t.tablename), 'INSERT') as auth_insert,
       has_table_privilege('authenticated', format('public.%I', t.tablename), 'UPDATE') as auth_update,
       has_table_privilege('authenticated', format('public.%I', t.tablename), 'DELETE') as auth_delete,
       has_table_privilege('service_role',  format('public.%I', t.tablename), 'INSERT') as svc_insert,
       has_table_privilege('service_role',  format('public.%I', t.tablename), 'DELETE') as svc_delete
  from pg_tables t
 where t.schemaname = 'public'
 order by 1;
-- anon_insert must be false on every row. Tables where the audit expects NO
-- anon_select: every per-user table, trades, trade_create_events, feedback,
-- feedback_submit_events, scanner_testers, scanner_consents, *_admins,
-- graded_premium_viewers, graded_tos_acceptances, elo_report_viewers,
-- elo_event_roster*, deck_views, deck_versions, _tournament_deck_name_backup_116.

-- 6b. profiles column-level grants (63 narrowed these; 134 splits anon vs
--     authenticated). has_table_privilege is table-level and will read false;
--     has_any_column_privilege / information_schema.column_privileges show the
--     column grants.
select has_any_column_privilege('anon',          'public.profiles', 'SELECT') as anon_any_col,
       has_any_column_privilege('authenticated', 'public.profiles', 'SELECT') as auth_any_col;
select grantee, privilege_type, string_agg(column_name, ', ' order by column_name) as columns
  from information_schema.column_privileges
 where table_schema = 'public' and table_name = 'profiles'
   and grantee in ('anon', 'authenticated')
 group by 1, 2
 order by 1, 2;
-- Expected before 134: both roles = user_id, display_name, avatar_url,
-- created_at, updated_at, collection_raw/sealed/graded_visibility.
-- Expected after 134: anon = user_id, display_name, avatar_url;
-- authenticated = those three + the three collection_*_visibility columns.
-- collection_share_token must appear for NEITHER role.

-- 6c. Default privileges (audit I6). Anything granting to anon/authenticated
--     here means new tables become API-readable before their migration says so.
select defaclrole::regrole            as for_role,
       defaclnamespace::regnamespace  as in_schema,
       defaclobjtype                  as objtype,   -- r table, f function, S sequence
       defaclacl                      as acl
  from pg_default_acl
 order by 1, 2, 3;

-- 6d. Tables in public with RLS OFF (expect: none, or only the 117/118 backup
--     table until migration 134 drops it).
select c.relname, c.relrowsecurity as rls_on, c.relforcerowsecurity as rls_forced
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity
 order by 1;

-- 6e. Tables with RLS ON but zero policies (locked to service_role / definer
--     functions by design — audit table lists them; anything unexpected = review).
select c.relname
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity
   and not exists (select 1 from pg_policy p where p.polrelid = c.oid)
 order by 1;

-- 6f. Matview grants (information_schema does not list matviews) + whether the
--     market_index matviews were ever populated (audit I1 / migration 131).
select m.matviewname,
       has_table_privilege('anon',          format('public.%I', m.matviewname), 'SELECT') as anon_select,
       has_table_privilege('authenticated', format('public.%I', m.matviewname), 'SELECT') as authenticated_select,
       has_table_privilege('service_role',  format('public.%I', m.matviewname), 'SELECT') as service_role_select,
       c.relispopulated                                                                    as populated
  from pg_matviews m
  join pg_class c on c.relname = m.matviewname
  join pg_namespace n on n.oid = c.relnamespace and n.nspname = m.schemaname
 where m.schemaname = 'public'
 order by 1;

-- 6g. Views without security_invoker (audit section 4: expect none).
select c.relname, c.reloptions
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'v'
   and not coalesce(c.reloptions::text ilike '%security_invoker=on%', false)
 order by 1;

-- ══════════════════════════════════════════════════════════════════════════
-- 7. request.headers echo helper (OPTIONAL, TEMPORARY — audit H1).
--    PostgREST exposes the HTTP request headers to SQL as the transaction GUC
--    `request.headers`; the SQL editor never sets it, so the helper has to be
--    called from the browser. Uncomment, run, call, then DROP it.
-- ══════════════════════════════════════════════════════════════════════════
-- create or replace function public._echo_request_headers()
-- returns jsonb
-- language sql
-- stable
-- set search_path = ''
-- as $$ select coalesce(current_setting('request.headers', true), '{}')::jsonb $$;
-- grant execute on function public._echo_request_headers() to anon, authenticated;
-- notify pgrst, 'reload schema';
--
-- From the site's devtools console (signed in or out):
--   sbClient.rpc("_echo_request_headers").then(r => console.log(r.data))
-- and once more with a forged first hop, to reproduce the H1 defect:
--   fetch(SUPABASE_URL + "/rest/v1/rpc/_echo_request_headers", {method: "POST",
--     headers: {...sbHeaders(), "Content-Type": "application/json",
--               "X-Forwarded-For": "203.0.113.9"}, body: "{}"})
--     .then(r => r.json()).then(console.log)
-- Look at `cf-connecting-ip` (should be your real address both times) and
-- `x-forwarded-for` (starts with 203.0.113.9 in the second call = spoofable).
--
-- Then remove it:
-- drop function if exists public._echo_request_headers();
-- notify pgrst, 'reload schema';

-- ══════════════════════════════════════════════════════════════════════════
-- 8. Data checks.
-- ══════════════════════════════════════════════════════════════════════════
-- 8a. profiles.avatar_url values that would NOT satisfy migration 134's CHECK.
--     The constraint is added NOT VALID (existing rows are not checked at
--     ALTER time) but a row listed here would fail on its next UPDATE, so
--     decide per row (null it out, or extend the pattern) before applying.
select user_id, left(avatar_url, 140) as avatar_url, updated_at
  from public.profiles
 where avatar_url is not null
   and not (
     length(avatar_url) <= 512
     and avatar_url ~ '^(/img-proxy/|/tcg-img-proxy/|https://packs\.ink/img-proxy/|https://packs\.ink/tcg-img-proxy/|https://cards\.lorcast\.io/|https://tcgplayer-cdn\.tcgplayer\.com/|https://umwqowkiatjjltologrd\.supabase\.co/storage/v1/object/public/card-art/|Logos/cards/)'
   )
 order by updated_at desc;

-- Distribution of avatar_url prefixes (what shapes actually exist).
select coalesce(substring(avatar_url from '^(https?://[^/]+/[^/]*/?|/[^/]+/|[A-Za-z]+/[^/]+/)'), '(null)') as prefix,
       count(*)
  from public.profiles
 group by 1
 order by 2 desc;

-- 8b. Audit H2, empirically: scan_samples rows since the 2026-08-04 public
--     beta from accounts that are NOT on the tester allowlist and NOT graded
--     admins. Any `allowlisted = false` rows mean the migration-98 gate is
--     already gone live; none (with consents recorded below) means uploads
--     have been silently failing for the public.
with testers as (
  select u.id
    from auth.users u
    join public.scanner_testers t on lower(t.email) = lower(u.email)
), admins as (
  select user_id as id from public.graded_admins
)
select (s.user_id in (select id from testers) or s.user_id in (select id from admins)) as allowlisted,
       count(*)                 as sample_rows,
       count(distinct s.user_id) as accounts,
       min(s.created_at)        as first_row,
       max(s.created_at)        as last_row
  from public.scan_samples s
 where s.created_at >= '2026-08-04'
 group by 1
 order by 1;

-- Accounts that accepted the beta notice (uploads_enabled = true) vs those
-- that have at least one sample row — a large gap is the silent-failure case.
select count(*)                                                        as consented_uploads_on,
       count(*) filter (where exists (select 1 from public.scan_samples s
                                       where s.user_id = c.user_id))   as with_any_sample_row
  from public.scanner_consents c
 where c.uploads_enabled;

-- 8c. Anonymous-write tables (audit H1): current size + hourly rate, to size
--     the global backstops in migration 133 (300/h trades, 120/h feedback).
select 'trades' as tbl, count(*) as rows, pg_size_pretty(pg_total_relation_size('public.trades')) as size,
       count(*) filter (where created_at > now() - interval '1 hour') as last_hour,
       count(*) filter (where created_at > now() - interval '24 hours') as last_24h
  from public.trades
union all
select 'feedback', count(*), pg_size_pretty(pg_total_relation_size('public.feedback')),
       count(*) filter (where created_at > now() - interval '1 hour'),
       count(*) filter (where created_at > now() - interval '24 hours')
  from public.feedback;
