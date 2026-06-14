-- 68_elo_event_roster.sql
-- Scouting intel: who is signed up for each tracked Set Championship, joined to
-- their current ELO rating. Rosters are scraped server-side from the RPH
-- registrations endpoint (CORS-blocked, no client fetch) by
-- scripts/elo/scrape_rosters.py + the refresh-elo-rosters Edge Function.
--
-- The raw rosters are NOT publicly readable (they're competitive recon). The
-- only read path is get_event_roster(), gated on can_view_store_report()
-- (admins + elo_report_viewers), mirroring the store-scouting report (mig 66).
-- Idempotent; safe to re-run.

-- ── Roster header: one row per scraped event ────────────────────────────────
create table if not exists public.elo_event_roster (
  event_id         bigint primary key references public.set_championships(event_id) on delete cascade,
  registered_count int,
  capacity         int,
  scraped_at       timestamptz not null default now()
);

-- ── Roster members: one row per signed-up player per event ──────────────────
-- best_identifier is the TV/tournament display name — the join key into
-- elo_players.display_name. rph_user_id is the stable RPH account id (kept for
-- future cross-event identity stitching even when best_identifier varies).
create table if not exists public.elo_event_roster_members (
  event_id            bigint not null references public.elo_event_roster(event_id) on delete cascade,
  rph_user_id         bigint,
  best_identifier     text not null,
  account_name        text,
  registration_status text,
  primary key (event_id, best_identifier)
);
create index if not exists elo_event_roster_members_event_idx
  on public.elo_event_roster_members (event_id);
create index if not exists elo_event_roster_members_ident_idx
  on public.elo_event_roster_members (lower(best_identifier));

-- ── RLS: enabled, NO public policies (read only via the gated RPC below) ─────
alter table public.elo_event_roster         enable row level security;
alter table public.elo_event_roster_members enable row level security;

-- service_role bypasses RLS but does NOT inherit table privileges implicitly
-- (per CLAUDE.md matview/grant trap) — the scraper writes with the service key.
grant select, insert, update, delete on public.elo_event_roster         to service_role;
grant select, insert, update, delete on public.elo_event_roster_members to service_role;

-- ── Gated read: full roster for one event, joined to current ELO ────────────
-- Returns a single jsonb blob: event header, field-strength aggregates (over
-- RATED members only), and the player list ordered by current rating desc.
-- Match each member to elo_players by case-insensitive display_name on the rph
-- platform, resolve the canonical id (merged_into_id), then to elo_leaderboard_v
-- for rating/rank/record. p_exclude_org drops the two I&L org accounts from both
-- the player list and the aggregates.
drop function if exists public.get_event_roster(bigint, boolean);
create function public.get_event_roster(p_event_id bigint, p_exclude_org boolean default false)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
stable
as $$
declare
  v_org_names constant text[] := array['I&L⟡Zaven', 'I&L⟡jacobayy'];
  v_event  jsonb;
  v_field  jsonb;
  v_players jsonb;
begin
  if not public.can_view_store_report() then
    raise exception 'not authorized';
  end if;

  -- One resolved row per roster member, joined to canonical player + rating.
  with members as (
    select m.best_identifier,
           m.account_name,
           m.rph_user_id
      from public.elo_event_roster_members m
     where m.event_id = p_event_id
  ),
  resolved as (
    select mb.best_identifier,
           mb.account_name,
           lb.player_id,
           lb.current_rating,
           lb.rank,
           lb.wins,
           lb.losses,
           (lb.player_id is not null) as matched,
           lb.display_name as canonical_name
      from members mb
      -- match the registration name to a player on the rph platform
      left join public.elo_players p
             on p.platform = 'rph'
            and lower(p.display_name) = lower(mb.best_identifier)
      -- resolve aliases to the canonical player, then to the leaderboard row
      left join public.elo_leaderboard_v lb
             on lb.player_id = coalesce(p.merged_into_id, p.player_id)
  ),
  filtered as (
    select *
      from resolved
     where not (p_exclude_org and canonical_name = any(v_org_names))
  )
  select
    -- player list (ordered by rating, unrated last)
    coalesce(jsonb_agg(
      jsonb_build_object(
        'best_identifier', f.best_identifier,
        'account_name',    f.account_name,
        'player_id',       f.player_id,
        'current_rating',  f.current_rating,
        'rank',            f.rank,
        'wins',            f.wins,
        'losses',          f.losses,
        'matched',         f.matched
      )
      order by f.current_rating desc nulls last, f.best_identifier asc
    ), '[]'::jsonb),
    -- field-strength aggregates over RATED members only
    jsonb_build_object(
      'n_signed_up', count(*),
      'n_rated',     count(*) filter (where f.matched),
      'n_unrated',   count(*) filter (where not f.matched),
      'avg_elo',     round(avg(f.current_rating) filter (where f.matched)::numeric, 1),
      'median_elo',  round((percentile_cont(0.5) within group (order by f.current_rating)
                              filter (where f.matched))::numeric, 1),
      'top_elo',     round(max(f.current_rating) filter (where f.matched)::numeric, 1)
    )
  into v_players, v_field
  from filtered f;

  -- event header from set_championships ⋈ roster (roster header carries the
  -- scrape metadata; LEFT join so an unscraped tracked event still returns).
  select jsonb_build_object(
           'event_id',        sc.event_id,
           'name',            sc.name,
           'store_name',      sc.store_name,
           'start_datetime',  sc.start_datetime,
           'capacity',        coalesce(r.capacity, sc.capacity),
           'registered_count',coalesce(r.registered_count, sc.registered_user_count),
           'scraped_at',      r.scraped_at
         )
    into v_event
    from public.set_championships sc
    left join public.elo_event_roster r on r.event_id = sc.event_id
   where sc.event_id = p_event_id;

  return jsonb_build_object(
    'event',   coalesce(v_event, jsonb_build_object('event_id', p_event_id)),
    'field',   coalesce(v_field, jsonb_build_object(
                 'n_signed_up', 0, 'n_rated', 0, 'n_unrated', 0,
                 'avg_elo', null, 'median_elo', null, 'top_elo', null)),
    'players', coalesce(v_players, '[]'::jsonb)
  );
end;
$$;

revoke all on function public.get_event_roster(bigint, boolean) from public;
grant execute on function public.get_event_roster(bigint, boolean) to authenticated;

notify pgrst, 'reload schema';
