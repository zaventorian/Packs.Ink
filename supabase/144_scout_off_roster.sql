-- 144_scout_off_roster.sql — a note must never be invisible on the event it
-- was written about, and you must be able to log somebody RPH has never heard of.
--
-- 143's get_scout_event listed exactly the roster: `elo_event_roster_members`
-- for the event, joined to a note. That is wrong in both directions, and the
-- first one is a SILENT data-hiding bug rather than a missing feature:
--
--   ⚠ The roster scrape is DELETE-then-INSERT (scrape_rosters.py / the edge
--     function both replace the whole member list, so a dropped registration
--     disappears — which is the behaviour we want for a roster). So the moment a
--     player drops, every note the team wrote about them AT THAT EVENT stopped
--     rendering on it. The row was still there, and still showed in the player's
--     own history, which makes it worse: the data is fine and the panel quietly
--     disagrees. There is no error, no empty state, nothing to notice.
--
--   · And a scouting tool that can only describe people RPH already knows about
--     is half a tool. Someone playing who was never entered into the system, a
--     player you met at another shop, a name you want to start a file on — all
--     of that is a `name:<lowercased>` key, which scout_player_key already
--     produces and save_scout_note already accepts. The only thing missing was
--     somewhere for it to show up.
--
-- So: the panel's list is the UNION of the roster and this event's notes, with
-- `off_roster` telling them apart. Everything else about 143 is unchanged —
-- same gate, same tracked-store scope, same one-row-per-(event, player) key.
--
-- Also here: removing a scout member by id, so the admin panel's Remove button
-- works on a row added by user_id rather than email (143 could only remove by
-- email, so that row had a button that did nothing).
--
-- Idempotent; safe to re-run. Requires 143.

-- ── The panel's read, widened ──────────────────────────────────────────────
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
    'registered_count', r.registered_count
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

-- ── Remove a member by id ──────────────────────────────────────────────────
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
