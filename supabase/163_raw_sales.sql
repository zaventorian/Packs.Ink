-- 163_raw_sales.sql
-- RAW (ungraded) eBay sales for the high-end promos TCGplayer cannot price.
--
-- WHY THIS EXISTS. card_prices_latest is an INNER JOIN on a TCGplayer product,
-- so a card TCGplayer has never recorded a sale for shows nothing at all, and a
-- card it froze on shows a fossil. Measured on the live catalog 2026-09-15,
-- promos freeze for 50-181 days where Enchanted/Iconic chase cards freeze for
-- 10-18 (they come out of packs continuously, so a flat reading there is a lull,
-- not an absent market). The worst cases are total: Challenge Promo #5 Mickey
-- Mouse - Brave Little Tailor has NEVER had a market_price populated, #7 Elsa's
-- Ice Palace likewise, and #9 Baymax shows the $63 NON-foil while its foil slabs
-- reach $33,494. Meanwhile a RAW Rapunzel - Gifted with Healing 4/C1 Foil sold
-- on eBay for $16,406. For these ~24 cards an eBay sold price is not a nice
-- extra -- it is the only honest number available.
--
-- SCOPE IS DELIBERATELY TINY AND CURATED. scripts/raw_watchlist.py is the list,
-- and it is promos only: a promo is a fixed, event-distributed population, so
-- its market is structurally somewhere other than TCGplayer. Every Enchanted and
-- Iconic is out of scope on purpose -- packs keep supplying them, so TCGplayer's
-- number is real there and a second source would only disagree with it.
--
-- RELATIONSHIP TO graded_sales. Same shape, same scraper, same attribution
-- engine (terapeak_match), one table each because they are different assets: a
-- slab and a raw card are not substitutes and averaging them describes neither.
-- The split is the same call migration 130 makes for sealed vs singles.
--
-- ⚠ NO grader/grade columns, and that is the point rather than an omission: a
-- row reaching this table has been affirmatively judged NOT to be a slab
-- (scripts/raw_match.py, gate 1). If a grade is ever discovered for a row, the
-- row is wrong and belongs in graded_sales, not in a new column here.

create table if not exists public.raw_sales (
  -- raw (filled by the scraper) --
  item_id        text        primary key,   -- eBay listing id
  title          text,                       -- raw listing title (drives matching)
  listing_url    text,
  image_url      text,
  sale_price     numeric(12,2),              -- Terapeak "avg sold price"; see quantity_sold
  shipping       numeric(12,2),
  quantity_sold  integer,                    -- see the comment below -- NOT always 1 here
  bids           integer,
  sold_date      date,
  listing_type   text,                       -- fixed_price | auction
  source_query   text,                       -- the raw_watchlist query that found it
  scraped_at     timestamptz default now(),
  -- derived (filled by scripts/raw_match.py at load) --
  card_id          text references public.cards(id),
  printing         text,                     -- Foil | Non-Foil | Cold Foil | null
  match_confidence numeric(5,3),
  cn_conflict      boolean default false,
  -- quality --
  excluded       boolean not null default false,
  exclude_reason text                        -- see raw_match.EXCLUDE_REASONS
);

-- ⚠ quantity_sold matters MORE here than it does for graded, and the difference
-- is easy to miss. A slab is a unique item, so Terapeak's "avg sold price"
-- collapses to the single sale and graded_sales can treat the two as the same
-- thing. A raw card is fungible: one listing can sell several copies, and then
-- sale_price is a per-unit AVERAGE across them and sold_date is only the LAST of
-- them. That is still a fair price point, so such rows are kept -- but a
-- multi-quantity sale of a card with a handful of known copies is also a strong
-- hint of mis-attribution, which is why the column is carried through to the
-- review report rather than discarded.
comment on column public.raw_sales.quantity_sold is
  'Copies sold by this listing. >1 means sale_price is a per-unit average and sold_date is the last sale.';
comment on column public.raw_sales.exclude_reason is
  'Why this row does not count. Recorded from the first row loaded, so one class can be re-evaluated without disturbing hand-reviewed decisions (the lesson of migration 111).';
comment on column public.raw_sales.source_query is
  'The raw_watchlist query that found this row, or backfill:graded_sales for rows recovered from the grader sweeps.';

create index if not exists raw_sales_card_idx on public.raw_sales (card_id);
create index if not exists raw_sales_rollup_idx on public.raw_sales (card_id, sold_date desc);
create index if not exists raw_sales_sold_date_idx on public.raw_sales (sold_date);
create index if not exists raw_sales_exclude_reason_idx
  on public.raw_sales (exclude_reason) where excluded and exclude_reason is not null;

