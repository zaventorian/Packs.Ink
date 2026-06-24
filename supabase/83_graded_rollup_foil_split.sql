-- 83_graded_rollup_foil_split.sql — make graded_sales_rollup foil-aware for
-- mainline (x/204) booster cards, so the collection total + Screener value the
-- non-foil and cold-foil printings of a card separately (they were blended into
-- one number; only the card-detail view split them, client-side, until now).
--
-- A new `cards.foil_split` flag marks the cards that genuinely have a non-foil /
-- cold-foil duality: mainline booster sets, base rarities only (chase is single-
-- printing), excluding the EXTRAS quest/gift/starter-foil pids (single-printing
-- oddities that happen to live in mainline sets). The rollup's printing key now:
--   split_printing (C1 / Genie Two Swords / Peter Pan Text Error) → the variant
--   foil_split (mainline x/204)                                    → Foil | Non-Foil
--   everything else                                                → '' (blended)
-- via the helper graded_sale_pkey(). For NON-foil_split cards the key is identical
-- to before, so their rollup rows are byte-identical (verified by checksum).
--
-- The card detail is unaffected — it computes its own split from per-sale data.

-- ── foil bucket / printing-key helper ────────────────────────────────────────
create or replace function public.graded_sale_pkey(p_printing text, p_split boolean, p_foilsplit boolean)
returns text language sql immutable as $$
  select case
    when p_split then coalesce(p_printing, 'Unknown')
    when p_foilsplit then case
        when lower(coalesce(p_printing,'')) in ('foil','cold foil','holofoil','holo') then 'Foil'
        else 'Non-Foil' end
    else ''
  end
$$;

-- ── foil_split flag ──────────────────────────────────────────────────────────
alter table cards add column if not exists foil_split boolean not null default false;
update cards set foil_split = false;
update cards set foil_split = true
where tcgplayer_product_id is not null
  and not coalesce(split_printing,false)
  and rarity in ('Common','Uncommon','Rare','Super Rare','Legendary')
  and set_id in (
    'set_7ecb0e0c71af496a9e0110e23824e0a5','set_142d2dfb5d4b4b739a1017dc4bb0fcd2',
    'set_10a1db03fe66417c9912494b94463e8e','set_8f4cbf5aef324eb295c4add5673e684f',
    'set_c64f092e725a4f66966f43af3aa161b6','set_0df34ab314e04a479ef3538fd6c3e4e1',
    'set_ceb34c63638a4ce6b80e518393964c8f','set_e4fe64374c144642a035ee7b8451f990',
    'set_42a2e9232c43494dab2c72945ea6879e','set_8b7f731a52bf4478a0c41f09c7f74a2a',
    'set_c794231df3e14fce9f63c19c59241ee3','set_bd17976749ec48359e1957f2bed51e83')
  and tcgplayer_product_id not in (
    678236,678237,678238,690204,647652,647681,649224,650077,653916,657892,657893,657894,
    516778,516775,539145,539148,557538,544485,544492,544494,544487,634262,634263,634264,634265);

