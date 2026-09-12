-- 148_scout_any_event.sql - a scout can add ANY event to scouting by hand.
--
-- Today the whole scouting surface is scoped to elo_tracked_stores: the Scout
-- tab lists tracked-store events, and get_scout_event / save_scout_note refuse
-- anything else. That is right for what fills the tab AUTOMATICALLY, and wrong
-- as a hard ceiling: some of the team lives outside the Chicagoland bubble, and
-- an event they are actually going to is exactly the one they want a sheet for.
--
-- So scope splits in two:
--
--   * AUTOMATIC scope stays precisely as it is. elo_tracked_stores still decides
--     what lands on the Scout tab on its own, and nothing here widens it. This
--     is Zaven's constraint - "don't auto add any more to our main scouting tab".
--
--   * OPT-IN scope is new. A scout opens an event anywhere on the site (the
--     calendar, the near-me finder, Upcoming SCs) and presses Add; that writes
--     one row to scout_events and the event becomes scoutable: roster pull,
--     sheet, notes, player history, the lot.
--
-- An added event DOES appear on the Scout tab, marked as hand-added. That is a
-- deliberate reading of the constraint above - it forbids widening the automatic
-- store scope, not hiding what somebody deliberately added. Notes written at an
-- out-of-bubble event would otherwise be reachable only through a player's own
-- history, which is a strange place to have to go to finish the sheet you were
-- filling in an hour ago.
--
-- Players at those events need nothing new: scout_player_key already falls back
-- to name:<lowercased> for anyone RPH never recorded, get_scout_event LEFT JOINs
-- the leaderboard so an unrated player renders NR, and 144 adds "Add player" for
-- a walk-in. The tracked gate was the only thing in the way.
--
-- HOW THE GATE WIDENS, and why it is done this way:
--
-- scout_event_meta returns `tracked`, and every consumer - get_scout_event (in
-- both 143 and 144), save_scout_note, and the refresh-elo-rosters edge function
-- - reads exactly that one flag and means "may we scout this". So `tracked`
-- widens IN PLACE to "the store is tracked OR a scout added this event", and the
-- narrow facts are appended beside it as `store_tracked` and `opted_in`.
--
-- That is the safe shape rather than the tidy one. The tidy version - a new
-- `scoutable` column and a re-gate of every caller - means this migration and
-- 144 both re-create get_scout_event, so applying 144 AFTER 148 would silently
-- revert the gate and an added event would stop opening with a message blaming
-- the store. Widening the flag the callers already read makes the order they are
-- pasted in stop mattering.
--
-- ORDERING. 148 contains 147's get_roster_scout change and 144's get_scout_event
-- body, so 144 -> 147 -> 148 in ascending order is correct, and pasting 148 on
-- its own is also correct. The one mistake is running an EARLIER file after this
-- one; that costs the hand-added events on the Scout tab (147) or the "added by"
-- line in the sheet header (144), never the gate.
--
-- Idempotent; safe to re-run. Requires 143.

-- == 1. The opt-in ledger ==================================================
-- One row per event a scout has added. RLS on with no policies, like
-- scout_notes: every path in goes through a definer function below.
--
-- The event label is DENORMALISED for the same reason scout_notes denormalises
-- it: lorcana_events is an UPCOMING feed that prunes what has already happened,
-- and an added event that has aged out of every feed must still resolve or its
-- sheet stops opening. scout_event_meta reads this table as a late resolution
-- source, so the ledger row is what keeps a hand-added event alive - and reads
-- scout_notes after it, so REMOVING an event is reversible rather than orphaning
-- whatever was written on it.
create table if not exists public.scout_events (
  event_id       bigint primary key,
  event_name     text,
  start_datetime timestamptz,
  event_tz       text,
  store_id       bigint,
  store_name     text,
  city           text,
  state          text,
  added_by       uuid references auth.users(id) on delete set null,
  added_by_name  text,
  added_at       timestamptz not null default now()
);
create index if not exists scout_events_start_idx on public.scout_events (start_datetime desc);
alter table public.scout_events enable row level security;
revoke all on public.scout_events from public, anon, authenticated;
grant select on public.scout_events to service_role;

