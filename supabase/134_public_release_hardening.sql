-- 134_public_release_hardening.sql
--
-- STAGED — not applied; review + paste in the SQL editor.
--
-- Pre-release hardening batch from the 2026-09 schema audit. One file, nine
-- independent sections (apply as a whole; each section is idempotent):
--
--   L1  EXECUTE hygiene: revoke the default PUBLIC EXECUTE that CREATE FUNCTION
--       hands out (106:128-135 states the rule but applied it only to its own
--       four functions) and grant exactly the roles that actually call each one.
--   L4  pin search_path on scanner_consents_touch() (114:50-58, the only
--       trigger function left unpinned after 64/65).
--   L5  drop the leftover backup table _tournament_deck_name_backup_116
--       (117:31 / 118:29; no RLS, no grants; 117:90 says to drop it).
--   M5  report_graded_sale: cap the comment at 1000 chars + 20 reports / user /
--       hour; remove the direct INSERT path on graded_sale_reports.
--   I9  service_role grant on graded_collection_goals (the only per-user table
--       migration 100 missed).
--   M1  get_shared_collection_raw / _sealed no longer return `notes`.
--   M2  split the profiles column grant: anon gets user_id, display_name,
--       avatar_url; authenticated additionally the three collection_*_visibility
--       columns (needed only for the caller's OWN row).
--   M3  CHECK constraint on profiles.avatar_url (NOT VALID) allowing exactly
--       the URL shapes the client writes, plus NULL.
--   L3  the three tournament RPCs that pin statement_timeout with an in-body
--       `set local` (which cannot re-arm a running timer — the defect 131
--       diagnosed for refresh_market_index) get a function-level SET clause.
--       Bodies copied verbatim (see each section for the source migration).
--
-- PRECONDITIONS
--   * Independent of 132/133 — apply in any order. The only cross-file care is
--     is_scanner_tester(): 98's policies reference it until 132 lands, so this
--     file keeps its `authenticated` grant (see L1).
--   * M2/M3 verified against every client read/write of profiles (Index.html
--     33241, 37376, 37424, 37684, 37771, 43128-43135, 43162, 43193, 43324): no
--     `select("*")`, other users' rows are only ever read as
--     user_id,display_name,avatar_url, the visibility columns are read only for
--     the caller's own row, upsert/update calls chain no .select() (PostgREST
--     return=minimal), and avatar_url is only ever written as
--     `card.img_small || card.img_normal` from the catalog or NULL.
--   * M1 verified: no client code reads `.notes` off the shared rows (the only
--     `notes` identifiers in Index.html are the deck-description UI).
--   * M5 verified: zero `from("graded_sale_reports")` in Index.html — the
--     client only uses the RPC, so the direct grant + policy can go.
--   * L5: only after confirming the 117/118 rollback path is no longer wanted
--     (the backup exists so those name-clearing data migrations can be undone).
--   * Post-apply smoke test for L1's trigger-function revokes: add one card to
--     a collection and rename a deck as an ordinary signed-in user — the
--     updated_at / token-rotation triggers must still fire (Postgres checks
--     EXECUTE on a trigger function only at CREATE TRIGGER time, not when the
--     trigger fires; this is the documented behaviour, but verify it here).
--
-- Every SECURITY DEFINER function below pins search_path as a function-level
-- SET clause. Ends with notify pgrst.

