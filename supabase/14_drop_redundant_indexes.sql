-- Drop indexes whose leading columns are already covered by the table's
-- primary key. The PK's btree serves any query that filters on a prefix
-- of its column list, so a separate index on just the leading columns is
-- pure write-amplification.
--
-- Confirmed via supabase/diagnostics/index_usage_audit.sql.
--
-- collection_items PK = (user_id, card_id, printing, condition)
--   collection_items_user_idx on (user_id) -> redundant.
--
-- deck_cards PK = (deck_id, card_id, printing)
--   deck_cards_deck_idx on (deck_id) -> redundant.

drop index if exists public.collection_items_user_idx;
drop index if exists public.deck_cards_deck_idx;
