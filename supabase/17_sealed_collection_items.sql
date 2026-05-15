-- Per-user sealed-product collection. Parallel structure to collection_items,
-- but keyed on tcgplayer_product_id (sealed has no Lorcast card_id).
--
-- Like collection_items, no FK to sealed_products — if a TCGPlayer SKU is
-- ever removed from our catalog, the user's owned record should survive.
-- (Same reasoning as 11_drop_collection_card_fk.sql for cards.)

create table if not exists public.sealed_collection_items (
  user_id              uuid    not null references auth.users(id) on delete cascade,
  tcgplayer_product_id bigint  not null,
  -- Sealed product is effectively NM/sealed-in-box; condition column kept
  -- for shape-parity with collection_items so the PK pattern is consistent.
  condition            text    not null default 'NM',
  quantity             int     not null default 1 check (quantity >= 0),
  notes                text,
  added_at             timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  primary key (user_id, tcgplayer_product_id, condition)
);

-- Hot path: "my sealed sorted by recency"
create index if not exists sealed_collection_items_user_idx
  on public.sealed_collection_items (user_id, updated_at desc);

alter table public.sealed_collection_items enable row level security;

drop policy if exists "sealed_collection_items: select own" on public.sealed_collection_items;
drop policy if exists "sealed_collection_items: insert own" on public.sealed_collection_items;
drop policy if exists "sealed_collection_items: update own" on public.sealed_collection_items;
drop policy if exists "sealed_collection_items: delete own" on public.sealed_collection_items;

create policy "sealed_collection_items: select own"
  on public.sealed_collection_items for select
  using (auth.uid() = user_id);

create policy "sealed_collection_items: insert own"
  on public.sealed_collection_items for insert
  with check (auth.uid() = user_id);

create policy "sealed_collection_items: update own"
  on public.sealed_collection_items for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "sealed_collection_items: delete own"
  on public.sealed_collection_items for delete
  using (auth.uid() = user_id);

grant select, insert, update, delete on public.sealed_collection_items to authenticated;
grant select, insert, update, delete on public.sealed_collection_items to service_role;

drop trigger if exists sealed_collection_items_updated_at on public.sealed_collection_items;
create trigger sealed_collection_items_updated_at
  before update on public.sealed_collection_items
  for each row execute function public.set_updated_at();
