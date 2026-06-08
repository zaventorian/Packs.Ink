-- 59_elo_official_standings.sql
--
-- Pull the official per-event placement (and full W/L/D record including
-- byes) from the RPH / melee platform standings APIs instead of computing
-- our own. Our local rank by `(points DESC, wins DESC)` was wrong on two
-- counts: (1) it discards byes from the record, undercounting wins for
-- players who got a R1 bye; (2) it doesn't apply OMW% tiebreakers or
-- respect bracket-cut champions, so a Final winner could end up #2.
--
-- elo_event_standings_v now LEFT JOINs the official table and prefers
-- those values when available; falls back to the computed numbers
-- otherwise (e.g. an event we haven't backfilled yet).

create table if not exists public.elo_event_standings_official (
  event_id        integer not null references public.elo_events(event_id) on delete cascade,
  player_id       integer not null references public.elo_players(player_id),
  place           integer not null,
  matches_won     integer,
  matches_lost    integer,
  matches_drawn   integer,
  match_points    integer,
  mw_pct          numeric,
  omw_pct         numeric,
  gw_pct          numeric,
  fetched_at      timestamptz not null default now(),
  primary key (event_id, player_id)
);
create index if not exists elo_event_standings_official_event_idx
  on public.elo_event_standings_official (event_id);

alter table public.elo_event_standings_official enable row level security;
drop policy if exists "elo_eso_public_read" on public.elo_event_standings_official;
create policy "elo_eso_public_read"
  on public.elo_event_standings_official for select to anon, authenticated using (true);
drop policy if exists "elo_eso_admin_write" on public.elo_event_standings_official;
create policy "elo_eso_admin_write"
  on public.elo_event_standings_official for all to authenticated
  using (public.is_elo_admin(auth.uid()))
  with check (public.is_elo_admin(auth.uid()));

grant select on public.elo_event_standings_official
  to anon, authenticated, service_role;
grant insert, update, delete on public.elo_event_standings_official
  to authenticated, service_role;

-- Replace the view: prefer the official record when available, fall back
-- to our computed numbers for events we haven't backfilled.
drop view if exists public.elo_event_standings_v;
create view public.elo_event_standings_v
  with (security_invoker = on)
as
with per_event as (
  select rt.player_id, m.event_id,
         count(*) filter (where rt.score = 1.0) as wins,
         count(*) filter (where rt.score = 0.0) as losses,
         count(*) filter (where rt.score = 0.5) as draws,
         sum(case when m.player1_id = rt.player_id then coalesce(m.games_won_p1,0)
                  when m.player2_id = rt.player_id then coalesce(m.games_won_p2,0)
                  else 0 end) as games_won,
         sum(case when m.player1_id = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                  when m.player2_id = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                  else 0 end) as total_games,
         (array_agg(rt.rating_after order by rt.rating_id desc))[1] as end_rating
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  group by rt.player_id, m.event_id
)
select pe.event_id,
       pe.player_id,
       p.display_name,
       p.platform,
       coalesce(off.matches_won,  pe.wins)   as wins,
       coalesce(off.matches_lost, pe.losses) as losses,
       coalesce(off.matches_drawn, pe.draws) as draws,
       coalesce(off.match_points, pe.wins*3 + pe.draws) as points,
       case when pe.total_games > 0
            then round((pe.games_won::numeric / pe.total_games) * 100, 1)
            else null end as gw_pct,
       coalesce(off.mw_pct,
                case when (coalesce(off.matches_won, pe.wins)
                         + coalesce(off.matches_lost, pe.losses)
                         + coalesce(off.matches_drawn, pe.draws)) > 0
                     then round(
                       ((coalesce(off.matches_won, pe.wins)
                         + 0.5 * coalesce(off.matches_drawn, pe.draws))::numeric
                       / (coalesce(off.matches_won, pe.wins)
                          + coalesce(off.matches_lost, pe.losses)
                          + coalesce(off.matches_drawn, pe.draws))) * 100, 1)
                     else null end) as mw_pct,
       off.omw_pct,
       pe.end_rating,
       coalesce(off.place,
                rank() over (partition by pe.event_id
                             order by (pe.wins * 3 + pe.draws) desc, pe.wins desc)
       ) as event_rank
  from per_event pe
  join public.elo_players p on p.player_id = pe.player_id
  left join public.elo_event_standings_official off
    on off.event_id = pe.event_id and off.player_id = pe.player_id;

grant select on public.elo_event_standings_v to anon, authenticated, service_role;

notify pgrst, 'reload schema';
