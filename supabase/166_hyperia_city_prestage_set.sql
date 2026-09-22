-- 166_hyperia_city_prestage_set.sql
-- A set row for Hyperia City (set 14), so its revealed cards can be prestaged
-- from the official gallery before Lorcast indexes the set.
--
-- Lorcast has NO set-14 row at all (checked 2026-09-22: /v0/sets returns 24
-- sets ending at 13 Attack of the Vine!, and /v0/sets/14 is a 404), so unlike
-- set 13 there is no real id to prestage into. This mints one.
--
-- WHY code IS NULL, and it is the whole point of this file:
--   load_lorcast skips any incoming Lorcast set whose `code` is already used by
--   a different id -- AND skips every one of that set's cards with it, to avoid
--   the FK violation. That guard exists for set_curators_cc1. If this row
--   claimed code '14', then the day Lorcast publishes Hyperia City we would
--   silently serve only the handful of cards we prestaged and NEVER load the
--   other ~193 -- on a green daily run, at the exact moment the set launches.
--   `sets.code` is nullable, and `existing_by_code` is built `if r.get("code")`,
--   so a null-code row is invisible to that guard: Lorcast's set 14 lands
--   cleanly under its own id with all 204 cards.
--   Nothing client-side reads sets.code (the app selects id,name,released_at).
--
-- The cost of that choice is a duplicate set row once Lorcast lands, which is
-- the SAFE failure: a visible extra tile plus a few duplicate cards, instead of
-- a silently incomplete catalog on launch day. Converging is then:
--   update cards set set_id = '<lorcast id>' where set_id = 'set_hyperia_city';
--   update sets set tcgplayer_group_id = 24740 where id = '<lorcast id>';
--   delete from sets where id = 'set_hyperia_city';
-- after which retire_prestaged's (set_id, collector_number) key does the rest
-- on its next run, repointing any deck/collection refs before deleting.
--
-- released_at 2026-10-16 is the LGS date in SET_RELEASE_DATES and is also
-- TCGCSV group 24740's publishedOn, to the day. card_count 204 is the "n/204"
-- total on every set-14 card_identifier in the official gallery.
--
-- tcgplayer_group_id is set explicitly rather than left for the ETL: group
-- 24740 is named exactly 'Hyperia City', so update_set_group_mapping would bind
-- it on the next run anyway by name match -- doing it here makes it immediate
-- and deterministic, and is what lets link_preorder_pids start walking the set
-- for singles and load_sealed_products bind the 8 sealed SKUs already listed.

insert into public.sets (id, code, name, released_at, card_count, tcgplayer_group_id)
values ('set_hyperia_city', null, 'Hyperia City', '2026-10-16', 204, 24740)
on conflict (id) do update
  set name               = excluded.name,
      released_at        = excluded.released_at,
      card_count         = excluded.card_count,
      tcgplayer_group_id = excluded.tcgplayer_group_id;

notify pgrst, 'reload schema';
