-- Public deck sharing primitives:
--   1. decks.visibility — 'private' (default, owner-only), 'unlisted'
--      (anyone with URL can view), 'public' (URL + discovery feed)
--   2. RLS updates so non-owners can read decks where visibility <> 'private'
--   3. public.profiles — display name + avatar mirror of auth.users metadata,
--      so the frontend can show "made by ..." without auth-admin access.
--      Synced on every sign-in from user_metadata.
--   4. public.deck_follows — for the "follow someone's deck" feature
--      (Phase B), so the user gets a saved list of decks to track.
--
-- Idempotent on re-run.

-- 1. decks.visibility -----------------------------------------------------
alter table public.decks add column if not exists visibility text not null
  default 'private'
  check (visibility in ('private', 'unlisted', 'public'));

-- Partial index: speeds up the public discovery feed without bloating the
-- index for the (much more common) owner queries on private decks.
create index if not exists decks_visibility_public_idx
  on public.decks (updated_at desc)
  where visibility = 'public';

-- 2. RLS rewrites ---------------------------------------------------------
-- Drop the existing "select own" policies and replace with policies that
-- also let anyone (including anon) read non-private decks. The deck UUID
-- is unguessable, so unlisted decks are effectively URL-gated despite the
-- RLS technically allowing anyone with the UUID to read them.
drop policy if exists "decks: select own" on public.decks;
drop policy if exists "decks: select visible" on public.decks;
create policy "decks: select visible"
  on public.decks for select
  using (auth.uid() = user_id OR visibility <> 'private');

drop policy if exists "deck_cards: select own"     on public.deck_cards;
drop policy if exists "deck_cards: select visible" on public.deck_cards;
create policy "deck_cards: select visible"
  on public.deck_cards for select
  using (exists (
    select 1 from public.decks d
    where d.id = deck_id
      and (d.user_id = auth.uid() OR d.visibility <> 'private')
  ));

-- Anon needs select grants on the underlying tables — without these,
-- PostgREST returns 401 before RLS even runs for unauthenticated visitors.
grant select on public.decks      to anon;
grant select on public.deck_cards to anon;

-- 3. profiles -------------------------------------------------------------
-- auth.users isn't queryable from PostgREST and we don't want to use the
-- auth-admin API client-side. Mirror the bits we need (display name +
-- avatar URL) into a public table, sync from user_metadata on each session.
create table if not exists public.profiles (
  user_id      uuid    primary key references auth.users(id) on delete cascade,
  display_name text,
  avatar_url   text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

alter table public.profiles enable row level security;

drop policy if exists "profiles: read all"   on public.profiles;
drop policy if exists "profiles: insert own" on public.profiles;
drop policy if exists "profiles: update own" on public.profiles;

create policy "profiles: read all"
  on public.profiles for select using (true);
create policy "profiles: insert own"
  on public.profiles for insert
  with check (auth.uid() = user_id);
create policy "profiles: update own"
  on public.profiles for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

grant select         on public.profiles to anon, authenticated;
grant insert, update on public.profiles to authenticated;

drop trigger if exists profiles_updated_at on public.profiles;
create trigger profiles_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

-- 4. deck_follows ---------------------------------------------------------
create table if not exists public.deck_follows (
  user_id     uuid    not null references auth.users(id) on delete cascade,
  deck_id     uuid    not null references public.decks(id) on delete cascade,
  followed_at timestamptz not null default now(),
  primary key (user_id, deck_id)
);

create index if not exists deck_follows_user_idx
  on public.deck_follows (user_id, followed_at desc);
-- For "how many followers does this deck have" aggregates later.
create index if not exists deck_follows_deck_idx
  on public.deck_follows (deck_id);

alter table public.deck_follows enable row level security;

drop policy if exists "deck_follows: read own"   on public.deck_follows;
drop policy if exists "deck_follows: insert own" on public.deck_follows;
drop policy if exists "deck_follows: delete own" on public.deck_follows;

create policy "deck_follows: read own"
  on public.deck_follows for select
  using (auth.uid() = user_id);
create policy "deck_follows: insert own"
  on public.deck_follows for insert
  with check (auth.uid() = user_id);
create policy "deck_follows: delete own"
  on public.deck_follows for delete
  using (auth.uid() = user_id);

grant select, insert, delete on public.deck_follows to authenticated;
