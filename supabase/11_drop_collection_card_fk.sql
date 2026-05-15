-- Drop the hard FK on collection_items.card_id so the client can store
-- collection rows for synthetic card variants (e.g. starter-deck-exclusive
-- foils) that live only in the client-side catalog, not in the cards table
-- proper. The application-level read path already filters orphaned card_ids
-- defensively via cardByKey lookups, so losing referential integrity here
-- doesn't change behavior — it just unblocks variant rows.
--
-- Idempotent: drop is guarded by `if exists`.

alter table public.collection_items
  drop constraint if exists collection_items_card_id_fkey;