-- == 2. Event resolution, widened ==========================================
-- DROP first: a RETURNS TABLE signature cannot be changed by CREATE OR REPLACE.
-- Re-granting is mandatory after the drop - a new relation grants nothing
-- implicitly, and service_role's grant in particular is what the edge function
-- needs (see 143's note; without it the per-event roster refresh fails with
-- "permission denied for function scout_event_meta").
drop function if exists public.scout_event_meta(bigint);
create function public.scout_event_meta(p_event_id bigint)
returns table (
  event_id bigint, name text, store_id bigint, store_name text,
  start_datetime timestamptz, timezone text, city text, state text,
  capacity int, kind text, set_name text,
  -- NOTE: `tracked` now means IN SCOPE FOR SCOUTING, not "the store is on the
  -- Elo board". Every caller already used it as the former. The literal store
  -- fact is `store_tracked`.
  tracked boolean, store_tracked boolean, opted_in boolean,
  registered_count int, added_by_name text, added_at timestamptz
)
language sql security definer set search_path = public, extensions stable
as $$
  with src as (
    select e.event_id, e.name, e.store_id, e.store_name, e.start_datetime, e.timezone,
           e.city, e.state, e.capacity, e.kind, e.set_name, e.registered_user_count, 1 as pref
      from public.lorcana_events e where e.event_id = p_event_id
    union all
    select h.event_id, h.name, h.store_id, h.store_name, h.start_datetime, h.timezone,
           h.city, h.state, h.capacity, h.kind, h.set_name, h.registered_user_count, 2
      from public.lorcana_events_history h where h.event_id = p_event_id
    union all
    select s.event_id, s.name, s.store_id, s.store_name, s.start_datetime, s.timezone,
           s.city, s.state, s.capacity, 'sc', s.set_name, s.registered_user_count, 3
      from public.set_championships s where s.event_id = p_event_id
    union all
    -- The ledger's own copy. This is what makes a hand-added event outlive the
    -- feed it was added from.
    select a.event_id, a.event_name, a.store_id, a.store_name, a.start_datetime, a.event_tz,
           a.city, a.state, null::int, null::text, null::text, null::int, 4
      from public.scout_events a where a.event_id = p_event_id
    union all
    -- Last resort: a note's own denormalised label. This is what makes REMOVING
    -- an event reversible. Without it, taking an aged-out event back off the
    -- board orphans its sheet permanently - scout_event_add refuses an event
    -- nothing can name, so the notes survive only in each player's history and
    -- the sheet can never be opened again. That is the exact failure the graded
    -- view's per-card Hide was killed for. Caught by the fixture test, which is
    -- why it is here rather than in a later migration.
    (select n.event_id, n.event_name, null::bigint, n.store_name, n.event_date, n.event_tz,
            null::text, null::text, null::int, null::text, null::text, null::int, 5
       from public.scout_notes n where n.event_id = p_event_id
      order by n.updated_at desc limit 1)
  ),
  pick as (select s.* from src s order by s.pref limit 1)
  select p.event_id, p.name, p.store_id, p.store_name, p.start_datetime, p.timezone,
         p.city, p.state, p.capacity, p.kind, p.set_name,
         (t.store_id is not null or a.event_id is not null),
         (t.store_id is not null),
         (a.event_id is not null),
         p.registered_user_count, a.added_by_name, a.added_at
    from pick p
    left join public.elo_tracked_stores t on t.store_id = p.store_id
    left join public.scout_events a on a.event_id = p.event_id;
$$;
revoke all on function public.scout_event_meta(bigint) from public, anon;
grant execute on function public.scout_event_meta(bigint) to authenticated;
grant execute on function public.scout_event_meta(bigint) to service_role;

-- == 3. Add / remove one event =============================================
-- Refuses an event that resolves nowhere: a ledger row pointing at a bare number
-- nobody can name is worse than no row.
create or replace function public.scout_event_add(p_event_id bigint)
returns jsonb
language plpgsql security definer set search_path = public, extensions volatile
as $$
declare
  v_meta   record;
  v_author text;
begin
  if not public.can_scout() then
    raise exception 'not authorized';
  end if;

  select * into v_meta from public.scout_event_meta(p_event_id);
  if v_meta.event_id is null then
    raise exception 'we have no event % on file', p_event_id;
  end if;

  select nullif(btrim(pr.display_name), '')
    into v_author from public.profiles pr where pr.user_id = (select auth.uid());
  v_author := coalesce(v_author, 'A teammate');

  insert into public.scout_events as s (
    event_id, event_name, start_datetime, event_tz,
    store_id, store_name, city, state, added_by, added_by_name)
  values (
    v_meta.event_id, v_meta.name, v_meta.start_datetime, v_meta.timezone,
    v_meta.store_id, v_meta.store_name, v_meta.city, v_meta.state,
    (select auth.uid()), v_author)
  on conflict (event_id) do update
     -- Re-adding refreshes the stored label from the live feed but keeps who
     -- added it: the first person to put it on the board is the fact worth
     -- keeping, and a second press is usually a mis-click.
     set event_name     = coalesce(excluded.event_name, s.event_name),
         start_datetime = coalesce(excluded.start_datetime, s.start_datetime),
         event_tz       = coalesce(excluded.event_tz, s.event_tz),
         store_id       = coalesce(excluded.store_id, s.store_id),
         store_name     = coalesce(excluded.store_name, s.store_name),
         city           = coalesce(excluded.city, s.city),
         state          = coalesce(excluded.state, s.state);

  return jsonb_build_object(
    'event_id', v_meta.event_id, 'added', true,
    'name', v_meta.name, 'store_name', v_meta.store_name,
    'store_tracked', v_meta.store_tracked);
