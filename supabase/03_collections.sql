-- Packs.Ink collections schema
-- Adds per-user card collection tracking. Idempotent — safe to re-run.

-- ──────────────────────────────────────────────────────────────────────────
-- collection_items: one row per (user, card, printing, condition).
-- Quantity tracks how many copies the user owns.
-- ──────────────────────────────────────────────────────────────────────────
create table if not exists public.collection_items (
  user_id     uuid    not null references auth.users(id) on delete cascade,
  card_id     text    not null references public.cards(id)   on delete cascade,
  printing    text    not null,                 -- 'Normal' | 'Cold Foil' | 'Holofoil'
  condition   text    not null default 'NM',    -- 'NM' | 'LP' | 'MP' | 'HP' | 'DMG'
  quantity    int     not null default 1 check (quantity >= 0),
  notes       text,
  added_at    timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (user_id, card_id, printing, condition)
);

create index if not exists collection_items_user_idx
  on public.collection_items (user_id);
create index if not exists collection_items_card_idx
  on public.collection_items (card_id);

-- ──────────────────────────────────────────────────────────────────────────
-- Row Level Security: each user sees / mutates only their own rows.
-- ──────────────────────────────────────────────────────────────────────────
alter table public.collection_items enable row level security;

drop policy if exists "collection_items: select own" on public.collection_items;
drop policy if exists "collection_items: insert own" on public.collection_items;
drop policy if exists "collection_items: update own" on public.collection_items;
drop policy if exists "collection_items: delete own" on public.collection_items;

create policy "collection_items: select own"
  on public.collection_items for select
  using (auth.uid() = user_id);

create policy "collection_items: insert own"
  on public.collection_items for insert
  with check (auth.uid() = user_id);

create policy "collection_items: update own"
  on public.collection_items for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "collection_items: delete own"
  on public.collection_items for delete
  using (auth.uid() = user_id);

-- ──────────────────────────────────────────────────────────────────────────
-- Grants (we have "auto-expose new tables" off, so this is required)
-- ──────────────────────────────────────────────────────────────────────────
grant select, insert, update, delete on public.collection_items to authenticated;
grant select, insert, update, delete on public.collection_items to service_role;

-- ──────────────────────────────────────────────────────────────────────────
-- updated_at trigger
-- ──────────────────────────────────────────────────────────────────────────
drop trigger if exists collection_items_updated_at on public.collection_items;
create trigger collection_items_updated_at
  before update on public.collection_items
  for each row execute function public.set_updated_at();
