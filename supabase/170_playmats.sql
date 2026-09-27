-- 170: Lorcana playmats - a catalog of their own, and their latest price.
--
-- A user asked to log their prize-wall and Set Championship mats (feedback
-- 2026-09-26). TCGplayer lists every official Lorcana mat, but NOT in the
-- Lorcana category (71) the ETL reads: they sit in its separate Playmats
-- category (35), group "Ravensburger Playmats" (23280). That is why no playmat
-- ever reached sealed_products and prices_daily held no history for one.
-- scripts/load_playmats.py fills this table; the daily ETL now writes the
-- group's prices (tcgcsv_common.EXTRA_PRICE_GROUPS); TCGCSV's archives carry
-- them back to 2024-02-08 (scripts/backfill_playmat_prices.py).
--
-- Its OWN table, deliberately NOT sealed_products. Every sealed surface reads
-- sealed_products, and so does the market index's 'sealed' scope (130 admits
-- every product_type but 'Promo Single'): a mat filed there would silently join
-- the sealed benchmark, the Sealed tab, the sealed Screener and Sealed Movers.
--
-- Ownership needs nothing here: an owned mat is a sealed_collection_items row
-- under 980000000 + its TCGplayer id (PLAYMAT_PID_BASE in Index.html), the same
-- synthetic-band trick the pins use, so no sealed count or value picks it up.
--
-- section: retail | set_champ | dlc | event | other (see load_playmats.py).

create table if not exists public.playmats (
  tcgplayer_product_id bigint primary key,
  tcg_name      text        not null,
  name          text        not null,
  section       text        not null default 'other',
  set_id        text        references public.sets(id) on delete set null,
  tier          text,
  finish        text,
  source        text,
  year          integer,
  released_on   date,
  description   text,
  image_url     text,
  tcgplayer_url text,
  presale       boolean     not null default false,
  modified_on   timestamptz,
  updated_at    timestamptz not null default now()
);

alter table public.playmats drop constraint if exists playmats_section_chk;
alter table public.playmats add constraint playmats_section_chk
  check (section in ('retail', 'set_champ', 'dlc', 'event', 'other'));

create index if not exists playmats_set_idx on public.playmats (set_id);

alter table public.playmats enable row level security;
drop policy if exists playmats_read on public.playmats;
create policy playmats_read on public.playmats
  for select to anon, authenticated using (true);

grant select on public.playmats to anon, authenticated, service_role;
grant insert, update, delete on public.playmats to service_role;

-- The catalog with each mat's newest price, and every mat present whether or
-- not it has one (an unlisted Champion mat is still a mat you can own). A plain
-- view, not a matview: it is ~60 index lookups on prices_daily_tcgcsv_raw_idx
-- (tcgplayer_product_id, printing, date desc), so it is always current and
-- needs no refresh step for the ETL to forget.
create or replace view public.playmat_prices_latest
with (security_invoker = on) as
select
  pm.tcgplayer_product_id,
  pm.tcg_name,
  pm.name,
  pm.section,
  pm.set_id,
  s.name        as set_name,
  s.released_at as set_released_at,
  pm.tier,
  pm.finish,
  pm.source,
  pm.year,
  pm.released_on,
  pm.image_url,
  pm.tcgplayer_url,
  pm.presale,
  px.date         as price_date,
  px.low_price,
  px.mid_price,
  px.market_price,
  px.high_price
from public.playmats pm
left join public.sets s on s.id = pm.set_id
left join lateral (
  select p.date, p.low_price, p.mid_price, p.market_price, p.high_price
  from public.prices_daily p
  where p.tcgplayer_product_id = pm.tcgplayer_product_id
    and p.source   = 'tcgcsv'
    and p.grade    = 'raw'
    and p.printing = 'Normal'
    and (p.low_price is not null or p.market_price is not null)
  order by p.date desc
  limit 1
) px on true;

grant select on public.playmat_prices_latest to anon, authenticated, service_role;

notify pgrst, 'reload schema';
