-- Per-deck unique-viewer tracking. Drives the "👁 N" badge on deck cards.
-- "Unique" = unique logged-in user. Anonymous viewers don't count; a user
-- viewing the same deck twice doesn't double-count (the PK enforces this).
-- The owner's own views are filtered out client-side, not in the DB —
-- keeping the table flexible for future "who viewed my deck" features.

create table if not exists public.deck_views (
  user_id    uuid        not null references auth.users(id) on delete cascade,
  deck_id    uuid        not null references public.decks(id) on delete cascade,
  viewed_at  timestamptz not null default now(),
  primary key (user_id, deck_id)
);

create index if not exists deck_views_deck_idx
  on public.deck_views (deck_id);

alter table public.deck_views enable row level security;

-- Insert your own view row, idempotent (ON CONFLICT DO NOTHING from the
-- client). No select policy: the frontend never reads individual view rows;
-- aggregate counts come from the SECURITY DEFINER RPC below.
drop policy if exists "deck_views: insert own" on public.deck_views;
create policy "deck_views: insert own"
  on public.deck_views for insert
  with check (auth.uid() = user_id);

grant insert on public.deck_views to authenticated;

-- Aggregate counts. Same pattern as deck_favorite_counts — bypass RLS to
-- expose just the totals. Anon can call too, returning 0 for everything
-- (they never inserted a row), which is fine.
create or replace function public.deck_view_counts(deck_ids uuid[])
returns table(deck_id uuid, view_count bigint)
language sql
security definer
set search_path = public, extensions, pg_catalog
as $$
  select deck_id, count(*)::bigint as view_count
    from public.deck_views
   where deck_id = any(deck_ids)
   group by deck_id;
$$;

revoke all on function public.deck_view_counts(uuid[]) from public;
grant  execute on function public.deck_view_counts(uuid[]) to anon, authenticated;

notify pgrst, 'reload schema';
