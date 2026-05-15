-- Sealed product catalog (booster boxes, packs, starter decks, gift sets,
-- Illumineer's Troves, Quests, etc.). Kept separate from `cards` because:
--   - sealed has no rarity/ink/cost/inkable — would force every cards column
--     to be nullable and break transformSupabaseData's invariants
--   - join semantics differ — sealed is one-row-per-product, no printing
--     dimension and no foil/normal pairing
--   - we want sealed surfaces (e.g. "EV vs box price") that don't make sense
--     for singles
--
-- prices_daily already stores sealed-product rows (the ETL is product-agnostic
-- and filters nothing). Once this table exists, the UI can join sealed price
-- rows to product metadata the same way card rows join to `cards`.

create table if not exists public.sealed_products (
  tcgplayer_product_id  bigint        primary key,
  tcgplayer_group_id    bigint,
  set_id                text          references public.sets(id) on delete set null,
  name                  text          not null,
  clean_name            text,
  -- Heuristic bucket from the loader: 'Booster Box', 'Booster Pack',
  -- 'Starter Deck', 'Gift Set', 'Trove', 'Quest', 'Promo Single', 'Other'.
  -- Re-runnable — the loader overwrites this on each pass so changes to the
  -- classification heuristic propagate without manual migration.
  product_type          text,
  image_url             text,
  tcgplayer_url         text,
  -- Modified-on from TCGCSV (when TCGPlayer last touched the listing); not
  -- a true release date, but useful for sorting "what's new on the feed".
  modified_on           timestamptz,
  ingested_at           timestamptz   not null default now(),
  updated_at            timestamptz   not null default now()
);

create index if not exists sealed_products_group_idx on public.sealed_products (tcgplayer_group_id);
create index if not exists sealed_products_set_idx   on public.sealed_products (set_id);
create index if not exists sealed_products_type_idx  on public.sealed_products (product_type);

-- Public catalog data — every visitor can read. No writes from the client;
-- only the service_role / ETL writes here.
alter table public.sealed_products enable row level security;
drop policy if exists "sealed_products: read all" on public.sealed_products;
create policy "sealed_products: read all"
  on public.sealed_products for select
  using (true);

grant select on public.sealed_products to anon, authenticated;
grant select, insert, update, delete on public.sealed_products to service_role;

-- Reuse the shared updated_at trigger function defined back in 03_collections.sql.
drop trigger if exists sealed_products_updated_at on public.sealed_products;
create trigger sealed_products_updated_at
  before update on public.sealed_products
  for each row execute function public.set_updated_at();
