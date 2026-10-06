-- 187: Starter Deck Foils are the Holofoil printing (2026-10-06).
--
-- STAGED: apply RIGHT AFTER the deploy that ships the "Starter Deck Foil"
-- client change (EXTRAS_MAP printing:"Holofoil"). The live client before that
-- deploy still reads these entries as Cold Foil; applied early, the 9 owners'
-- tiles read unowned until the deploy lands.
--
-- The 12 Extras & Oddities tiles took the product's in-pack Cold Foil row, so
-- every collection entry made on them was saved as Cold Foil. The tile is now
-- the Holofoil row (the starter-deck foil itself), so the entries move with it.
-- On 2026-10-06 that was 47 rows from 9 users, all Cold Foil, and no Holofoil
-- row existed for these ids; the merge below only matters if one appears.
-- Nothing else references these ids (deck_cards, graded, watchlists, goals
-- were checked: none).

begin;

create temporary table _sdf_ids (card_id text primary key) on commit drop;
insert into _sdf_ids values
  ('extras:678236'), ('extras:678237'), ('extras:678238'), ('extras:690204'),
  ('extras:647652'), ('extras:647681'), ('extras:649224'), ('extras:650077'),
  ('extras:653916'), ('extras:657892'), ('extras:657893'), ('extras:657894');

-- A Holofoil row already there was made on the new client before this ran,
-- most likely the same card entered again because the tile read 0. So the two
-- are not added: the larger count stands and the Cold Foil row goes.
update public.collection_items h
   set quantity = greatest(h.quantity, c.quantity),
       notes = coalesce(h.notes, c.notes),
       updated_at = now()
  from public.collection_items c
 where c.card_id in (select card_id from _sdf_ids)
   and c.printing = 'Cold Foil'
   and h.user_id = c.user_id and h.card_id = c.card_id
   and h.condition is not distinct from c.condition
   and h.printing = 'Holofoil';

delete from public.collection_items c
 using public.collection_items h
 where c.card_id in (select card_id from _sdf_ids)
   and c.printing = 'Cold Foil'
   and h.user_id = c.user_id and h.card_id = c.card_id
   and h.condition is not distinct from c.condition
   and h.printing = 'Holofoil';

update public.collection_items
   set printing = 'Holofoil', updated_at = now()
 where card_id in (select card_id from _sdf_ids)
   and printing = 'Cold Foil';

commit;

notify pgrst, 'reload schema';
