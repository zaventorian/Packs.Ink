-- 147_scout_window_24h.sql — the Scout tab keeps an event for 24 hours past its
-- start, instead of dropping it the minute the doors open.
--
-- 143's get_roster_scout scoped its slate to `sc.start_datetime >= now()`, so an
-- event vanished from Roster Scout at the exact moment it became the one you are
-- standing in. Reported from the floor 2026-09-12: three 3:00 PM Set
-- Championships were on the tab at 2:59 and gone at 3:00, which is precisely
-- backwards — the whole point of a scouting sheet is that you fill it in DURING
-- the event and finish it on the drive home.
--
-- So the window is `now() - interval '24 hours'`. Twenty-four hours because a
-- day's play plus the evening you write it up is the real working life of a
-- sheet, and because a fixed interval is the same length of grace whatever time
-- the event started — see the note below on why the date-based filters elsewhere
-- are not that.
--
-- ⚠ This is the ONLY thing 147 changes. The body is 143's verbatim otherwise:
-- same gate (can_view_store_report OR can_scout), same tracked-store join, same
-- LEFT JOIN onto the roster so an unpulled event is still listed, same player
-- resolution and field aggregates.
--
-- ⚠ Deliberately NOT widened: the BULK roster sweep (the "Refresh all rosters"
-- button's edge function, and scrape_rosters.py's scheduled run), which still
-- scopes to `start_datetime >= today`. Those replace a roster delete-then-insert,
-- so pointing the automatic sweep at events that have already been played risks
-- overwriting the roster of the very event somebody is taking notes on with
-- whatever RPH's registration list says afterwards. The per-event refresh — the
-- ↻ button inside a sheet, and scrape_rosters.py --event — resolves through
-- scout_event_meta and has never had a date filter, so refreshing the event you
-- are sitting in already works and is the right tool for it.
--
-- Ordering: independent of 144_scout_off_roster.sql, which re-creates
-- get_scout_event and never touches this function. Either may land first.
--
-- Idempotent; safe to re-run. Requires 143.

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

  with ev as (
    select sc.event_id, sc.name, sc.store_name, sc.city, sc.state,
           sc.start_datetime, sc.set_name, sc.timezone,
           coalesce(r.capacity, sc.capacity)                  as capacity,
           coalesce(r.registered_count, sc.registered_user_count) as registered_count,
           r.scraped_at
      from public.set_championships sc
      join public.elo_tracked_stores t on t.store_id = sc.store_id
      left join public.elo_event_roster r on r.event_id = sc.event_id
     where sc.start_datetime >= now() - interval '24 hours'
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
             e.start_datetime, e.timezone, e.capacity, e.registered_count, e.scraped_at
  )
  select coalesce(jsonb_agg(ev_json order by start_datetime asc), '[]'::jsonb)
    into v_result
    from per_event;

  return coalesce(v_result, '[]'::jsonb);
end;
$$;

revoke all on function public.get_roster_scout(boolean) from public, anon;
grant execute on function public.get_roster_scout(boolean) to authenticated;

notify pgrst, 'reload schema';