-- ══════════════════════════════════════════════════════════════════════════
-- L1. EXECUTE hygiene
-- ══════════════════════════════════════════════════════════════════════════
-- Roles were chosen from the actual call sites:
--   authenticated only — client calls sit behind `if(!user)` (Index.html
--   43097, 43050, 43068, 6444, 24383, 6570, 6624, 36908) and the bodies keep
--   their is_graded_admin() / is_tournament_admin() / auth.uid() gates:
revoke all on function public.admin_update_graded_sale(text, text, text, text, numeric) from public, anon;
grant  execute on function public.admin_update_graded_sale(text, text, text, text, numeric) to authenticated;
revoke all on function public.admin_delete_graded_sale(text) from public, anon;
grant  execute on function public.admin_delete_graded_sale(text) to authenticated;
revoke all on function public.admin_list_graded_reports(text) from public, anon;
grant  execute on function public.admin_list_graded_reports(text) to authenticated;
revoke all on function public.admin_resolve_report(bigint, text) from public, anon;
grant  execute on function public.admin_resolve_report(bigint, text) to authenticated;
revoke all on function public.admin_add_private_sale(text, text, text, numeric, date, text) from public, anon;
grant  execute on function public.admin_add_private_sale(text, text, text, numeric, date, text) to authenticated;
revoke all on function public.accept_graded_tos(text) from public, anon;
grant  execute on function public.accept_graded_tos(text) to authenticated;
revoke all on function public.graded_tos_status() from public, anon;
grant  execute on function public.graded_tos_status() to authenticated;
revoke all on function public.get_roster_scout(boolean) from public, anon;
grant  execute on function public.get_roster_scout(boolean) to authenticated;
-- is_graded_admin(): also evaluated by the scan_samples + storage.objects
-- policies, which are `to authenticated`; admin_list_graded_reports/get_feedback
-- call it as SECURITY DEFINER (owner).
revoke all on function public.is_graded_admin() from public, anon;
grant  execute on function public.is_graded_admin() to authenticated;
-- is_tournament_admin(uuid): client call (36908) is signed-in only; the
-- tournaments / tournament_decks admin policies are `to authenticated`;
-- can_view_store_report() calls it as SECURITY DEFINER. anon never needs it
-- (the public SELECT policies are `using (true)`), and the explicit anon grant
-- from 35:88 was an admin-membership oracle (audit I2).
revoke all on function public.is_tournament_admin(uuid) from public, anon;
grant  execute on function public.is_tournament_admin(uuid) to authenticated;

--   authenticated + service_role:
-- is_elo_admin(uuid): elo_* admin policies (`to authenticated`) + the exporter
-- grant from 56b:18. Client never calls it directly; anon never evaluates it.
revoke all on function public.is_elo_admin(uuid) from public, anon;
grant  execute on function public.is_elo_admin(uuid) to authenticated, service_role;
-- gen_share_token(): column DEFAULT on decks.share_token (22:43) and
-- profiles.collection_share_token (39:54) runs as the INSERTING role, and the
-- BEFORE UPDATE trigger rotate_share_token_on_private (SECURITY INVOKER) calls
-- it as the updating role. authenticated inserts decks/profiles from the client;
-- scripts/seed_coconut_starter_decks.py inserts decks as service_role.
revoke all on function public.gen_share_token() from public, anon;
grant  execute on function public.gen_share_token() to authenticated, service_role;

--   anon + authenticated + service_role:
-- safe_local_ts(): called inside get_nearby_lorcana_events (113:129 is
-- SECURITY INVOKER) which anon runs from the signed-out home page.
revoke all on function public.safe_local_ts(timestamptz, text) from public;
grant  execute on function public.safe_local_ts(timestamptz, text) to anon, authenticated, service_role;
-- get_nearby_lorcana_events: granted in 113:229 but never revoked from PUBLIC.
revoke all on function public.get_nearby_lorcana_events(double precision, double precision, double precision, text, integer, integer) from public;
grant  execute on function public.get_nearby_lorcana_events(double precision, double precision, double precision, text, integer, integer) to anon, authenticated;
-- get_shared_collection_graded: recreated in 65:39 with plain `create function`
-- (fresh default PUBLIC EXECUTE) and never revoked. raw/sealed are handled in M1.
revoke all on function public.get_shared_collection_graded(uuid, text) from public;
grant  execute on function public.get_shared_collection_graded(uuid, text) to anon, authenticated;