alter table public.raw_sales enable row level security;

drop policy if exists "raw_sales public read" on public.raw_sales;
create policy "raw_sales public read"
  on public.raw_sales for select to anon, authenticated using (true);

-- service_role bypasses RLS but still needs table-level GRANTs -- it does NOT
-- inherit them implicitly. The trap migration 45 had to fix retroactively.
grant select on public.raw_sales to anon, authenticated, service_role;
grant insert, update, delete on public.raw_sales to service_role;


-- ── rollup ───────────────────────────────────────────────────────────────────
-- Per (card_id, printing bucket): the latest raw sale and the mean of the last
-- five. Deliberately keyed on the SAME printing bucket as the graded rollup, via
-- graded_sale_pkey -- a Challenge card's Top Prize foil and Prize Wall non-foil
-- share one card_id and sit ~50x apart ($1,707 vs $280 on Cinderella -
-- Stouthearted), so a raw price that does not respect the split is worse than
-- none. Reusing that function rather than writing a second one is what stops the
-- two tables ever disagreeing about which bucket a printing is in; a null
-- printing lands in its own 'Unknown' bucket, which can never be read as either
-- real printing.
--
-- ⚠ NO pct_* delta columns, unlike graded_sales_rollup, and this is a decision
-- rather than an unfinished edge. Migration 85 had to retrofit a window guard
-- onto the graded rollup because a sparse series produced honest-looking
-- nonsense ("+884% (1W)" off a reference sale nine months old). This data is
-- sparser still -- 19 of the 24 watchlist cards have fewer than ten known sales
-- ever, several have exactly one -- so every window would be either null or
-- misleading. Sale count and date carry the uncertainty honestly instead.
drop materialized view if exists public.raw_sales_rollup;
create materialized view public.raw_sales_rollup as
with base as (
  select rs.card_id, rs.sale_price, rs.sold_date, rs.scraped_at, rs.quantity_sold,
         graded_sale_pkey(rs.printing, c.split_printing, c.foil_split) as pkey
  from raw_sales rs
  join cards c on c.id = rs.card_id
  where rs.card_id is not null
    and rs.sale_price is not null
    and rs.sold_date is not null
    and not rs.excluded
),
ranked as (
  select base.*,
         row_number() over (partition by base.card_id, base.pkey
                            order by base.sold_date desc nulls last, base.scraped_at desc) as rn
  from base
)
select card_id,
       pkey as printing,
       count(*)                                          as sale_count,
       max(sold_date)                                    as last_sold_date,
       min(sold_date)                                    as first_sold_date,
       max(sale_price) filter (where rn = 1)             as last_sold_price,
       avg(sale_price) filter (where rn <= 5)            as avg_last_5,
       count(*)        filter (where rn <= 5)            as last_5_count,
       min(sale_price)                                   as min_price,
       max(sale_price)                                   as max_price
from ranked
group by card_id, pkey;

create unique index raw_sales_rollup_pk on public.raw_sales_rollup (card_id, printing);
create index raw_sales_rollup_card_idx on public.raw_sales_rollup (card_id);
grant select on public.raw_sales_rollup to anon, authenticated, service_role;


-- ⚠ statement_timeout is pinned as a FUNCTION-LEVEL `SET` clause, never with a
-- `set local` inside the body. The GUC is armed when the outer call begins, so
-- changing it part-way through does not re-arm the running timer -- that is
-- exactly how migration 130's refresh died at the role default every time and
-- had to be fixed by 131. The table is small today, but the pin costs nothing
-- and the failure it prevents is silent.
create or replace function public.refresh_raw_sales_rollup()
returns void language plpgsql security definer set search_path = public, extensions
set statement_timeout = '5min'
as $$
begin
  if exists (select 1 from pg_class
             where relname = 'raw_sales_rollup' and relkind = 'm' and relispopulated) then
    refresh materialized view concurrently public.raw_sales_rollup;
  else
    refresh materialized view public.raw_sales_rollup;
  end if;
end;
$$;

-- CREATE FUNCTION hands PUBLIC an EXECUTE grant by default; only the loader
-- (service key) ever calls this. Migration 97 had to revoke exactly this on the
-- graded twin after any anon visitor could trigger a refresh in a loop.
revoke execute on function public.refresh_raw_sales_rollup() from public, anon, authenticated;
grant execute on function public.refresh_raw_sales_rollup() to service_role;

-- Populated by the first load; a matview created empty is fine here because the
-- table is empty too (unlike migration 130, where CREATE ... WITH NO DATA was
-- needed to keep an expensive build out of the SQL editor's own timeout).
notify pgrst, 'reload schema';
