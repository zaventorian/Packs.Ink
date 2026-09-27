-- 169_tcgplayer_names.sql — TCGplayer's own spelling of a card, where it
-- differs from ours (2026-09-25).
--
-- TCGplayer's mass-entry cart ("Buy bulk on TCGplayer") matches on TCGplayer's
-- exact product name, and 470 of 3,229 linked cards are spelled differently
-- there: 21 fail outright ("Chief Bogo- Commanding Officer", "The Sword of Shan
-- Yu", "Walk the Plank", straight apostrophes, no macron on Te Ka) and ~450
-- carry a rarity suffix ("Hades - Infernal Schemer (Enchanted)") without which
-- mass entry silently picks the base printing — the wrong card in the cart.
--
-- Keyed by product id, not card id, so a CONNECTING_FOILS companion ("X
-- (Foil)", a separate TCGplayer product under the base card's id) is covered
-- too. Only DIFFERING names are stored, so the client fetches a few hundred
-- rows. Filled by scripts/sync_tcgplayer_names.py (daily, in etl.yml).

create table if not exists public.tcgplayer_names (
  product_id  bigint primary key,
  name        text   not null,
  updated_at  timestamptz not null default now()
);

alter table public.tcgplayer_names enable row level security;

drop policy if exists tcgplayer_names_read on public.tcgplayer_names;
create policy tcgplayer_names_read on public.tcgplayer_names
  for select to anon, authenticated using (true);

grant select on public.tcgplayer_names to anon, authenticated;
grant select, insert, update, delete on public.tcgplayer_names to service_role;

notify pgrst, 'reload schema';