--   nobody through the API:
-- can_view_graded_premium(): dead code (CLAUDE.md "The allowlist is retired");
-- no client call, no policy. Not dropped here — DROP is a human decision.
revoke all on function public.can_view_graded_premium() from public, anon, authenticated;
-- graded_sale_pkey(): only evaluated inside the graded_sales_rollup matview
-- body, and REFRESH runs that as the matview owner.
revoke all on function public.graded_sale_pkey(text, boolean, boolean) from public, anon, authenticated;
-- Trigger functions: not callable through PostgREST (they return `trigger`),
-- and fire-time execution does not check EXECUTE.
revoke all on function public.set_updated_at() from public, anon, authenticated;
revoke all on function public.rotate_share_token_on_private() from public, anon, authenticated;
revoke all on function public.rotate_collection_token_on_all_private() from public, anon, authenticated;
revoke all on function public.scanner_consents_touch() from public, anon, authenticated;
revoke all on function public.scan_samples_daily_cap() from public, anon, authenticated;
revoke all on function public.scan_samples_daily_cap_stmt() from public, anon, authenticated;

--   is_scanner_tester(): the client probe is gone (CLAUDE.md line 82), so anon
--   and PUBLIC lose it; `authenticated` is KEPT because 98's INSERT/UPDATE
--   policies reference it until migration 132 is applied. Once 132 is in, it
--   and public.scanner_testers can be dropped by hand.
revoke all on function public.is_scanner_tester() from public, anon;
grant  execute on function public.is_scanner_tester() to authenticated;

-- ══════════════════════════════════════════════════════════════════════════
-- L4. Pin search_path on the one unpinned trigger function.
-- ══════════════════════════════════════════════════════════════════════════
alter function public.scanner_consents_touch() set search_path = public;

-- ══════════════════════════════════════════════════════════════════════════
-- L5. Leftover backup table from the 117/118 data migrations.
-- ══════════════════════════════════════════════════════════════════════════
drop table if exists public._tournament_deck_name_backup_116;

-- ══════════════════════════════════════════════════════════════════════════
-- M5. report_graded_sale: bounded comment + per-user cap; no direct INSERT.
--     Body from 74_graded_review.sql:56-67 (latest definition). Edits: the
--     v_recent count/raise, and left(p_comment, 1000) in the insert.
--     graded_sale_reports(user_id) is indexed (92:25-26), so the count is cheap.
-- ══════════════════════════════════════════════════════════════════════════
create or replace function public.report_graded_sale(p_item_id text, p_comment text)
returns void language plpgsql security definer set search_path = public
as $$
declare
  v_recent int;
begin
  if auth.uid() is null then raise exception 'sign in to report'; end if;
  if not exists(select 1 from public.graded_sales where item_id = p_item_id) then
    raise exception 'unknown sale';
  end if;
  -- 134: 20 reports / user / hour.
  select count(*) into v_recent
    from public.graded_sale_reports
   where user_id = auth.uid()
     and created_at > now() - interval '1 hour';
  if v_recent >= 20 then
    raise exception 'rate limited: too many reports submitted — try again in an hour';
  end if;
  insert into public.graded_sale_reports(item_id, user_id, comment)
  values (p_item_id, auth.uid(), nullif(btrim(coalesce(left(p_comment, 1000), '')), ''));
end;
$$;
revoke all on function public.report_graded_sale(text, text) from public, anon;
grant  execute on function public.report_graded_sale(text, text) to authenticated;

-- The client only ever goes through the RPC, so the direct table path
-- (74:50-52 grant + policy, which let a caller set status / resolved_at /
-- resolved_by and unbounded comments) is removed. RLS stays on with no
-- policies; service_role keeps its 74:53 grant and bypasses RLS.
revoke insert on public.graded_sale_reports from authenticated;
drop policy if exists "graded report insert own" on public.graded_sale_reports;