-- ── rebuild the rollup matview ───────────────────────────────────────────────
drop materialized view if exists public.graded_sales_rollup;
create materialized view public.graded_sales_rollup as
  with base as (
    select gs.card_id, gs.grader, gs.grade, gs.sale_price, gs.sold_date, gs.scraped_at,
      c.split_printing as is_split, c.foil_split as is_foilsplit,
      public.graded_sale_pkey(gs.printing, c.split_printing, c.foil_split) as pkey
    from graded_sales gs join cards c on c.id = gs.card_id
    where gs.card_id is not null and gs.grade is not null and gs.sale_price is not null and not gs.excluded
  ), ranked as (
    select base.*,
      row_number() over (partition by base.card_id, base.grader, base.grade, base.pkey
                         order by base.sold_date desc nulls last, base.scraped_at desc) as rn
    from base
  ), agg as (
    select ranked.card_id, ranked.grader, ranked.grade, ranked.pkey,
      bool_or(ranked.is_split) as is_split, bool_or(ranked.is_foilsplit) as is_foilsplit,
      count(*) as sale_count, max(ranked.sold_date) as last_sold_date,
      max(ranked.sale_price) filter (where ranked.rn = 1) as last_sold_price,
      avg(ranked.sale_price) filter (where ranked.rn <= 5) as avg_last_5,
      count(*) filter (where ranked.rn <= 5) as last_5_count
    from ranked group by ranked.card_id, ranked.grader, ranked.grade, ranked.pkey
  )
  select a.card_id, a.grader, a.grade, a.pkey as printing, a.sale_count, a.last_sold_date,
    a.last_sold_price, a.avg_last_5, a.last_5_count,
    case when r.r1   > 0 then round(((a.last_sold_price - r.r1)   / r.r1)   * 100, 1) end as pct_1d,
    case when r.r7   > 0 then round(((a.last_sold_price - r.r7)   / r.r7)   * 100, 1) end as pct_7d,
    case when r.r30  > 0 then round(((a.last_sold_price - r.r30)  / r.r30)  * 100, 1) end as pct_30d,
    case when r.r90  > 0 then round(((a.last_sold_price - r.r90)  / r.r90)  * 100, 1) end as pct_90d,
    case when r.r180 > 0 then round(((a.last_sold_price - r.r180) / r.r180) * 100, 1) end as pct_180d,
    case when r.r365 > 0 then round(((a.last_sold_price - r.r365) / r.r365) * 100, 1) end as pct_365d,
    case when r.r1095> 0 then round(((a.last_sold_price - r.r1095)/ r.r1095)* 100, 1) end as pct_1095d,
    case when r.rfirst > 0 and r.rfirst is distinct from a.last_sold_price
         then round(((a.last_sold_price - r.rfirst) / r.rfirst) * 100, 1) end as pct_rel
  from agg a
  left join lateral (
    select
      (select x.sale_price from graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade
         and x.sale_price is not null and not x.excluded
         and public.graded_sale_pkey(x.printing, a.is_split, a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 1 order by x.sold_date desc limit 1) as r1,
      (select x.sale_price from graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade
         and x.sale_price is not null and not x.excluded
         and public.graded_sale_pkey(x.printing, a.is_split, a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 7 order by x.sold_date desc limit 1) as r7,
      (select x.sale_price from graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade
         and x.sale_price is not null and not x.excluded
         and public.graded_sale_pkey(x.printing, a.is_split, a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 30 order by x.sold_date desc limit 1) as r30,
      (select x.sale_price from graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade
         and x.sale_price is not null and not x.excluded
         and public.graded_sale_pkey(x.printing, a.is_split, a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 90 order by x.sold_date desc limit 1) as r90,
      (select x.sale_price from graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade
         and x.sale_price is not null and not x.excluded
         and public.graded_sale_pkey(x.printing, a.is_split, a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 180 order by x.sold_date desc limit 1) as r180,
      (select x.sale_price from graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade
         and x.sale_price is not null and not x.excluded
         and public.graded_sale_pkey(x.printing, a.is_split, a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 365 order by x.sold_date desc limit 1) as r365,
      (select x.sale_price from graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade
         and x.sale_price is not null and not x.excluded
         and public.graded_sale_pkey(x.printing, a.is_split, a.is_foilsplit)=a.pkey
         and x.sold_date <= a.last_sold_date - 1095 order by x.sold_date desc limit 1) as r1095,
      (select x.sale_price from graded_sales x where x.card_id=a.card_id and x.grader=a.grader and x.grade=a.grade
         and x.sale_price is not null and not x.excluded
         and public.graded_sale_pkey(x.printing, a.is_split, a.is_foilsplit)=a.pkey
         order by x.sold_date, x.scraped_at limit 1) as rfirst
  ) r on true;

create unique index graded_sales_rollup_pk on public.graded_sales_rollup (card_id, grader, grade, printing);
grant select on public.graded_sales_rollup to anon, authenticated, service_role;
notify pgrst, 'reload schema';
