-- 118_clear_deck_names_two_tournaments.sql
--
-- Targeted version of 117, scoped to the two tournaments uploaded 2026-08-08
-- (~00:20 and ~00:21 UTC) whose decks all carry a generated "<Player>'s deck"
-- name. 117 remains available for the older ~23 tournaments.
--
-- ⚠️ REQUIRES MIGRATION 116 FIRST. decks.name is still NOT NULL until 116 runs;
--    without it every statement below fails with 23502.
--
-- Verified before writing this: all 16 decks across both events are generated
-- names (every one ends in "'s deck"). None was hand-typed, so clearing the
-- whole set cannot lose real data. Run the SELECT below to re-confirm on your
-- own data before the UPDATE.
--
-- Idempotent: rows already NULL are skipped. Reversible via the backup table.

-- ── verify first (expect 16 rows, every name ending in "'s deck") ──
-- select t.name as tournament, td.place, td.player_name, d.name as deck_name
--   from public.decks d
--   join public.tournament_decks td on td.deck_id = d.id
--   join public.tournaments t on t.id = td.tournament_id
--  where td.tournament_id in (
--          '70bb4f01-81f5-4b17-b748-20799aed8f25',  -- Ink Inc Open - Attack of the Vines $3k
--          '4f3cddb2-d8c1-4d5a-bc16-eed2328a0de6')  -- Mega Mulligan Challenge #29
--    and d.name is not null
--  order by t.name, td.place_rank;

-- Shared with 117 so either order works and neither double-backs-up a row.
create table if not exists public._tournament_deck_name_backup_116 (
  deck_id      uuid primary key,
  old_name     text not null,
  pattern      text not null,
  backed_up_at timestamptz not null default now()
);

insert into public._tournament_deck_name_backup_116 (deck_id, old_name, pattern)
select d.id, d.name, 'scoped_two_tournaments'
  from public.decks d
  join public.tournament_decks td on td.deck_id = d.id
 where td.tournament_id in (
         '70bb4f01-81f5-4b17-b748-20799aed8f25',
         '4f3cddb2-d8c1-4d5a-bc16-eed2328a0de6')
   and d.name is not null
on conflict (deck_id) do nothing;

update public.decks d
   set name       = null,
       updated_at = now()
  from public.tournament_decks td
 where td.deck_id = d.id
   and td.tournament_id in (
         '70bb4f01-81f5-4b17-b748-20799aed8f25',
         '4f3cddb2-d8c1-4d5a-bc16-eed2328a0de6')
   and d.name is not null;

notify pgrst, 'reload schema';

-- Rollback:
--   update public.decks d set name = b.old_name
--     from public._tournament_deck_name_backup_116 b
--    where d.id = b.deck_id and d.name is null
--      and b.pattern = 'scoped_two_tournaments';
