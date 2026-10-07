-- 194: the scouting sheet matched one roster name to TWO rated players (audit 2026-10-07).
--
-- get_scout_event, get_roster_scout and search_scout_players resolve a roster
-- name to an Elo player by lower(display_name). RPH has two pairs of accounts
-- that differ only by case ("John M" / "john m", "Wyatt A" / "Wyatt a"), and
-- both pairs are on real rosters, so the join returned two rows: the player
-- appeared twice on the sheet and in the roster's counts and Avg Elo. Each
-- name now resolves to ONE account: one that has played a rated match first
-- ("john m" has none, while "John M" has 70 at 1851 and is the person a
-- roster "john m" means), then the exact-case match, then the unmerged one.
--
-- The same join followed a merge one hop (coalesce(merged_into_id, player_id)),
-- so a name on the first account of a two-deep merge chain (1001 -> 5 -> 2506)
-- would land on a merged account with no leaderboard row and read NR. No roster
-- holds such a name today; three such chains exist. It follows two hops now, as
-- migration 193 does for GW%.
--
-- Measured over all 1,654 stored roster members: 1,664 rows before, 1,654 after,
-- and 1,434 rated either way.
--
-- Bodies are 148's / 153's verbatim (the live functions hashed identical to
-- them, comments and whitespace aside) with only that join changed.

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
      left join lateral (
             select coalesce(p2.merged_into_id, p1.merged_into_id, p1.player_id) as canon_id
               from public.elo_players p1
               left join public.elo_players p2 on p2.player_id = p1.merged_into_id
              where p1.platform = 'rph' and lower(p1.display_name) = lower(mb.best_identifier)
              order by exists (select 1 from public.elo_ratings r
                                where r.player_id = coalesce(p2.merged_into_id, p1.merged_into_id, p1.player_id)) desc,
                       (p1.display_name = mb.best_identifier) desc,
                       (p1.merged_into_id is null) desc, p1.player_id
              limit 1) p on true
      left join public.elo_leaderboard_v lb
             on lb.player_id = p.canon_id
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
      left join lateral (
             select coalesce(p2.merged_into_id, p1.merged_into_id, p1.player_id) as canon_id
               from public.elo_players p1
               left join public.elo_players p2 on p2.player_id = p1.merged_into_id
              where p1.platform = 'rph' and lower(p1.display_name) = lower(m.best_identifier)
              order by exists (select 1 from public.elo_ratings r
                                where r.player_id = coalesce(p2.merged_into_id, p1.merged_into_id, p1.player_id)) desc,
                       (p1.display_name = m.best_identifier) desc,
                       (p1.merged_into_id is null) desc, p1.player_id
              limit 1) p on true
      left join public.elo_leaderboard_v lb
             on lb.player_id = p.canon_id
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

create or replace function public.search_scout_players(p_query text)
returns jsonb
language plpgsql security definer set search_path = public, extensions stable
as $$
declare
  v_q text := lower(btrim(coalesce(p_query, '')));
  v_rows jsonb;
begin
  if not public.can_scout() then
    raise exception 'not authorized';
  end if;
  -- Same floor the client's other player search already uses ("Type at least
  -- 2 characters") — a 1-char query against a name column is a table scan
  -- that answers almost everyone.
  if length(v_q) < 2 then
    return '[]'::jsonb;
  end if;

  with hits as (
    select n.player_key,
           -- "Most recent" is judged by the EVENT date, not by when the row was
           -- last edited — a note fixed up months later should still surface
           -- the name/store as of the most recent time this person was seen,
           -- and every array_agg here shares that one ordering so the fields
           -- describe the same sighting.
           (array_agg(n.player_name order by coalesce(n.event_date, '-infinity'::timestamptz) desc, n.updated_at desc))[1] as best_identifier,
           (array_agg(n.rph_user_id order by coalesce(n.event_date, '-infinity'::timestamptz) desc, n.updated_at desc)
             filter (where n.rph_user_id is not null))[1] as rph_user_id,
           count(*) as n_entries,
           max(n.event_date) as last_event_date,
           (array_agg(n.event_tz   order by coalesce(n.event_date, '-infinity'::timestamptz) desc, n.updated_at desc))[1] as last_event_tz,
           (array_agg(n.event_name order by coalesce(n.event_date, '-infinity'::timestamptz) desc, n.updated_at desc))[1] as last_event_name,
           (array_agg(n.store_name order by coalesce(n.event_date, '-infinity'::timestamptz) desc, n.updated_at desc))[1] as last_store_name
      from public.scout_notes n
     where n.player_key like ('%' || v_q || '%')
        or lower(coalesce(n.player_name, '')) like ('%' || v_q || '%')
     group by n.player_key
  ),
  -- Same resolution join as get_roster_scout / get_scout_event: by lowercased
  -- display name, because elo_players carries no RPH user id of its own.
  resolved as (
    select h.*, lb.player_id, lb.current_rating, lb.rank,
           (lb.player_id is not null) as matched
      from hits h
      left join lateral (
             select coalesce(p2.merged_into_id, p1.merged_into_id, p1.player_id) as canon_id
               from public.elo_players p1
               left join public.elo_players p2 on p2.player_id = p1.merged_into_id
              where p1.platform = 'rph' and lower(p1.display_name) = lower(h.best_identifier)
              order by exists (select 1 from public.elo_ratings r
                                where r.player_id = coalesce(p2.merged_into_id, p1.merged_into_id, p1.player_id)) desc,
                       (p1.display_name = h.best_identifier) desc,
                       (p1.merged_into_id is null) desc, p1.player_id
              limit 1) p on true
      left join public.elo_leaderboard_v lb
             on lb.player_id = p.canon_id
     order by h.last_event_date desc nulls last, h.n_entries desc
     limit 30
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'player_key',      r.player_key,
           'best_identifier', r.best_identifier,
           'rph_user_id',     r.rph_user_id,
           'player_id',       r.player_id,
           'current_rating',  r.current_rating,
           'rank',            r.rank,
           'matched',         r.matched,
           'n_entries',       r.n_entries,
           'last_event_date', r.last_event_date,
           'last_event_tz',   r.last_event_tz,
           'last_event_name', r.last_event_name,
           'last_store_name', r.last_store_name
         ) order by r.last_event_date desc nulls last, r.n_entries desc), '[]'::jsonb)
    into v_rows
    from resolved r;

  return coalesce(v_rows, '[]'::jsonb);
end;
$$;

revoke all on function public.get_scout_event(bigint) from public, anon;
grant execute on function public.get_scout_event(bigint) to authenticated;
revoke all on function public.get_roster_scout(boolean) from public, anon;
grant execute on function public.get_roster_scout(boolean) to authenticated;
revoke all on function public.search_scout_players(text) from public, anon;
grant execute on function public.search_scout_players(text) to authenticated;

NOTIFY pgrst, 'reload schema';