-- ══════════════════════════════════════════════════════════════════════════
-- I9. service_role on graded_collection_goals (mirrors 100:26-28).
-- ══════════════════════════════════════════════════════════════════════════
grant select, insert, update, delete on public.graded_collection_goals to service_role;

-- ══════════════════════════════════════════════════════════════════════════
-- M1. Shared-collection RPCs stop returning `notes`.
--     RETURNS TABLE changes, so drop + recreate (42P13 otherwise).
--     get_shared_collection_raw body from 39_collection_sharing.sql:150-172
--     (never redefined since); get_shared_collection_sealed body from
--     65_review_privacy_hardening.sql:18-35 (its latest). Only `notes` removed.
-- ══════════════════════════════════════════════════════════════════════════
drop function if exists public.get_shared_collection_raw(uuid, text);
create function public.get_shared_collection_raw(p_user_id uuid, p_token text)
returns table(
  user_id    uuid,
  card_id    text,
  printing   text,
  condition  text,
  quantity   int,
  updated_at timestamptz
)
language sql
security definer
set search_path = public
as $$
  select ci.user_id, ci.card_id, ci.printing, ci.condition, ci.quantity, ci.updated_at
    from public.collection_items ci
    join public.profiles p on p.user_id = ci.user_id
   where ci.user_id = p_user_id
     and (
       p.collection_raw_visibility = 'public'
       OR (p.collection_raw_visibility = 'unlisted' AND p.collection_share_token = p_token)
     );
$$;
revoke all on function public.get_shared_collection_raw(uuid, text) from public;
grant  execute on function public.get_shared_collection_raw(uuid, text) to anon, authenticated;

drop function if exists public.get_shared_collection_sealed(uuid, text);
create function public.get_shared_collection_sealed(p_user_id uuid, p_token text)
returns table(user_id uuid, tcgplayer_product_id bigint, condition text,
              quantity integer, acquired_date date,
              updated_at timestamptz)
language sql
security definer
set search_path to 'public'
as $function$
  select sci.user_id, sci.tcgplayer_product_id, sci.condition, sci.quantity,
         sci.acquired_date, sci.updated_at
    from public.sealed_collection_items sci
    join public.profiles p on p.user_id = sci.user_id
   where sci.user_id = p_user_id
     and (
       p.collection_sealed_visibility = 'public'
       OR (p.collection_sealed_visibility = 'unlisted' AND p.collection_share_token = p_token)
     );
$function$;
revoke all on function public.get_shared_collection_sealed(uuid, text) from public;
grant  execute on function public.get_shared_collection_sealed(uuid, text) to anon, authenticated;

-- ══════════════════════════════════════════════════════════════════════════
-- M2. profiles column grant split.
--     63:56-60 granted the same 8-column list to anon AND authenticated, which
--     made every account's signup time and collection-visibility flags a
--     world-readable directory. REVOKE on the table also drops the column
--     privileges (documented REVOKE behaviour), then re-grant per role. The
--     `profiles: read all` policy (18:68-69) is unchanged; column privileges do
--     the narrowing. created_at/updated_at are read nowhere in the client.
-- ══════════════════════════════════════════════════════════════════════════
revoke select on public.profiles from anon, authenticated;
grant select (user_id, display_name, avatar_url) on public.profiles to anon;
grant select (user_id, display_name, avatar_url,
              collection_raw_visibility, collection_sealed_visibility, collection_graded_visibility)
  on public.profiles to authenticated;

