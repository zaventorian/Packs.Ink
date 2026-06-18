-- 71_graded_sales.sql
-- Individual graded-card eBay sales scraped from eBay Terapeak (Seller Hub →
-- Product Research, SOLD tab) via scripts/terapeak_scrape.py.
--
-- One row per sold listing. A graded slab is a unique item, so each row IS a
-- single sale: `sale_price` + `sold_date` are exact (Terapeak's "avg sold
-- price" collapses to the single sale when quantity_sold = 1). USD-normalized
-- across all eBay marketplaces (marketplace=ALL); per-site origin not captured.
--
-- DESIGN: the scraper fills only the RAW columns. The derived columns
-- (card_id, grader, grade, printing) are populated by a SEPARATE attribution
-- pass (scripts/terapeak_match.py → loader) that parses `title`. This keeps the
-- expensive, account-risky scrape decoupled from matching, which is cheap and
-- re-runnable (re-match 60% → 90% without re-scraping). Unmatched rows keep
-- card_id null and are simply ignored by the rollup until matching improves.

create table if not exists public.graded_sales (
  -- raw (filled by the scraper) --
  item_id        text        primary key,   -- eBay listing id
  title          text,                       -- raw listing title (drives matching)
  listing_url    text,                       -- link to the listing
  image_url      text,                       -- slab photo (eBay s-l1200)
  sale_price     numeric(12,2),
  shipping       numeric(12,2),
  quantity_sold  integer,
  bids           integer,
  sold_date      date,                        -- parsed from Terapeak "date last sold"
  listing_type   text,                        -- fixed_price | auction
  source_query   text,                        -- which grader sweep found it (debug)
  scraped_at     timestamptz default now(),
  -- derived (filled LATER by the matcher; null until attributed) --
  card_id        text references public.cards(id),
  grader         text,                        -- PSA | CGC | BGS | SGC | TAG
  grade          text,                        -- 10 | 9.5 | 9 | ...
  printing       text                         -- Foil | Non-Foil
);

-- Rollup keys: per (card_id, grader, grade) ordered by sold_date for
-- last-sale / avg-of-last-5. Plus a date index for windowed queries.
create index if not exists graded_sales_card_idx
  on public.graded_sales (card_id);
create index if not exists graded_sales_rollup_idx
  on public.graded_sales (card_id, grader, grade, sold_date desc);
create index if not exists graded_sales_sold_date_idx
  on public.graded_sales (sold_date);

alter table public.graded_sales enable row level security;

drop policy if exists "graded_sales public read" on public.graded_sales;
create policy "graded_sales public read"
  on public.graded_sales
  for select to anon, authenticated
  using (true);

grant select on public.graded_sales to anon, authenticated, service_role;
-- service_role bypasses RLS but still needs table-level write GRANTs (does NOT inherit implicitly).
grant insert, update, delete on public.graded_sales to service_role;

notify pgrst, 'reload schema';
