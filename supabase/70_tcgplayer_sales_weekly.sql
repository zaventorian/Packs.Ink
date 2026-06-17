-- 70_tcgplayer_sales_weekly.sql
-- Stores TCGplayer weekly sales-history buckets scraped via the Apify actor
-- scraped/tcgplayer-sales-history (one-off bulk capture 2026-06-16).
-- Raw-card SKU sales (NOT graded eBay sales). Weekly aggregates, not per-sale.
-- Initially loaded with Near Mint only; `condition` is in the PK so other
-- conditions can be added later without a schema change.

create table if not exists public.tcgplayer_sales_weekly (
  tcgplayer_product_id   bigint      not null,
  printing               text        not null,   -- Normal | Cold Foil | Holofoil
  condition              text        not null,   -- Near Mint (others loadable later)
  week_start             date        not null,   -- bucketStartDate (Monday)
  card_id                text,                    -- references cards.id (null = unmapped)
  market_price           numeric(12,2),           -- TCGplayer computed market (carried fwd on dead weeks)
  low_sale_price         numeric(12,2),           -- actual completed-sale low (null when no sales)
  high_sale_price        numeric(12,2),
  low_sale_price_ship    numeric(12,2),
  high_sale_price_ship   numeric(12,2),
  quantity_sold          integer,
  transaction_count      integer,
  sku_id                 bigint,
  language               text,
  updated_at             timestamptz default now(),
  primary key (tcgplayer_product_id, printing, condition, week_start)
);

create index if not exists tcgplayer_sales_weekly_card_id_idx
  on public.tcgplayer_sales_weekly (card_id);
create index if not exists tcgplayer_sales_weekly_card_week_idx
  on public.tcgplayer_sales_weekly (card_id, week_start);

alter table public.tcgplayer_sales_weekly enable row level security;

drop policy if exists "tcgplayer_sales_weekly public read" on public.tcgplayer_sales_weekly;
create policy "tcgplayer_sales_weekly public read"
  on public.tcgplayer_sales_weekly
  for select to anon, authenticated
  using (true);

grant select on public.tcgplayer_sales_weekly to anon, authenticated, service_role;
-- service_role bypasses RLS but still needs table-level write GRANTs (does NOT inherit implicitly).
grant insert, update, delete on public.tcgplayer_sales_weekly to service_role;

notify pgrst, 'reload schema';
