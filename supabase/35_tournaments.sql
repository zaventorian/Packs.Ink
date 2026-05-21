-- 35_tournaments.sql — tournament results + admin-gated bulk upload.
--
-- The tournament-decks feature lets approved users bulk-upload a set of
-- decks that played in a tournament. Each upload creates one tournaments
-- row + one tournament_decks row per player, and each tournament_decks
-- row references a `decks` row (created by the uploader, owned by them
-- for write-permission purposes, but DISPLAYED publicly as the player's
-- deck — see tournament_decks.player_name).
--
-- The deck stays publicly visible (decks.visibility = 'public') so it
-- appears in the standard Discover feed AND under its tournament page.

create table if not exists public.tournaments (
  id           uuid primary key default gen_random_uuid(),
  name         text not null,
  event_date   date,
  uploaded_by  uuid references auth.users(id) on delete set null,
  format       text,                       -- 'core' | 'infinity' | null
  inserted_at  timestamptz not null default now()
);
create index if not exists tournaments_inserted_idx on public.tournaments (inserted_at desc);
create index if not exists tournaments_event_idx    on public.tournaments (event_date desc nulls last);

create table if not exists public.tournament_decks (
  id            uuid primary key default gen_random_uuid(),
  tournament_id uuid not null references public.tournaments(id) on delete cascade,
  deck_id       uuid references public.decks(id) on delete cascade,
  place         text,                      -- '1st' | 'Top 8' | etc. (display label)
  place_rank    integer,                   -- numeric for sort: 1=first, 2=second, 8=Top 8, ...
  player_name   text,
  inserted_at   timestamptz not null default now()
);
create index if not exists tournament_decks_tournament_idx on public.tournament_decks (tournament_id, place_rank);
create index if not exists tournament_decks_deck_idx on public.tournament_decks (deck_id);

-- Admin allowlist. Insert a row keyed by auth.users.id for each user you
-- want to grant tournament-upload privileges to. The site reads this via
-- is_tournament_admin() below.
create table if not exists public.tournament_admins (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  granted_at timestamptz not null default now()
);

create or replace function public.is_tournament_admin(p_user uuid)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (select 1 from public.tournament_admins where user_id = p_user)
$$;

-- RLS:
--   tournaments / tournament_decks: anyone can SELECT (public feature);
--     only admins can INSERT/UPDATE/DELETE.
--   tournament_admins: nobody can read or write through the API
--     (manage rows manually via the Supabase dashboard).

alter table public.tournaments       enable row level security;
alter table public.tournament_decks  enable row level security;
alter table public.tournament_admins enable row level security;

drop policy if exists "tournaments_public_read" on public.tournaments;
create policy "tournaments_public_read"
  on public.tournaments for select to anon, authenticated using (true);

drop policy if exists "tournaments_admin_write" on public.tournaments;
create policy "tournaments_admin_write"
  on public.tournaments for all to authenticated
  using (public.is_tournament_admin(auth.uid()))
  with check (public.is_tournament_admin(auth.uid()));

drop policy if exists "tournament_decks_public_read" on public.tournament_decks;
create policy "tournament_decks_public_read"
  on public.tournament_decks for select to anon, authenticated using (true);

drop policy if exists "tournament_decks_admin_write" on public.tournament_decks;
create policy "tournament_decks_admin_write"
  on public.tournament_decks for all to authenticated
  using (public.is_tournament_admin(auth.uid()))
  with check (public.is_tournament_admin(auth.uid()));

grant select on public.tournaments, public.tournament_decks
  to anon, authenticated;
grant insert, update, delete on public.tournaments, public.tournament_decks
  to authenticated;
grant execute on function public.is_tournament_admin(uuid) to anon, authenticated;

-- Convenience view: tournament_decks joined with the deck name + visibility.
-- Read-only, anon-friendly. Used by the Tournament results page + home banner.
drop view if exists public.tournament_results_v;
create view public.tournament_results_v
  with (security_invoker = on)
as
select td.id            as result_id,
       td.tournament_id,
       t.name           as tournament_name,
       t.event_date     as event_date,
       t.format         as tournament_format,
       td.place,
       td.place_rank,
       td.player_name,
       td.inserted_at   as result_inserted_at,
       d.id             as deck_id,
       d.name           as deck_name,
       d.user_id        as deck_owner_id,
       d.visibility     as deck_visibility,
       d.inks           as deck_inks,
       d.share_token    as deck_share_token,
       d.updated_at     as deck_updated_at
  from public.tournament_decks td
  join public.tournaments t on t.id = td.tournament_id
  left join public.decks d on d.id = td.deck_id;

grant select on public.tournament_results_v to anon, authenticated;

notify pgrst, 'reload schema';
