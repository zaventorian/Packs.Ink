-- 75_graded_rollup_deltas.sql
-- (1) Add windowed Δ% (1W/1M/3M/6M/1Y) to graded_sales_rollup so the Screener
--     graded mode can show price changes again. Anchored on the latest sale
--     (not today) so sparse histories still yield a reference — matches the
--     client's computeGradedSaleWindows. pct_W = change from the most recent
--     sale on/before (last_sold_date − W days) to the last sale.
-- (2) Let admins also correct a sale's price (admin_update_graded_sale + p_sale_price).

drop materialized view if exists public.graded_sales_rollup;
create materialized view public.graded_sales_rollup as
with ranked as (
  select card_id, grader, grade, sale_price, sold_date, scraped_at,
    row_number() over (partition by card_id, grader, grade
                       order by sold_date desc nulls last, scraped_at desc) as rn
  from public.graded_sales
  where card_id is not null and grade is not null and sale_price is not null
),
agg as (
  select card_id, grader, grade,
    count(*)                               as sale_count,
    max(sold_date)                         as last_sold_date,
    max(sale_price) filter (where rn = 1)  as last_sold_price,
    avg(sale_price) filter (where rn <= 5) as avg_last_5,
    count(*)        filter (where rn <= 5) as last_5_count
  from ranked group by card_id, grader, grade
)
select a.card_id, a.grader, a.grade, a.sale_count, a.last_sold_date,
       a.last_sold_price, a.avg_last_5, a.last_5_count,
       case when r.r7   > 0 then round((a.last_sold_price - r.r7  )/r.r7  *100, 1) end as pct_7d,
       case when r.r30  > 0 then round((a.last_sold_price - r.r30 )/r.r30 *100, 1) end as pct_30d,
       case when r.r90  > 0 then round((a.last_sold_price - r.r90 )/r.r90 *100, 1) end as pct_90d,
       case when r.r180 > 0 then round((a.last_sold_price - r.r180)/r.r180*100, 1) end as pct_180d,
       case when r.r365 > 0 then round((a.last_sold_price - r.r365)/r.r365*100, 1) end as pct_365d
from agg a
left join lateral (
  select
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and x.sold_date <= a.last_sold_date -   7 order by x.sold_date desc limit 1) as r7,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and x.sold_date <= a.last_sold_date -  30 order by x.sold_date desc limit 1) as r30,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and x.sold_date <= a.last_sold_date -  90 order by x.sold_date desc limit 1) as r90,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and x.sold_date <= a.last_sold_date - 180 order by x.sold_date desc limit 1) as r180,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and x.sold_date <= a.last_sold_date - 365 order by x.sold_date desc limit 1) as r365
) r on true;

create unique index if not exists graded_sales_rollup_pk on public.graded_sales_rollup (card_id, grader, grade);
create index if not exists graded_sales_rollup_card_idx on public.graded_sales_rollup (card_id);
grant select on public.graded_sales_rollup to anon, authenticated, service_role;

-- admins can now also fix the sale price
create or replace function public.admin_update_graded_sale(
  p_item_id text,
  p_grader  text default null,
  p_grade   text default null,
  p_card_id text default null,
  p_sale_price numeric default null)
returns void language plpgsql security definer set search_path = public
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  update public.graded_sales set
    grader     = coalesce(nullif(btrim(p_grader), ''), grader),
    grade      = coalesce(nullif(btrim(p_grade),  ''), grade),
    card_id    = coalesce(nullif(btrim(p_card_id),''), card_id),
    sale_price = coalesce(p_sale_price, sale_price)
  where item_id = p_item_id;
end;
$$;
grant execute on function public.admin_update_graded_sale(text, text, text, text, numeric) to authenticated;

notify pgrst, 'reload schema';
