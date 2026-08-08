-- 117_null_generated_tournament_deck_names.sql
--
-- ⚠️ DATA MIGRATION — REVIEW THE DRY RUN BEFORE APPLYING.
--    Run supabase/diagnostics/generated_tournament_deck_names.sql first; it
--    reports the exact rows this touches, grouped by pattern, with samples.
--
-- Backfills migration 116. Historic tournament uploads persisted a generated
-- deck name because the client substituted one for a blank field before
-- calling the RPC. This nulls those out so they render the same way a newly
-- blanked name does.
--
-- Two patterns are cleared:
--   ink_combo    — name is exactly the deck's own ink list, in any order or
--                  separator ("Amber/Emerald", "amber emerald"). This is the
--                  COMMON case: any row whose decklist parsed has inks, so the
--                  ink branch fired before the "<Player>'s deck" branch ever
--                  could.
--   players_deck — name is exactly "<player_name>'s deck".
--
-- A third pattern, the literal "Untitled deck", is DETECTED and reported but
-- deliberately NOT cleared — an uploader may have typed it on purpose. Uncomment
-- the marked line to include it.
--
-- Scope: only decks reachable from tournament_decks. User decks are untouched,
-- and in any case store their name AES-GCM-encrypted ("e1:" prefix), so these
-- plaintext patterns cannot match one.
--
-- Idempotent: the CTE skips rows already NULL, so re-running is a no-op.
-- Reversible: prior values are copied to the backup table below first.

create table if not exists public._tournament_deck_name_backup_116 (
  deck_id      uuid primary key,
  old_name     text not null,
  pattern      text not null,
  backed_up_at timestamptz not null default now()
);

with named as (
  select d.id, d.name, d.inks, td.player_name
    from public.decks d
    join public.tournament_decks td on td.deck_id = d.id
   where d.name is not null
     and btrim(d.name) <> ''
), tokens as (
  select n.*,
         (select array_agg(lower(v) order by lower(v))
            from unnest(coalesce(n.inks, '{}'::text[])) v
           where btrim(v) <> '')                                      as ink_sorted,
         (select array_agg(w order by w)
            from unnest(regexp_split_to_array(lower(btrim(n.name)), '[\s/,\-]+')) w
           where w <> '')                                             as name_sorted
    from named n
), classified as (
  select t.id, t.name,
         case
           when t.player_name is not null
            and lower(btrim(t.name)) = lower(btrim(t.player_name)) || '''s deck'
             then 'players_deck'
           when t.ink_sorted is not null
            and t.name_sorted is not null
            and t.name_sorted = t.ink_sorted
             then 'ink_combo'
           when lower(btrim(t.name)) = 'untitled deck'
             then 'untitled'
         end as pattern
    from tokens t
)
insert into public._tournament_deck_name_backup_116 (deck_id, old_name, pattern)
select c.id, c.name, c.pattern
  from classified c
 where c.pattern in ('players_deck', 'ink_combo')
 --  or c.pattern = 'untitled'   -- uncomment to also clear literal "Untitled deck"
on conflict (deck_id) do nothing;

update public.decks d
   set name       = null,
       updated_at = now()
  from public._tournament_deck_name_backup_116 b
 where d.id = b.deck_id
   and d.name is not null;

notify pgrst, 'reload schema';

-- Rollback (run by hand if needed):
--   update public.decks d set name = b.old_name
--     from public._tournament_deck_name_backup_116 b
--    where d.id = b.deck_id and d.name is null;
--
-- Once you're satisfied, drop the backup:
--   drop table public._tournament_deck_name_backup_116;