end;
$$;
revoke all on function public.scout_event_add(bigint) from public, anon;
grant execute on function public.scout_event_add(bigint) to authenticated;

-- Removing is reversible on purpose: the notes stay (they are still in every
-- player's own history) and re-adding restores the sheet exactly. The count of
-- what is being left behind comes back so the UI can say so rather than making
-- the reader guess - the lesson from the graded view's per-card Hide, which was
-- killed for making things vanish with no way back.
create or replace function public.scout_event_remove(p_event_id bigint)
returns jsonb
language plpgsql security definer set search_path = public, extensions volatile
as $$
declare
  v_notes int;
  v_gone  boolean;
begin
  if not public.can_scout() then
    raise exception 'not authorized';
  end if;
  select count(*) into v_notes from public.scout_notes where event_id = p_event_id;
  delete from public.scout_events where event_id = p_event_id;
  v_gone := found;
  return jsonb_build_object('event_id', p_event_id, 'removed', v_gone, 'notes_kept', v_notes);
end;
$$;
revoke all on function public.scout_event_remove(bigint) from public, anon;
grant execute on function public.scout_event_remove(bigint) to authenticated;

-- == 4. The panel's read ===================================================
-- 144's body verbatim, plus `added` / `added_by` / `added_at` on the event so the
-- sheet can mark a hand-added event and offer to take it back off. The GATE is
-- untouched - v_meta.tracked is what widened in section 2.
create or replace function public.get_scout_event(p_event_id bigint)
returns jsonb
language plpgsql security definer set search_path = public, extensions stable
as $$
declare
  v_meta    record;
  v_event   jsonb;
  v_field   jsonb;
  v_players jsonb;
begin
  if not public.can_scout() then
    raise exception 'not authorized';
  end if;

  select * into v_meta from public.scout_event_meta(p_event_id);
  if v_meta.event_id is null then
    return jsonb_build_object('scoutable', false, 'reason', 'unknown_event',
                              'event', jsonb_build_object('event_id', p_event_id));
  end if;
  if not v_meta.tracked then
    return jsonb_build_object('scoutable', false, 'reason', 'untracked_store',
      'event', jsonb_build_object('event_id', v_meta.event_id, 'name', v_meta.name,
                                  'store_name', v_meta.store_name));
  end if;

  with roster as (
    select m.best_identifier, m.account_name, m.rph_user_id,
           public.scout_player_key(m.rph_user_id, m.best_identifier) as player_key,
           false as off_roster
      from public.elo_event_roster_members m
     where m.event_id = p_event_id
  ),
  -- Anyone this event carries a note for who is NOT on the roster: a walk-in we
  -- added by hand, or somebody who has since dropped their registration. Their
  -- stored player_name is the only name we have for them.
  extra as (
    select n.player_name as best_identifier, null::text as account_name,
           n.rph_user_id, n.player_key, true as off_roster
      from public.scout_notes n
     where n.event_id = p_event_id
       and not exists (select 1 from roster r where r.player_key = n.player_key)
  ),
  mem as (
    select * from roster union all select * from extra
  ),
  resolved as (
    select mb.*, lb.player_id, lb.current_rating, lb.rank, lb.wins, lb.losses,
           (lb.player_id is not null) as matched
      from mem mb
      left join public.elo_players p
             on p.platform = 'rph' and lower(p.display_name) = lower(mb.best_identifier)
      left join public.elo_leaderboard_v lb
             on lb.player_id = coalesce(p.merged_into_id, p.player_id)
  ),
  hist as (
    select n.player_key, count(*) as n_notes
      from public.scout_notes n
     where n.player_key in (select player_key from mem) and n.event_id <> p_event_id
     group by n.player_key
  )
  select
    coalesce(jsonb_agg(jsonb_build_object(
      'best_identifier', r.best_identifier,
      'account_name',    r.account_name,
      'rph_user_id',     r.rph_user_id,
      'player_key',      r.player_key,
      'off_roster',      r.off_roster,
      'player_id',       r.player_id,
      'current_rating',  r.current_rating,
      'rank',            r.rank,
      'wins',            r.wins,
      'losses',          r.losses,
      'matched',         r.matched,
      'deck',            sn.deck,
      'notes',           sn.notes,
      'note_by',         sn.updated_by_name,
      'note_at',         sn.updated_at,
      'prior_notes',     coalesce(h.n_notes, 0)
    ) order by r.current_rating desc nulls last, r.best_identifier asc), '[]'::jsonb),
    jsonb_build_object(
      -- "Signed up" stays the ROSTER count. An off-roster note is our own record
      -- of who was in the room; folding it in would quietly restate RPH's number
      -- as something it isn't.
      'n_signed_up', count(*) filter (where not r.off_roster),
      'n_off_roster',count(*) filter (where r.off_roster),
      'n_rated',     count(*) filter (where r.matched),
      'n_unrated',   count(*) filter (where not r.matched),
      'n_logged',    count(*) filter (where sn.id is not null),
      'avg_elo',     round(avg(r.current_rating) filter (where r.matched)::numeric, 0),
      'top_elo',     round(max(r.current_rating) filter (where r.matched)::numeric, 0)
    )
  into v_players, v_field
  from resolved r
  left join public.scout_notes sn
         on sn.event_id = p_event_id and sn.player_key = r.player_key
  left join hist h on h.player_key = r.player_key;

  select jsonb_build_object(
    'event_id',       v_meta.event_id,
    'name',           v_meta.name,
    'store_name',     v_meta.store_name,
    'store_id',       v_meta.store_id,
    'city',           v_meta.city,
    'state',          v_meta.state,
    'set_name',       v_meta.set_name,
    'kind',           v_meta.kind,
    'capacity',       coalesce(r.capacity, v_meta.capacity),
    'start_datetime', v_meta.start_datetime,
    'timezone',       v_meta.timezone,
    'scraped_at',     r.scraped_at,
    'registered_count', coalesce(r.registered_count, v_meta.registered_count),
    'added',          v_meta.opted_in,
    'store_tracked',  v_meta.store_tracked,
    'added_by',       v_meta.added_by_name,
    'added_at',       v_meta.added_at
  ) into v_event
  from (select p_event_id as eid) base
  left join public.elo_event_roster r on r.event_id = base.eid;

  return jsonb_build_object(
    'scoutable', true,
    'event',   coalesce(v_event, jsonb_build_object('event_id', p_event_id)),
    'field',   coalesce(v_field, jsonb_build_object('n_signed_up', 0, 'n_off_roster', 0,
                 'n_rated', 0, 'n_unrated', 0, 'n_logged', 0, 'avg_elo', null, 'top_elo', null)),
    'players', coalesce(v_players, '[]'::jsonb)
  );
end;
$$;
revoke all on function public.get_scout_event(bigint) from public, anon;
grant execute on function public.get_scout_event(bigint) to authenticated;

-- == 5. The Scout tab's slate ==============================================
-- 147's body (the 24-hour window) plus the hand-added events, each marked so the
-- tab can say which are there because somebody put them there. The automatic
-- half is byte-identical to 147's: elo_tracked_stores still decides it alone.
create or replace function public.get_roster_scout(p_exclude_org boolean default false)
returns jsonb
language plpgsql stable security definer
set search_path to 'public', 'extensions'
as $$
declare
  v_org_names constant text[] := array['I&L⟡Zaven', 'I&L⟡jacobayy'];
  v_result jsonb;
begin
  if not (public.can_view_store_report() or public.can_scout()) then
    raise exception 'not authorized';
  end if;

  with tracked_ev as (
    select sc.event_id, sc.name, sc.store_name, sc.city, sc.state,
           sc.start_datetime, sc.set_name, sc.timezone,
           coalesce(r.capacity, sc.capacity)                  as capacity,
           coalesce(r.registered_count, sc.registered_user_count) as registered_count,
           r.scraped_at, false as added, null::text as added_by
      from public.set_championships sc
      join public.elo_tracked_stores t on t.store_id = sc.store_id
      left join public.elo_event_roster r on r.event_id = sc.event_id
     where sc.start_datetime >= now() - interval '24 hours'
  ),
  -- Hand-added events, resolved through scout_event_meta so one that has aged
  -- out of every live feed still lists off the ledger's own stored label. The
  -- NOT EXISTS keeps an added SC at a tracked store from listing twice.
  added_ev as (
    select a.event_id,
           coalesce(m.name, a.event_name)                   as name,
           coalesce(m.store_name, a.store_name)             as store_name,
           coalesce(m.city, a.city)                         as city,
           coalesce(m.state, a.state)                       as state,
           coalesce(m.start_datetime, a.start_datetime)     as start_datetime,
           m.set_name,
           coalesce(m.timezone, a.event_tz)                 as timezone,
           coalesce(r.capacity, m.capacity)                 as capacity,
           coalesce(r.registered_count, m.registered_count) as registered_count,
           r.scraped_at, true as added, a.added_by_name as added_by
      from public.scout_events a
      left join lateral public.scout_event_meta(a.event_id) m on true
      left join public.elo_event_roster r on r.event_id = a.event_id
     where coalesce(m.start_datetime, a.start_datetime) >= now() - interval '24 hours'
       and not exists (select 1 from tracked_ev te where te.event_id = a.event_id)
  ),
  ev as (
    select * from tracked_ev union all select * from added_ev
  ),
  mem as (
    select m.event_id, m.best_identifier, m.account_name,
           lb.player_id, lb.current_rating, lb.rank, lb.wins, lb.losses,
           (lb.player_id is not null) as matched,
           lb.display_name as canonical_name
      from public.elo_event_roster_members m
      join ev on ev.event_id = m.event_id
      left join public.elo_players p
             on p.platform = 'rph' and lower(p.display_name) = lower(m.best_identifier)
      left join public.elo_leaderboard_v lb
             on lb.player_id = coalesce(p.merged_into_id, p.player_id)
     where not (p_exclude_org and coalesce(lb.display_name = any(v_org_names), false))
  ),
  per_event as (
    select e.event_id, e.start_datetime,
      jsonb_build_object(
        'event_id',        e.event_id,
        'name',            e.name,
        'store_name',      e.store_name,
        'city',            e.city,
        'state',           e.state,
        'set_name',        e.set_name,
        'start_datetime',  e.start_datetime,
        'timezone',        e.timezone,
        'capacity',        e.capacity,
        'registered_count',e.registered_count,
        'scraped_at',      e.scraped_at,
        'added',           e.added,
        'added_by',        e.added_by,
        'field', jsonb_build_object(
          'n_signed_up', count(mm.best_identifier),
          'n_rated',     count(*) filter (where mm.matched),
          'avg_elo',     round(avg(mm.current_rating) filter (where mm.matched)::numeric, 0),
          'top_elo',     round(max(mm.current_rating) filter (where mm.matched)::numeric, 0)
        ),
        'players', coalesce(jsonb_agg(
          jsonb_build_object(
            'best_identifier', mm.best_identifier,
            'account_name',    mm.account_name,
            'player_id',       mm.player_id,
            'current_rating',  mm.current_rating,
            'rank',            mm.rank,
            'wins',            mm.wins,
            'losses',          mm.losses,
            'matched',         mm.matched
          )
          order by mm.current_rating desc nulls last, mm.best_identifier asc
        ) filter (where mm.best_identifier is not null), '[]'::jsonb)
      ) as ev_json
    from ev e
    left join mem mm on mm.event_id = e.event_id
    group by e.event_id, e.name, e.store_name, e.city, e.state, e.set_name,
             e.start_datetime, e.timezone, e.capacity, e.registered_count, e.scraped_at,
             e.added, e.added_by
  )
  select coalesce(jsonb_agg(ev_json order by start_datetime asc), '[]'::jsonb)
    into v_result
    from per_event;

  return coalesce(v_result, '[]'::jsonb);
end;
$$;

revoke all on function public.get_roster_scout(boolean) from public, anon;
grant execute on function public.get_roster_scout(boolean) to authenticated;

-- == 6. Carried from 144 so this file stands alone =========================
-- 143's scout_member_remove takes an email, so a row added by user_id (the
-- escape hatch for a provider that omits email from the JWT) had a Remove button
-- in the admin panel that could never do anything.
create or replace function public.scout_member_delete(p_id uuid)
returns boolean
language plpgsql security definer set search_path = public, extensions volatile
as $$
begin
  if not coalesce(public.is_tournament_admin((select auth.uid())), false) then
    raise exception 'not authorized';
  end if;
  delete from public.scout_members where id = p_id;
  return found;
end;
$$;
revoke all on function public.scout_member_delete(uuid) from public, anon;
grant execute on function public.scout_member_delete(uuid) to authenticated;

notify pgrst, 'reload schema';
