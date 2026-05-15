-- Phase B revision:
--   * Rename deck_follows -> deck_favorites. The old name conflated "save
--     this deck" (a bookmark) with the new "follow this creator" concept,
--     so we split them. Favorites stay scoped to (user, deck); follows
--     are now scoped to (follower, creator).
--   * Introduce public.user_follows for the creator-feed feature: a user
--     follows other users, and the Decks tab's Following section becomes
--     a chronological feed of recent public decks from those creators.
--
-- Idempotent: safe to re-run. The rename is no-op if it's already happened.

-- 1. Rename deck_follows -> deck_favorites --------------------------------
do $$
begin
  if exists (select 1 from pg_tables where schemaname='public' and tablename='deck_follows')
     and not exists (select 1 from pg_tables where schemaname='public' and tablename='deck_favorites')
  then
    execute 'alter table public.deck_follows rename to deck_favorites';
  end if;
  -- Rename related indexes if they still bear the old names.
  if exists (select 1 from pg_indexes where schemaname='public' and indexname='deck_follows_user_idx') then
    execute 'alter index public.deck_follows_user_idx rename to deck_favorites_user_idx';
  end if;
  if exists (select 1 from pg_indexes where schemaname='public' and indexname='deck_follows_deck_idx') then
    execute 'alter index public.deck_follows_deck_idx rename to deck_favorites_deck_idx';
  end if;
end $$;

-- Drop policies (old name) if they survived the rename, then create new.
drop policy if exists "deck_follows: read own"     on public.deck_favorites;
drop policy if exists "deck_follows: insert own"   on public.deck_favorites;
drop policy if exists "deck_follows: delete own"   on public.deck_favorites;
drop policy if exists "deck_favorites: read own"   on public.deck_favorites;
drop policy if exists "deck_favorites: insert own" on public.deck_favorites;
drop policy if exists "deck_favorites: delete own" on public.deck_favorites;

create policy "deck_favorites: read own"
  on public.deck_favorites for select using (auth.uid() = user_id);
create policy "deck_favorites: insert own"
  on public.deck_favorites for insert with check (auth.uid() = user_id);
create policy "deck_favorites: delete own"
  on public.deck_favorites for delete using (auth.uid() = user_id);

grant select, insert, delete on public.deck_favorites to authenticated;

-- 2. user_follows ---------------------------------------------------------
create table if not exists public.user_follows (
  follower_id  uuid not null references auth.users(id) on delete cascade,
  followed_id  uuid not null references auth.users(id) on delete cascade,
  followed_at  timestamptz not null default now(),
  primary key (follower_id, followed_id),
  check (follower_id <> followed_id)
);

create index if not exists user_follows_follower_idx
  on public.user_follows (follower_id, followed_at desc);
-- Reverse direction for "how many people follow this creator" aggregates.
create index if not exists user_follows_followed_idx
  on public.user_follows (followed_id);

alter table public.user_follows enable row level security;

drop policy if exists "user_follows: read own"   on public.user_follows;
drop policy if exists "user_follows: insert own" on public.user_follows;
drop policy if exists "user_follows: delete own" on public.user_follows;

-- Both sides of the relationship can read it: followers see who they
-- follow, creators can see their follower count (useful later).
create policy "user_follows: read own"
  on public.user_follows for select
  using (auth.uid() = follower_id OR auth.uid() = followed_id);
create policy "user_follows: insert own"
  on public.user_follows for insert
  with check (auth.uid() = follower_id);
create policy "user_follows: delete own"
  on public.user_follows for delete
  using (auth.uid() = follower_id);

grant select, insert, delete on public.user_follows to authenticated;
