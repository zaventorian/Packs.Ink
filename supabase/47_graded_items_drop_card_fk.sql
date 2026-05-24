-- Drop the foreign key on graded_collection_items.card_id so users can
-- save synthetic Extras & Oddities cards (Half Hexwell Crown, Palace
-- Heist standalones, Genie Two Swords Variant, Peter Pan Text Error,
-- etc.) whose card_id is a client-generated string like "extras:557538"
-- or "<base>::variant::<slug>" rather than a real Lorcast id.
--
-- The same was done previously for collection_items in migration 11.
-- Symptom that motivated this: clicking "+" on Half Hexwell Crown's tile
-- and trying to save threw:
--   insert or update on table "graded_collection_items" violates foreign
--   key constraint "graded_collection_items_card_id_fkey"
--
-- Tradeoff: orphan rows are possible if a card is ever deleted from
-- `cards`. Cards aren't deleted in practice; the UI tolerates unknown
-- card_ids by hiding them from the grid.

alter table public.graded_collection_items
  drop constraint if exists graded_collection_items_card_id_fkey;

notify pgrst, 'reload schema';
