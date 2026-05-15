-- Add inks[] column to cards.
--
-- Why: Lorcana introduced dual-ink cards (single card with two ink colors,
-- e.g. Ink Geyser is Emerald + Sapphire). Lorcast's API exposes this as
-- `inks: ["Emerald", "Sapphire"]` while the legacy `ink` field is null.
-- Our loader was only reading `ink`, so dual cards land with `ink IS NULL`
-- and the deck-stats pie chart bucketed them as "Unknown".
--
-- Schema change: store the full inks array. Single-ink cards get a one-
-- element array; dual cards get both. The legacy `ink` column is kept and
-- populated with `inks[0]` for code that still reads it (back-compat —
-- safe to drop later once all consumers migrate).
--
-- Idempotent: add column only if missing.

alter table public.cards
  add column if not exists inks text[];

-- Notify PostgREST to refresh schema cache so the new column is visible.
notify pgrst, 'reload schema';
