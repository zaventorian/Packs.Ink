-- Migration 127: watchlists.
--
-- A saved Screener view saves a QUERY — "every Enchanted that moved 25% this
-- week". Every professional screening tool also saves a LIST: these eleven
-- specific cards, which I picked, which I want to see together. Those are
-- different objects and the second one has no home in this schema today. It is
-- also the thing everything else hangs off — the compare-graph handoff, price
-- alerts (migration 128), and a future cost-basis column all want "the user's
-- named set of instruments" to already exist.
--
-- Shape: one row per list, one row per item. Items key on
-- (card_id, printing) because that is what identifies a tradable thing on this
-- site — the same key `collection_items` and `deck_cards` use. A card_id alone
-- would merge a Cold Foil and its non-foil, which are different markets and
-- often differ 10x in price.
--
-- Sealed products live in the same list. They have no card_id, so `card_id` is
-- nullable and `tcgplayer_product_id` carries them; exactly one of the two must
-- be set, enforced by a CHECK. Keeping sealed in the same table (rather than a
-- parallel one) is what lets "graph this watchlist" hand a mixed list to Price
-- Graphing, which already accepts mixed compare items.
--
-- Idempotent.

create table if not exists public.watchlists (
  id          uuid    primary key default gen_random_uuid(),
  user_id     uuid    not null references auth.users(id) on delete cascade,
  name        text    not null check (length(trim(name)) > 0 and length(name) <= 80),
  -- Display order in the chip strip. Ties break on created_at.
  position    int     not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  -- One list per name per user, so "star into Watchlist" is an upsert target
  -- and a rename can't silently produce two lists that look identical.
  unique (user_id, name)
);

create index if not exists watchlists_user_idx
  on public.watchlists (user_id, position, created_at);

create table if not exists public.watchlist_items (
  watchlist_id uuid   not null references public.watchlists(id) on delete cascade,
  -- crd_<hex> for a card; null for a sealed product.
  card_id      text,
  -- "Normal" / "Cold Foil" / "Holofoil" / … Not null even for sealed (which is
  -- always "Normal") so the primary key never has to deal with a null column:
  -- in Postgres, nulls in a PK are impossible, and in a UNIQUE they'd let the
  -- same product be added repeatedly.
  printing     text   not null default 'Normal',
  -- Set for sealed products; also stored for cards so the client can build a
  -- price-history fetch without a catalog round-trip.
  tcgplayer_product_id int,
  -- Free-text reason the item is on the list ("watching for a reprint dip").
  note         text   check (note is null or length(note) <= 500),
  added_at     timestamptz not null default now(),
  primary key (watchlist_id, card_id, printing),
  constraint watchlist_items_identifies_something
    check (card_id is not null or tcgplayer_product_id is not null)
);

create index if not exists watchlist_items_list_idx
  on public.watchlist_items (watchlist_id, added_at desc);

-- ── RLS ─────────────────────────────────────────────────────────────────
-- Owner-only on both tables. watchlist_items has no user_id of its own, so its
-- policies reach through to the parent list — which is also why the parent's
-- ON DELETE CASCADE matters: deleting a list must not strand its items behind
-- a policy that can no longer find an owner for them.
--
-- auth.uid() is wrapped in (select …) per migration 91: an unwrapped call is
-- re-evaluated per row (auth_rls_initplan), which on a list of a few hundred
-- items is the difference between one call and a few hundred.

alter table public.watchlists      enable row level security;
alter table public.watchlist_items enable row level security;

drop policy if exists "watchlists: select own" on public.watchlists;
drop policy if exists "watchlists: insert own" on public.watchlists;
drop policy if exists "watchlists: update own" on public.watchlists;
drop policy if exists "watchlists: delete own" on public.watchlists;

create policy "watchlists: select own"
  on public.watchlists for select
  using ((select auth.uid()) = user_id);

create policy "watchlists: insert own"
  on public.watchlists for insert
  with check ((select auth.uid()) = user_id);

create policy "watchlists: update own"
  on public.watchlists for update
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "watchlists: delete own"
  on public.watchlists for delete
  using ((select auth.uid()) = user_id);

drop policy if exists "watchlist_items: select own" on public.watchlist_items;
drop policy if exists "watchlist_items: insert own" on public.watchlist_items;
drop policy if exists "watchlist_items: update own" on public.watchlist_items;
drop policy if exists "watchlist_items: delete own" on public.watchlist_items;

create policy "watchlist_items: select own"
  on public.watchlist_items for select
  using (exists (
    select 1 from public.watchlists w
    where w.id = watchlist_id and w.user_id = (select auth.uid())
  ));

create policy "watchlist_items: insert own"
  on public.watchlist_items for insert
  with check (exists (
    select 1 from public.watchlists w
    where w.id = watchlist_id and w.user_id = (select auth.uid())
  ));

create policy "watchlist_items: update own"
  on public.watchlist_items for update
  using (exists (
    select 1 from public.watchlists w
    where w.id = watchlist_id and w.user_id = (select auth.uid())
  ))
  with check (exists (
    select 1 from public.watchlists w
    where w.id = watchlist_id and w.user_id = (select auth.uid())
  ));

create policy "watchlist_items: delete own"
  on public.watchlist_items for delete
  using (exists (
    select 1 from public.watchlists w
    where w.id = watchlist_id and w.user_id = (select auth.uid())
  ));

-- ⚠ A new relation grants NOTHING implicitly. Migration 125 created
-- deck_versions with correct RLS and no GRANT, so an owner reading their own
-- history got a flat 403 (42501) before RLS was ever consulted, and 126 had to
-- follow. Same rule CLAUDE.md already states for matviews. Do not split these.
grant select, insert, update, delete on public.watchlists      to authenticated;
grant select, insert, update, delete on public.watchlist_items to authenticated;
grant select, insert, update, delete on public.watchlists      to service_role;
grant select, insert, update, delete on public.watchlist_items to service_role;

drop trigger if exists watchlists_updated_at on public.watchlists;
create trigger watchlists_updated_at
  before update on public.watchlists
  for each row execute function public.set_updated_at();

notify pgrst, 'reload schema';
