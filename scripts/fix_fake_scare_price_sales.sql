-- Re-exclude fake "scare price" graded sales (mid-June 2026 cluster).
--
-- A batch of bogus $999.99 / $9999.99 "sales" landed in graded_sales in mid-June
-- 2026 (fake BIN listings / Terapeak artifacts) and polluted the affected cards'
-- last_sold + avg_last_5 (e.g. Mickey - Playful Sorcerer Deep Trouble #225 showed
-- $999.99 last sold vs a real ~$50). They aren't caught by the foreign/autograph/
-- troll filters in terapeak_load.py, so a reload re-imports them as excluded=false
-- — this re-applies the exclusion. Idempotent; run after any terapeak_load reload.
--
-- Precision: only exclude the round "scare" prices that are clear OUTLIERS (> 2x
-- the card+grade median of OTHER sales). Cards that genuinely trade near $1000
-- (Cruella #4, Elsa Spirit, Maleficent #5, Mickey - Brave Little Tailor #1,
-- Stitch Rock Star) sit at ~1x their median and are LEFT ALONE.
update graded_sales gs set excluded = true
from cards c
left join lateral (
  select percentile_cont(0.5) within group (order by g2.sale_price) m
  from graded_sales g2
  where g2.card_id = c.id and g2.grader = gs.grader and g2.grade = gs.grade
    and not g2.excluded and g2.sale_price not in (999.99, 9999.99)
) med on true
where c.id = gs.card_id
  and not gs.excluded
  and gs.sale_price in (999.99, 9999.99)
  and gs.sold_date >= '2026-06-01'
  and med.m is not null
  and gs.sale_price > 2 * med.m;

select public.refresh_graded_sales_rollup();