-- ══════════════════════════════════════════════════════════════════════════
-- M3. profiles.avatar_url shape.
--     The client writes `card.img_small || card.img_normal` from the catalog
--     (Index.html 43319-43324) or NULL. Catalog image URLs are, in order of
--     how buildRow produces them:
--       /img-proxy/…            lorcastToProxy() on web (Index.html:664-667, 2240-2242)
--       https://packs.ink/img-proxy/…   same, in the native shell (PROXY_ORIGIN)
--       /tcg-img-proxy/… and https://packs.ink/tcg-img-proxy/…   proxyImg() (7850-7855)
--       https://tcgplayer-cdn.tcgplayer.com/…   synthetic/extras rows (2597-2604) and
--                                               cards inserted by 82/107 (not proxied by lorcastToProxy)
--       https://<project>.supabase.co/storage/v1/object/public/card-art/…   prestaged + coconut art
--       https://cards.lorcast.io/…   only if a Lorcast URL ever bypasses the proxy
--       Logos/cards/…            CHINA_ONLY_NONFOIL / JAPAN_ONLY_NONFOIL (1739-1751)
--     NOT VALID: existing rows are not checked at ALTER time. NOTE that a
--     non-conforming existing row would still fail on its NEXT update (any
--     column) — run diagnostics section 8a first; the client's avatar sync
--     effect (43318-43329) rewrites avatar_url on every sign-in, so active
--     accounts already hold a conforming value or NULL.
-- ══════════════════════════════════════════════════════════════════════════
alter table public.profiles drop constraint if exists profiles_avatar_url_shape;
alter table public.profiles add constraint profiles_avatar_url_shape
  check (
    avatar_url is null
    or (
      length(avatar_url) <= 512
      and avatar_url ~ '^(/img-proxy/|/tcg-img-proxy/|https://packs\.ink/img-proxy/|https://packs\.ink/tcg-img-proxy/|https://cards\.lorcast\.io/|https://tcgplayer-cdn\.tcgplayer\.com/|https://umwqowkiatjjltologrd\.supabase\.co/storage/v1/object/public/card-art/|Logos/cards/)'
    )
  ) not valid;

