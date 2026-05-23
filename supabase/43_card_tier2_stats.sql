-- Tier 2 stat columns on cards: strength / willpower / lore / move_cost.
--
-- Lorcast exposes all four directly on every card payload. Adding them
-- unlocks smart-search filters in the Cards browse like "lore 2",
-- "str>=4", "wil 5". Backfill with scripts/patch_card_tier2.py after
-- running this migration; future weekly Lorcast cron will populate
-- new cards directly via load_lorcast.py.
--
-- Move cost: Lorcana Location cards have a "Move Cost N" stat. Lorcast
-- exposes it as `move_cost`. Non-locations have it as null.
--
-- All four are nullable. Action / Item / Song cards don't have
-- strength/willpower/lore. Characters don't have move_cost.
--
-- Idempotent: add columns only if missing.

alter table public.cards
  add column if not exists strength   int,
  add column if not exists willpower  int,
  add column if not exists lore       int,
  add column if not exists move_cost  int;

-- Indexes — small selectivity gain on the screener/cards filter joins.
-- Only the three primary stats; move_cost is rarely filtered on.
create index if not exists cards_lore_idx       on public.cards (lore);
create index if not exists cards_strength_idx   on public.cards (strength);
create index if not exists cards_willpower_idx  on public.cards (willpower);

notify pgrst, 'reload schema';
