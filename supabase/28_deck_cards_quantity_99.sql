-- Relax the deck_cards.quantity CHECK constraint from ≤4 to ≤99.
--
-- Why: Lorcana grants per-card-text exceptions to the 4-copy deck rule.
--   - Dalmatian Puppy - Tail Wagger: up to 99 copies, variants share total
--   - Microbots: unlimited copies
-- Client-side caps at 99 already (SPECIAL_DECK_LIMITS + getDeckLimitForUI in
-- Index.html), but the original 13_decks.sql baked quantity ≤ 4 into the
-- database, so the upsert failed with deck_cards_quantity_check on any
-- legitimate 5+ copy attempt.
--
-- Variant-sharing for Dalmatian Puppy is still enforced by checkDeckLegality
-- on the client; the DB only enforces the upper bound on a single row.
--
-- Idempotent: drops the existing constraint by exact name and recreates.

alter table public.deck_cards
  drop constraint if exists deck_cards_quantity_check;

alter table public.deck_cards
  add constraint deck_cards_quantity_check check (quantity > 0 and quantity <= 99);

notify pgrst, 'reload schema';
