-- 85_graded_rollup_window_guard.sql
-- Honest sparse-graded Δ%: each window's reference sale must actually fall in the
-- [W, 2W]-days-ago band relative to the last sale. Before this, the reference was
-- "the most recent sale at least W days before the last sale" with NO lower bound,
-- so a foil card whose only prior sale was 9 months earlier showed "+884% (1W)".
-- Now if there's no sale ~W ago, the window is null (no misleading delta). The
-- all-time pct_rel keeps its single first-sale reference (intentional).
--
-- Recreate (matview can't be ALTERed). graded_sale_pkey + the printing split are
-- unchanged from migration 83.

drop materialized view if exists public.graded_sales_rollup;
create materialized view public.graded_sales_rollup as
with base as (
  select gs.card_id, gs.grader, gs.grade, gs.sale_price, gs.sold_date, gs.scraped_at,
    c.split_printing as is_split, c.foil_split as is_foilsplit,
    graded_sale_pkey(gs.printing, c.split_printing, c.foil_split) as pkey
  from graded_sales gs
  join cards c on c.id = gs.card_id
  where gs.card_id is not null and gs.grade is not null and gs.sale_price is not null and not gs.excluded
),
ranked as (
  select base.*,
    row_number() over (partition by base.card_id, base.grader, base.grade, base.pkey
      order by base.sold_date desc nulls last, base.scraped_at desc) as rn
  from base
),
agg as (
  select card_id, grader, grade, pkey,
    bool_or(is_split) as is_split, bool_or(is_foilsplit) as is_foilsplit,
    count(*) as sale_count,
    max(sold_date) as last_sold_date,
    max(sale_price) filter (where rn = 1) as last_sold_price,
    avg(sale_price) filter (where rn <= 5) as avg_last_5,
    count(*) filter (where rn <= 5) as last_5_count
  from ranked
  group by card_id, grader, grade, pkey
)
select a.card_id, a.grader, a.grade, a.pkey as printing, a.sale_count, a.last_sold_date,
  a.last_sold_price, a.avg_last_5, a.last_5_count,
  case when r.r1    > 0 then round((a.last_sold_price - r.r1   )/r.r1   *100, 1) end as pct_1d,
  case when r.r7    > 0 then round((a.last_sold_price - r.r7   )/r.r7   *100, 1) end as pct_7d,
  case when r.r30   > 0 then round((a.last_sold_price - r.r30  )/r.r30  *100, 1) end as pct_30d,
  case when r.r90   > 0 then round((a.last_sold_price - r.r90  )/r.r90  *100, 1) end as pct_90d,
  case when r.r180  > 0 then round((a.last_sold_price - r.r180 )/r.r180 *100, 1) end as pct_180d,
  case when r.r365  > 0 then round((a.last_sold_price - r.r365 )/r.r365 *100, 1) end as pct_365d,
  case when r.r1095 > 0 then round((a.last_sold_price - r.r1095)/r.r1095*100, 1) end as pct_1095d,
  case when r.rfirst > 0 and r.rfirst is distinct from a.last_sold_price
       then round((a.last_sold_price - r.rfirst)/r.rfirst*100, 1) end as pct_rel
from agg a
left join lateral (
  select
    (select x.sale_price from graded_sales x
       where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded
         and graded_sale_pkey(x.printing,a.is_split,a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 1    and x.sold_date >= a.last_sold_date - 2
       order by x.sold_date desc limit 1) as r1,
    (select x.sale_price from graded_sales x
       where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded
         and graded_sale_pkey(x.printing,a.is_split,a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 7    and x.sold_date >= a.last_sold_date - 14
       order by x.sold_date desc limit 1) as r7,
    (select x.sale_price from graded_sales x
       where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded
         and graded_sale_pkey(x.printing,a.is_split,a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 30   and x.sold_date >= a.last_sold_date - 60
       order by x.sold_date desc limit 1) as r30,
    (select x.sale_price from graded_sales x
       where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded
         and graded_sale_pkey(x.printing,a.is_split,a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 90   and x.sold_date >= a.last_sold_date - 180
       order by x.sold_date desc limit 1) as r90,
    (select x.sale_price from graded_sales x
       where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded
         and graded_sale_pkey(x.printing,a.is_split,a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 180  and x.sold_date >= a.last_sold_date - 360
       order by x.sold_date desc limit 1) as r180,
    (select x.sale_price from graded_sales x
       where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded
         and graded_sale_pkey(x.printing,a.is_split,a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 365  and x.sold_date >= a.last_sold_date - 730
       order by x.sold_date desc limit 1) as r365,
    (select x.sale_price from graded_sales x
       where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded
         and graded_sale_pkey(x.printing,a.is_split,a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 1095 and x.sold_date >= a.last_sold_date - 2190
       order by x.sold_date desc limit 1) as r1095,
    (select x.sale_price from graded_sales x
       where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded
         and graded_sale_pkey(x.printing,a.is_split,a.is_foilsplit)=a.pkey
       order by x.sold_date, x.scraped_at limit 1) as rfirst
) r on true;

create unique index graded_sales_rollup_pk on public.graded_sales_rollup (card_id, grader, grade, printing);
create index graded_sales_rollup_card_idx on public.graded_sales_rollup (card_id);
grant select on public.graded_sales_rollup to anon, authenticated, service_role;

notify pgrst, 'reload schema';
