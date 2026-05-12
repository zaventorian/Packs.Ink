-- Packs.Ink schema v1
-- Run this in Supabase SQL Editor (Project → SQL Editor → New query → paste → Run)
-- Idempotent: safe to re-run.

-- ──────────────────────────────────────────────────────────────────────────
-- sets: Lorcana set metadata. Keyed by Lorcast set id.
-- ──────────────────────────────────────────────────────────────────────────
create table if not exists public.sets (
  id            text primary key,                -- Lorcast set id, e.g. "set_..."
  code          text unique,                     -- e.g. "TFC", "ROF"
  name          text not null,
  released_at   date,
  card_count    int,
  tcgplayer_group_id int,                        -- TCGCSV groupId for joining prices
  inserted_at   timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists sets_released_at_idx on public.sets (released_at desc);

-- ──────────────────────────────────────────────────────────────────────────
-- cards: Lorcana card metadata. Keyed by Lorcast card id.
-- One row per unique card (regardless of printing — printing lives on prices).
-- ──────────────────────────────────────────────────────────────────────────
create table if not exists public.cards (
  id                      text primary key,      -- Lorcast card id
  set_id                  text not null references public.sets(id) on delete cascade,
  name                    text not null,
  version                 text,                  -- subtitle, e.g. "Brave Little Tailor"
  collector_number        text,
  rarity                  text,                  -- Common, Uncommon, Rare, Super Rare, Legendary, Enchanted, Epic, Iconic, Promo
  ink                     text,                  -- Amber, Amethyst, Emerald, Ruby, Sapphire, Steel, null
  cost                    int,
  inkable                 boolean,
  card_type               text,                  -- Character, Action, Item, Location, Song
  classifications         text[],
  text                    text,                  -- rules text
  flavor_text             text,
  tcgplayer_product_id    int,                   -- bridge to TCGCSV prices
  image_small             text,
  image_normal            text,
  image_large             text,
  inserted_at             timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

create index if not exists cards_set_id_idx on public.cards (set_id);
create index if not exists cards_tcgplayer_product_id_idx on public.cards (tcgplayer_product_id);
create index if not exists cards_rarity_idx on public.cards (rarity);

-- ──────────────────────────────────────────────────────────────────────────
-- prices_daily: one row per (product, date, printing, source, grade).
-- Source-agnostic so TCGCSV (raw) and graded sources coexist.
-- ──────────────────────────────────────────────────────────────────────────
create table if not exists public.prices_daily (
  tcgplayer_product_id  int     not null,
  date                  date    not null,
  printing              text    not null,        -- "Normal", "Foil", "Cold Foil"
  source                text    not null,        -- "tcgcsv", "tcg_price_lookup"
  grade                 text    not null default 'raw',  -- 'raw' or "PSA 10" etc. (non-null so it works in PK)
  low_price             numeric(10,2),
  mid_price             numeric(10,2),
  market_price          numeric(10,2),
  high_price            numeric(10,2),
  direct_low_price      numeric(10,2),
  sample_size           int,                     -- for graded sources from sold listings
  inserted_at           timestamptz not null default now(),
  primary key (tcgplayer_product_id, date, printing, source, grade)
);

create index if not exists prices_daily_product_date_idx
  on public.prices_daily (tcgplayer_product_id, date desc);
create index if not exists prices_daily_date_idx
  on public.prices_daily (date desc);

-- ──────────────────────────────────────────────────────────────────────────
-- card_prices_latest: convenience view, most recent raw price per (card, printing).
-- This is what the site reads for "current price" displays.
-- ──────────────────────────────────────────────────────────────────────────
create or replace view public.card_prices_latest as
select distinct on (p.tcgplayer_product_id, p.printing)
  c.id              as card_id,
  c.set_id,
  c.name,
  c.version,
  c.rarity,
  c.ink,
  c.collector_number,
  c.image_small,
  c.image_normal,
  c.image_large,
  p.tcgplayer_product_id,
  p.printing,
  p.date            as price_date,
  p.low_price,
  p.mid_price,
  p.market_price,
  p.high_price,
  p.direct_low_price
from public.prices_daily p
join public.cards c on c.tcgplayer_product_id = p.tcgplayer_product_id
where p.source = 'tcgcsv'
  and p.grade  = 'raw'
order by p.tcgplayer_product_id, p.printing, p.date desc;

-- ──────────────────────────────────────────────────────────────────────────
-- Row Level Security: public data is world-readable, writes are service-role only.
-- (service_role bypasses RLS automatically, so ETL scripts work without explicit policies.)
-- ──────────────────────────────────────────────────────────────────────────
alter table public.sets         enable row level security;
alter table public.cards        enable row level security;
alter table public.prices_daily enable row level security;

drop policy if exists "sets readable by all"          on public.sets;
drop policy if exists "cards readable by all"         on public.cards;
drop policy if exists "prices_daily readable by all"  on public.prices_daily;

create policy "sets readable by all"
  on public.sets for select using (true);

create policy "cards readable by all"
  on public.cards for select using (true);

create policy "prices_daily readable by all"
  on public.prices_daily for select using (true);

-- ──────────────────────────────────────────────────────────────────────────
-- Auto-update `updated_at` on row changes.
-- ──────────────────────────────────────────────────────────────────────────
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists sets_updated_at  on public.sets;
drop trigger if exists cards_updated_at on public.cards;

create trigger sets_updated_at  before update on public.sets
  for each row execute function public.set_updated_at();
create trigger cards_updated_at before update on public.cards
  for each row execute function public.set_updated_at();
