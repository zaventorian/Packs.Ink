-- 53_graded_goals_printings.sql
--
-- Adds a `printings text[]` column to graded_collection_goals so set goals
-- can scope to specific printings (Foil / Non-Foil) rather than always
-- tracking every printing of every base-rarity card in the set.
--
-- Why: previously, adding a "Common-Legendary in TFC" goal pulled in
-- every Common (Normal + Foil = 2x the card list), which most users don't
-- want to grade. The new UI on the Add Goal modal now requires the user
-- to pick at least one printing when they select any base rarity (Common
-- / Uncommon / Rare / Super Rare / Legendary). Chase rarities (Epic /
-- Enchanted / Iconic / Promo) bypass — they have only one printing per
-- card and aren't affected by this filter.
--
-- Storage: NULL = no printing filter (legacy goals, or chase-only goals
-- where the printing picker is hidden). Non-NULL = filter to the listed
-- printings — values are the user-facing labels "Foil" and "Non-Foil",
-- mapped client-side onto each card row's tcg_printing.
--
-- Backfill: leave existing rows NULL. Their goals continue to track all
-- printings, matching pre-migration behavior. New goals created via the
-- updated UI will set this explicitly.

ALTER TABLE public.graded_collection_goals
  ADD COLUMN IF NOT EXISTS printings text[] NULL;

COMMENT ON COLUMN public.graded_collection_goals.printings IS
  'Optional list of printing-category labels (Foil / Non-Foil) the goal scopes to. NULL = no printing filter (track all printings).';

NOTIFY pgrst, 'reload schema';
