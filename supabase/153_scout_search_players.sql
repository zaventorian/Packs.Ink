-- 153_scout_search_players.sql — search every player scouting has ever logged,
-- not just an upcoming Set Championship's roster.
--
-- The Scout tab's "Search player" mode (EloRosterScout) only ever searched the
-- players get_roster_scout() already had loaded — every UPCOMING tracked Set
-- Championship's signed-up roster. Clicking a hit there opened the Elo
-- profile, never what the team had actually written down for them. So a
-- player who had dropped their registration, played a league night instead,
-- or was scouted at an event that has since passed was invisible to this
-- search — exactly the players a scouting note exists to remember.
--
-- search_scout_players reads scout_notes directly (every logged entry, any
-- event, any date) and groups by player_key — the same identity
-- save_scout_note already keys on (migration 143) — so a hit here always has
-- something to show via get_scout_player. Gated the same as everything else
-- in 143: can_scout() only, so a store-report viewer who is not a scout still
-- gets a flat refusal rather than a name list.
--
-- Idempotent; safe to re-run.

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
      left join public.elo_players p
             on p.platform = 'rph' and lower(p.display_name) = lower(h.best_identifier)
      left join public.elo_leaderboard_v lb
             on lb.player_id = coalesce(p.merged_into_id, p.player_id)
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
revoke all on function public.search_scout_players(text) from public, anon;
grant execute on function public.search_scout_players(text) to authenticated;

notify pgrst, 'reload schema';
