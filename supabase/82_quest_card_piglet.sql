-- 82_quest_card_piglet.sql — fix Illumineer's-Quest card graded attribution.
--
-- Problem: the client's EXTRAS synthesis stamped EVERY "Extras & Oddities" tile
-- with a synthetic `extras:<pid>` card_id, but graded eBay sales are matched to
-- the REAL Lorcast card_id. So owned graded copies of quest/gift cards never
-- linked to their sales, and the Deep Trouble "Piglet - Pooh Pirate Captain"
-- (#223) wasn't even in `cards` at all — so its sales fell onto the booster
-- #16 Super Rare (Into the Inklands).
--
-- Two-part fix:
--   (client, Index.html) the EXTRAS synthesis now uses the REAL card_id for
--   excludeFromBaseSet entries (the base is dropped from its origin set, so the
--   Extras tile is the only tile — no collision), preferring the Lorcast row
--   over any crd_custom_* duplicate.
--   (this file) (1) insert the Deep Trouble Piglet as a real card so sales can
--   attribute to it, and (2) migrate existing owned items (graded + raw) off the
--   old `extras:<pid>` ids onto the real card_ids.
--
-- The Deep Trouble Piglet's two real graded sales were split off booster #16 by
-- collector-number slab OCR — see scripts/reattribute_quest_cards.py (not pure
-- SQL since it needs OCR); the two item_ids it moved are recorded at the bottom
-- for the record. Idempotent.

-- (1) Deep Trouble Piglet — real card row (was a client-only EXTRAS standalone).
insert into cards (id, set_id, name, version, collector_number, rarity, ink, inks, cost, inkable,
  card_type, classifications, tcgplayer_product_id, image_small, image_normal, image_large, split_printing)
values (
  'crd_custom_544487_piglet_pooh',
  'set_8f4cbf5aef324eb295c4add5673e684f',   -- Ursula's Return (matches its Deep Trouble siblings)
  'Piglet', 'Pooh Pirate Captain', '223', 'Super Rare',
  'Amber', array['Amber'], 2, true,
  'Character', array['Dreamborn','Hero','Captain','Pirate'], 544487,
  'https://tcgplayer-cdn.tcgplayer.com/product/544487_200w.jpg',
  'https://tcgplayer-cdn.tcgplayer.com/product/544487_400w.jpg',
  'https://tcgplayer-cdn.tcgplayer.com/product/544487_1000w.jpg',
  false)
on conflict (id) do nothing;

-- (2) Migrate owned items (graded + raw) off extras:<pid> for every
-- excludeFromBaseSet pid (Gift Set Oversized, Deep Trouble, Palace Heist) onto
-- the real card_id (prefer the Lorcast row over a crd_custom_* duplicate).
create temp table _xmap on commit drop as
select x.pid, (select c.id from cards c where c.tcgplayer_product_id = x.pid
               order by (c.id like 'crd_custom_%') asc, c.id limit 1) as new_id
from (values (516778),(516775),(539145),(539148),
             (557538),(544485),(544492),(544494),(544487),
             (634262),(634263),(634264),(634265)) x(pid);

insert into graded_collection_items (user_id, card_id, printing, grader, grade, quantity, amount_paid, acquired_date, custom_value, updated_at)
select g.user_id, m.new_id, g.printing, g.grader, g.grade, g.quantity, g.amount_paid, g.acquired_date, g.custom_value, now()
from graded_collection_items g join _xmap m on g.card_id = 'extras:'||m.pid
where m.new_id is not null
on conflict (user_id, card_id, printing, grader, grade)
  do update set quantity = greatest(graded_collection_items.quantity, excluded.quantity), updated_at = now();
delete from graded_collection_items g using _xmap m where g.card_id = 'extras:'||m.pid and m.new_id is not null;

insert into collection_items (user_id, card_id, printing, condition, quantity, notes, added_at, updated_at)
select ci.user_id, m.new_id, ci.printing, ci.condition, ci.quantity, ci.notes, ci.added_at, now()
from collection_items ci join _xmap m on ci.card_id = 'extras:'||m.pid
where m.new_id is not null
on conflict (user_id, card_id, printing, condition)
  do update set quantity = greatest(collection_items.quantity, excluded.quantity), updated_at = now();
delete from collection_items ci using _xmap m where ci.card_id = 'extras:'||m.pid and m.new_id is not null;

select public.refresh_graded_sales_rollup();

-- For the record (already applied via scripts/reattribute_quest_cards.py): the two
-- Deep Trouble Piglet graded sales split off booster #16 by slab OCR (cn 223):
--   update graded_sales set card_id='crd_custom_544487_piglet_pooh'
--   where item_id in ('326240497349','305975455093');
