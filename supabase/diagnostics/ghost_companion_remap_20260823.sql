-- Ghost-collection repair: collection_items rows stored under a
-- CONNECTING_FOILS *companion* card_id. The client transform suppresses those
-- ids (their foil row is re-emitted under the BASE card's card_id), so such
-- rows count in the collection header but render no tile anywhere, and the
-- Export CSV reports them as "skipped — no longer in the catalog".
--
-- Diagnostic run 2026-08-23 (service-role REST, all users):
--   4 rows · 8 copies · 1 user (the demo account a871f6b1-…) — the four
--   Winterspell companions (Iduna / Agnarr / Roo / Kanga), all Cold Foil.
--   0 merge conflicts (no target rows exist). 0 orphan card_ids anywhere else.
--
-- This script is generic + rerunnable: it derives companion→base from the
-- CONNECTING_FOILS pairs (mirrors Index.html — keep in sync if pairs change),
-- merges quantities into the base slot on conflict, then deletes the
-- companion rows. Run the two SELECTs first; apply the DO block only after
-- eyeballing them.

-- 1) Preview: what would be remapped.
with pairs(base_pid, foil_pid) as (values
  (692014,692015),(692016,692017),(692018,692019),(692020,692021),(692022,692023),
  (692024,692025),(692026,692027),(692028,692029),(692040,692041),(692050,692093),
  (692179,692180),(692060,692061),(692062,692063),(692081,692082),(690212,692097),
  (675499,678861),(675500,678862),(676217,678863),(676218,678864),
  (631349,633427),(631350,633428),(631351,633429),(631394,633430),(631431,633431),
  (702684,702683),(702686,702685),(704619,704618),(704621,704620),(704656,704655),(704658,704657)
), map as (
  select comp.id as companion_id, base.id as base_id, comp.name
  from pairs
  join cards comp on comp.tcgplayer_product_id = pairs.foil_pid
  join cards base on base.tcgplayer_product_id = pairs.base_pid
)
select ci.user_id, m.name, ci.card_id as companion_id, m.base_id, ci.printing, ci.quantity,
       tgt.quantity as existing_target_qty
from collection_items ci
join map m on m.companion_id = ci.card_id
left join collection_items tgt
  on tgt.user_id = ci.user_id and tgt.card_id = m.base_id and tgt.printing = ci.printing;

-- 2) Apply: merge-then-delete. Idempotent — a second run finds nothing.
-- do $$
-- begin
--   with pairs(base_pid, foil_pid) as (values
--     (692014,692015),(692016,692017),(692018,692019),(692020,692021),(692022,692023),
--     (692024,692025),(692026,692027),(692028,692029),(692040,692041),(692050,692093),
--     (692179,692180),(692060,692061),(692062,692063),(692081,692082),(690212,692097),
--     (675499,678861),(675500,678862),(676217,678863),(676218,678864),
--     (631349,633427),(631350,633428),(631351,633429),(631394,633430),(631431,633431),
--     (702684,702683),(702686,702685),(704619,704618),(704621,704620),(704656,704655),(704658,704657)
--   ), map as (
--     select comp.id as companion_id, base.id as base_id
--     from pairs
--     join cards comp on comp.tcgplayer_product_id = pairs.foil_pid
--     join cards base on base.tcgplayer_product_id = pairs.base_pid
--   ), moved as (
--     insert into collection_items (user_id, card_id, printing, quantity)
--     select ci.user_id, m.base_id, ci.printing, ci.quantity
--     from collection_items ci
--     join map m on m.companion_id = ci.card_id
--     on conflict (user_id, card_id, printing)
--       do update set quantity = collection_items.quantity + excluded.quantity
--     returning 1
--   )
--   delete from collection_items ci
--   using map m
--   where m.companion_id = ci.card_id;
-- end $$;
