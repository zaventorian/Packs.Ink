-- 200: move Deep Trouble Piglet copies off Lorcast's hidden duplicate.
--
-- From 2026-10-03 the Extras tile for pid 544487 saved to the suppressed
-- crd_318c41d06e2340debaba878e3c926cdc, while the copies added before that sit on
-- crd_custom_544487_piglet_pooh, which then had no tile. Index.html v548 points the
-- tile back at the custom id.
--
-- APPLY AFTER v548 IS LIVE: until then the tile still reads the suppressed id, and
-- these copies would vanish from it. Safe to re-run for a stray write from an old tab.
--
-- A person holding both most likely re-added the copy that vanished, so the larger
-- quantity wins rather than the sum. 2026-11-02: 3 such rows, all 1 + 1.
begin;

update public.collection_items keep
   set quantity = greatest(keep.quantity, dup.quantity),
       notes = coalesce(keep.notes, dup.notes)
  from public.collection_items dup
 where keep.card_id = 'crd_custom_544487_piglet_pooh'
   and dup.card_id = 'crd_318c41d06e2340debaba878e3c926cdc'
   and keep.user_id = dup.user_id
   and keep.printing = dup.printing
   and keep.condition = dup.condition;

delete from public.collection_items dup
 using public.collection_items keep
 where keep.card_id = 'crd_custom_544487_piglet_pooh'
   and dup.card_id = 'crd_318c41d06e2340debaba878e3c926cdc'
   and keep.user_id = dup.user_id
   and keep.printing = dup.printing
   and keep.condition = dup.condition;

update public.collection_items
   set card_id = 'crd_custom_544487_piglet_pooh'
 where card_id = 'crd_318c41d06e2340debaba878e3c926cdc';

commit;
