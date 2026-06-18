-- Per-user tracking of which of a booster pack's 3 cover-art variants the user
-- owns. TCGPlayer sells each set's pack as a single SKU (the 3 arts are NOT
-- separate products — they only appear bundled as "...Art Bundle [Set of 3]",
-- which we hide), so this is a manual completion checklist keyed on the pack's
-- tcgplayer_product_id + an art slot (1..3). A row means "owned"; the client
-- deletes the row to mark an art un-owned. No FK to sealed_products (same
-- survive-catalog-churn reasoning as sealed_collection_items).

create table if not exists public.sealed_pack_arts (
  user_id              uuid     not null references auth.users(id) on delete cascade,
  tcgplayer_product_id bigint   not null,
  art_index            smallint not null check (art_index between 1 and 3),
  updated_at           timestamptz not null default now(),
  primary key (user_id, tcgplayer_product_id, art_index)
);

create index if not exists sealed_pack_arts_user_idx
  on public.sealed_pack_arts (user_id);

alter table public.sealed_pack_arts enable row level security;

drop policy if exists "sealed_pack_arts: select own" on public.sealed_pack_arts;
drop policy if exists "sealed_pack_arts: insert own" on public.sealed_pack_arts;
drop policy if exists "sealed_pack_arts: delete own" on public.sealed_pack_arts;

create policy "sealed_pack_arts: select own"
  on public.sealed_pack_arts for select
  using (auth.uid() = user_id);

create policy "sealed_pack_arts: insert own"
  on public.sealed_pack_arts for insert
  with check (auth.uid() = user_id);

create policy "sealed_pack_arts: delete own"
  on public.sealed_pack_arts for delete
  using (auth.uid() = user_id);

grant select, insert, delete on public.sealed_pack_arts to authenticated;
grant select, insert, delete on public.sealed_pack_arts to service_role;

notify pgrst, 'reload schema';
