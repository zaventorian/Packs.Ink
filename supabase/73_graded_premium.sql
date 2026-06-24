-- 73_graded_premium.sql
-- Premium graded experience, gated to an allowlist of accounts.
--
-- The new per-sale dataset (graded_sales, migration 71) replaces the old
-- TCGPriceLookup graded data (graded_prices_daily/_latest) ONLY for accounts in
-- graded_premium_viewers. Everyone else keeps the existing graded view. Graded
-- data is slated to become a paid feature; this allowlist is the interim gate.
--
-- Two objects:
--   1. graded_premium_viewers + can_view_graded_premium()  -- the access gate
--   2. graded_sales_rollup matview                         -- Last Sold / Avg-5
--      per (card_id, grader, grade), powering the Screener + collection totals.
--      The card-detail scatter fetches raw graded_sales rows directly, so it
--      does NOT depend on this matview.

------------------------------------------------------------------------------
-- 1) Access gate
------------------------------------------------------------------------------
create table if not exists public.graded_premium_viewers (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  granted_at timestamptz default now(),
  note       text
);

alter table public.graded_premium_viewers enable row level security;
-- No policies: the table is read only through the SECURITY DEFINER RPC below.
-- service_role (migrations / admin inserts) bypasses RLS but still needs grants.
grant select, insert, update, delete on public.graded_premium_viewers to service_role;

create or replace function public.can_view_graded_premium()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.graded_premium_viewers v
    where v.user_id = auth.uid()
  );
$$;
grant execute on function public.can_view_graded_premium() to anon, authenticated;

-- Seed the owner account.
insert into public.graded_premium_viewers (user_id, note)
select id, 'owner'
from auth.users
where lower(email) = 'zaventorian@gmail.com'
on conflict (user_id) do nothing;

------------------------------------------------------------------------------
-- 2) Per-(card, grader, grade) rollup: Last Sold + Average of Last 5
------------------------------------------------------------------------------
-- Only attributed, graded rows count. NEEDS_GRADE rows (grade null, awaiting
-- slab-OCR) and unmatched rows (card_id null) are excluded until resolved.
-- printing is intentionally NOT a key: the scraper's printing detection is weak
-- (only set when the word foil/non-foil is in the title), so keying on it would
-- fragment the rollup. Valuation looks up by (card_id, grader, grade).
drop materialized view if exists public.graded_sales_rollup;
create materialized view public.graded_sales_rollup as
with ranked as (
  select
    card_id,
    grader,
    grade,
    sale_price,
    sold_date,
    row_number() over (
      partition by card_id, grader, grade
      order by sold_date desc nulls last, scraped_at desc
    ) as rn
  from public.graded_sales
  where card_id is not null
    and grade is not null
    and sale_price is not null
)
select
  card_id,
  grader,
  grade,
  count(*)                                       as sale_count,
  max(sold_date)                                 as last_sold_date,
  max(sale_price) filter (where rn = 1)          as last_sold_price,
  avg(sale_price) filter (where rn <= 5)         as avg_last_5,
  count(*)        filter (where rn <= 5)          as last_5_count
from ranked
group by card_id, grader, grade;

-- Unique index required for REFRESH ... CONCURRENTLY.
create unique index if not exists graded_sales_rollup_pk
  on public.graded_sales_rollup (card_id, grader, grade);
create index if not exists graded_sales_rollup_card_idx
  on public.graded_sales_rollup (card_id);

grant select on public.graded_sales_rollup to anon, authenticated, service_role;

create or replace function public.refresh_graded_sales_rollup()
returns void
language plpgsql
security definer
set search_path = public, extensions
set statement_timeout = '5min'
as $$
begin
  refresh materialized view concurrently public.graded_sales_rollup;
exception
  when others then
    -- first refresh (or missing unique index) can't go concurrent
    refresh materialized view public.graded_sales_rollup;
end;
$$;
grant execute on function public.refresh_graded_sales_rollup() to service_role;

notify pgrst, 'reload schema';
