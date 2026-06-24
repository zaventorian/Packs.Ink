-- 77_graded_rollup_3y_since_release.sql
-- Extend graded_sales_rollup with two more Δ% windows on top of migration 75's
-- 1W/1M/3M/6M/1Y:
--   • pct_1095d — 3 years (graded eBay history reaches ~3y on Terapeak).
--   • pct_rel   — "since release": change from the card's FIRST recorded sale for
--                 this grader/grade to its most recent. The earliest sale is, by
--                 definition, on/after the card released, so this is the lifetime
--                 appreciation of that exact slab combo. No sets-table join needed.
-- Same anchoring as 75: every window is measured back from last_sold_date (not
-- today) so sparse histories still yield a reference.

drop materialized view if exists public.graded_sales_rollup;
create materialized view public.graded_sales_rollup as
with ranked as (
  select card_id, grader, grade, sale_price, sold_date, scraped_at,
    row_number() over (partition by card_id, grader, grade
                       order by sold_date desc nulls last, scraped_at desc) as rn
  from public.graded_sales
  where card_id is not null and grade is not null and sale_price is not null and not excluded
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
       case when r.r7    > 0 then round((a.last_sold_price - r.r7   )/r.r7   *100, 1) end as pct_7d,
       case when r.r30   > 0 then round((a.last_sold_price - r.r30  )/r.r30  *100, 1) end as pct_30d,
       case when r.r90   > 0 then round((a.last_sold_price - r.r90  )/r.r90  *100, 1) end as pct_90d,
       case when r.r180  > 0 then round((a.last_sold_price - r.r180 )/r.r180 *100, 1) end as pct_180d,
       case when r.r365  > 0 then round((a.last_sold_price - r.r365 )/r.r365 *100, 1) end as pct_365d,
       case when r.r1095 > 0 then round((a.last_sold_price - r.r1095)/r.r1095*100, 1) end as pct_1095d,
       case when r.rfirst > 0 and r.rfirst is distinct from a.last_sold_price
            then round((a.last_sold_price - r.rfirst)/r.rfirst*100, 1) end                as pct_rel
from agg a
left join lateral (
  select
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date -    7 order by x.sold_date desc limit 1) as r7,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date -   30 order by x.sold_date desc limit 1) as r30,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date -   90 order by x.sold_date desc limit 1) as r90,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date -  180 order by x.sold_date desc limit 1) as r180,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date -  365 order by x.sold_date desc limit 1) as r365,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date - 1095 order by x.sold_date desc limit 1) as r1095,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded order by x.sold_date asc, x.scraped_at asc limit 1) as rfirst
) r on true;

create unique index if not exists graded_sales_rollup_pk on public.graded_sales_rollup (card_id, grader, grade);
create index if not exists graded_sales_rollup_card_idx on public.graded_sales_rollup (card_id);
grant select on public.graded_sales_rollup to anon, authenticated, service_role;

notify pgrst, 'reload schema';