-- ══════════════════════════════════════════════════════════════════════════
-- L3. Function-level statement_timeout on the three tournament RPCs.
--     An in-body `set local statement_timeout` cannot re-arm the timer that
--     was armed when the outer statement began (131:10-35), so these ran under
--     the authenticated role's 8 s and a large upload could 57014. Bodies are
--     copied VERBATIM; the ONLY edits are the removed `set local …` line and
--     the added function-level `set statement_timeout` clause.
--     bulk_upload_tournament        — body from 116_tournament_blank_deck_names.sql:33-100
--     admin_add_tournament_deck     — body from 116_tournament_blank_deck_names.sql:106-166
--     admin_replace_tournament_deck_cards — body from 40_tournament_deck_admin.sql:22-66
-- ══════════════════════════════════════════════════════════════════════════
create or replace function public.bulk_upload_tournament(
  p_name        text,
  p_event_date  date,
  p_format      text,
  p_num_players integer,
  p_rows        jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public, extensions
set statement_timeout = '2min'
as $$
declare
  v_uid   uuid := auth.uid();
  v_tid   uuid;
  v_row   jsonb;
  v_did   uuid;
begin
  if v_uid is null then raise exception 'not authenticated'; end if;
  if not public.is_tournament_admin(v_uid) then
    raise exception 'caller is not a tournament admin';
  end if;
  if p_name is null or btrim(p_name) = '' then
    raise exception 'tournament name is required';
  end if;

  insert into public.tournaments (name, event_date, format, num_players, uploaded_by)
    values (btrim(p_name), p_event_date, p_format, p_num_players, v_uid)
    returning id into v_tid;

  for v_row in select * from jsonb_array_elements(coalesce(p_rows, '[]'::jsonb))
  loop
    insert into public.decks (user_id, name, visibility, inks)
      values (
        null,
        nullif(btrim(v_row->>'deck_name'), ''),
        'public',
        case when jsonb_typeof(v_row->'inks') = 'array'
             then (select array_agg(value) from jsonb_array_elements_text(v_row->'inks'))
             else null end
      )
      returning id into v_did;

    if jsonb_typeof(v_row->'entries') = 'array' then
      insert into public.deck_cards (deck_id, card_id, printing, quantity)
      select v_did,
             e->>'card_id',
             'Normal',
             least(4, greatest(1, (e->>'quantity')::int))
        from jsonb_array_elements(v_row->'entries') e
       where e->>'card_id' is not null;
    end if;

    insert into public.tournament_decks
      (tournament_id, deck_id, place, place_rank, player_name)
      values (
        v_tid, v_did,
        nullif(btrim(v_row->>'place'), ''),
        nullif(v_row->>'place_rank', '')::int,
        nullif(btrim(v_row->>'player_name'), '')
      );
  end loop;

  return v_tid;
end;
$$;

revoke all on function public.bulk_upload_tournament(text, date, text, integer, jsonb) from public;
grant execute on function public.bulk_upload_tournament(text, date, text, integer, jsonb) to authenticated;

create or replace function public.admin_add_tournament_deck(
  p_tid         uuid,
  p_place       text,
  p_place_rank  integer,
  p_player_name text,
  p_deck_name   text,
  p_inks        text[],
  p_cards       jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public
set statement_timeout = '1min'
as $$
declare
  v_uid uuid := auth.uid();
  v_did uuid;
  v_rid uuid;
begin
  if v_uid is null or not public.is_tournament_admin(v_uid) then
    raise exception 'not authorized';
  end if;

  if not exists (select 1 from public.tournaments where id = p_tid) then
    raise exception 'tournament % not found', p_tid;
  end if;

  insert into public.decks (user_id, name, visibility, inks)
    values (
      null,
      nullif(btrim(p_deck_name), ''),
      'public',
      p_inks
    )
    returning id into v_did;

  if jsonb_typeof(p_cards) = 'array' then
    insert into public.deck_cards (deck_id, card_id, printing, quantity)
    select v_did,
           e->>'card_id',
           'Normal',
           least(99, greatest(1, (e->>'quantity')::int))
      from jsonb_array_elements(p_cards) e
     where e->>'card_id' is not null;
  end if;

  insert into public.tournament_decks
    (tournament_id, deck_id, place, place_rank, player_name)
    values (
      p_tid, v_did,
      nullif(btrim(p_place), ''),
      p_place_rank,
      nullif(btrim(p_player_name), '')
    )
    returning id into v_rid;

  return v_rid;
end;
$$;
revoke all on function public.admin_add_tournament_deck(uuid, text, integer, text, text, text[], jsonb) from public;
grant  execute on function public.admin_add_tournament_deck(uuid, text, integer, text, text, text[], jsonb) to authenticated;

create or replace function public.admin_replace_tournament_deck_cards(
  p_result_id uuid,
  p_inks      text[],
  p_cards     jsonb
)
returns void
language plpgsql
security definer
set search_path = public
set statement_timeout = '1min'
as $$
declare
  v_uid uuid := auth.uid();
  v_did uuid;
begin
  if v_uid is null or not public.is_tournament_admin(v_uid) then
    raise exception 'not authorized';
  end if;

  select deck_id into v_did
    from public.tournament_decks
   where id = p_result_id;
  if v_did is null then
    raise exception 'tournament deck not found for result %', p_result_id;
  end if;

  delete from public.deck_cards where deck_id = v_did;

  if jsonb_typeof(p_cards) = 'array' then
    insert into public.deck_cards (deck_id, card_id, printing, quantity)
    select v_did,
           e->>'card_id',
           'Normal',
           least(99, greatest(1, (e->>'quantity')::int))
      from jsonb_array_elements(p_cards) e
     where e->>'card_id' is not null;
  end if;

  update public.decks
     set inks       = p_inks,
         updated_at = now()
   where id = v_did;
end;
$$;
revoke all on function public.admin_replace_tournament_deck_cards(uuid, text[], jsonb) from public;
grant  execute on function public.admin_replace_tournament_deck_cards(uuid, text[], jsonb) to authenticated;

notify pgrst, 'reload schema';
