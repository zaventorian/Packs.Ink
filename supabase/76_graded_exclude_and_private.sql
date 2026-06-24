-- 76_graded_exclude_and_private.sql
-- (1) graded_sales.excluded — soft-exclude rows from the price history/rollup
--     while KEEPING them in the table. Used for foreign-language listings
--     (Chinese / Japanese / Korean printings are a different market and
--     shouldn't blend into a card's graded price history).
-- (2) Recreate graded_sales_rollup to skip excluded rows.
-- (3) admin_add_private_sale — admins log a manual/private graded sale (counts
--     in the history, flagged source='private_sale').

alter table public.graded_sales add column if not exists excluded boolean not null default false;

-- Flag foreign-language listings: full words (any case) OR standalone UPPERCASE
-- language codes (ZH/JA/JP/KR/CN) — verified no English false positives in the
-- current data (the codes always appear as "JPN JA 1", "ZH P1", etc).
update public.graded_sales
set excluded = true
where excluded = false
  and (title ~* '\y(chinese|japanese|korean|china|japan|korea)\y'
       or title ~ '\y(ZH|JA|JP|KR|CN)\y');

create index if not exists graded_sales_excluded_idx on public.graded_sales (excluded) where excluded;

------------------------------------------------------------------------------
-- Rollup, now excluding flagged rows
------------------------------------------------------------------------------
drop materialized view if exists public.graded_sales_rollup;
create materialized view public.graded_sales_rollup as
with ranked as (
  select card_id, grader, grade, sale_price, sold_date, scraped_at,
    row_number() over (partition by card_id, grader, grade
                       order by sold_date desc nulls last, scraped_at desc) as rn
  from public.graded_sales
  where card_id is not null and grade is not null and sale_price is not null
    and excluded = false
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
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date -   7 order by x.sold_date desc limit 1) as r7,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date -  30 order by x.sold_date desc limit 1) as r30,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date -  90 order by x.sold_date desc limit 1) as r90,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date - 180 order by x.sold_date desc limit 1) as r180,
    (select x.sale_price from public.graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade and x.sale_price is not null and not x.excluded and x.sold_date <= a.last_sold_date - 365 order by x.sold_date desc limit 1) as r365
) r on true;

create unique index if not exists graded_sales_rollup_pk on public.graded_sales_rollup (card_id, grader, grade);
create index if not exists graded_sales_rollup_card_idx on public.graded_sales_rollup (card_id);
grant select on public.graded_sales_rollup to anon, authenticated, service_role;

------------------------------------------------------------------------------
-- Private (manual) graded sale entry
------------------------------------------------------------------------------
create or replace function public.admin_add_private_sale(
  p_card_id text, p_grader text, p_grade text, p_sale_price numeric,
  p_sold_date date, p_note text default null)
returns void language plpgsql security definer set search_path = public, extensions
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  insert into public.graded_sales(item_id, card_id, grader, grade, sale_price, sold_date,
    title, listing_type, source_query, excluded, scraped_at)
  values ('priv_' || replace(gen_random_uuid()::text, '-', ''),
    p_card_id, upper(btrim(p_grader)), btrim(p_grade), p_sale_price, p_sold_date,
    coalesce(nullif(btrim(p_note), ''), 'Private sale'), 'private', 'private_sale', false, now());
end;
$$;
grant execute on function public.admin_add_private_sale(text, text, text, numeric, date, text) to authenticated;

notify pgrst, 'reload schema';
