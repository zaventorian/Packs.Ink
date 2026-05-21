-- 31_card_illustrators.sql — add illustrators[] column to public.cards.
--
-- Why: filter cards by artist in the Cards browse (parity with dreamborn).
-- Lorcast exposes `illustrators: string[]` on every card; we mirror it as a
-- text[] column. Backfill is one-shot via scripts/load_lorcast.py (idempotent
-- — re-running picks up the new column for every existing card).
--
-- Empty array (not null) is the "loaded but no artist credit" state.

alter table public.cards
  add column if not exists illustrators text[];

create index if not exists cards_illustrators_gin_idx
  on public.cards using gin (illustrators);

-- PostgREST schema cache reload so the new column is queryable immediately.
notify pgrst, 'reload schema';
