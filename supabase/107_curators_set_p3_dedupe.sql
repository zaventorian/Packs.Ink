-- 107_curators_set_p3_dedupe.sql
--
-- Two changes, both catalog hygiene for the current promo wave:
--
-- 1. Create the "Curator's Collection: Heroines" promo set (code CC1). Its 6
--    singles (Ariel/Elsa/Jasmine/Mulan/Anna/Tinker Bell, one per ink) are built
--    as promo reprints by scripts/patch_pid_overrides.py (REPRINT_PROMOS).
--
-- 2. De-duplicate Promo Set 3 #52-55. Those cards had TWO catalog rows each:
--    a Lorcast-indexed row (crd_<hash>, tcgplayer_id null, auto-maintained by
--    load_lorcast) and a hand-built crd_custom_ row carrying the pid. Lorcast
--    now indexes #52-55, so the crd_custom_ rows are redundant duplicate tiles.
--    patch_pid_overrides.py now applies the pid to the Lorcast row via OVERRIDES
--    (and no longer mints the crd_custom_ rows), so here we repoint any user
--    collection refs onto the Lorcast row (matched by collector number) and drop
--    the crd_custom_ rows. #56 (Buzz - On the Way) is NOT dedup'd — Lorcast's P3
--    feed stops at #55, so it legitimately stays a synthetic crd_custom_ row.

-- 1. Curator's Collection: Heroines set ---------------------------------------
insert into sets (id, code, name, released_at, card_count, tcgplayer_group_id)
values ('set_curators_cc1', 'CC1', 'Curator''s Collection: Heroines', '2026-07-17', 6, null)
on conflict (id) do update
  set code = excluded.code, name = excluded.name,
      released_at = excluded.released_at, card_count = excluded.card_count;

-- 2. Repoint user + sales refs off the redundant crd_custom_ P3 #52-55 rows
--    onto the Lorcast-indexed rows (matched by collector number), then drop the
--    customs. graded_sales.card_id is the only FK to cards; deck_cards /
--    collection_items / graded_collection_items reference by plain text. The
--    Lorcast target rows had 0 refs of any kind, so no PK/unique conflict.
--    (Only collection_items[#52-54] and graded_sales[#54] actually had rows at
--     authoring time; the rest are defensive no-ops.)
update collection_items        set card_id='crd_a8d42353d6374c619c35808f08b541de' where card_id='crd_custom_692484_dash_lava_runner';
update deck_cards              set card_id='crd_a8d42353d6374c619c35808f08b541de' where card_id='crd_custom_692484_dash_lava_runner';
update graded_collection_items set card_id='crd_a8d42353d6374c619c35808f08b541de' where card_id='crd_custom_692484_dash_lava_runner';
update graded_sales            set card_id='crd_a8d42353d6374c619c35808f08b541de' where card_id='crd_custom_692484_dash_lava_runner';

update collection_items        set card_id='crd_c31abedb3b3b4b0fa489a81a926c5544' where card_id='crd_custom_692485_woody_jungle_participant';
update deck_cards              set card_id='crd_c31abedb3b3b4b0fa489a81a926c5544' where card_id='crd_custom_692485_woody_jungle_participant';
update graded_collection_items set card_id='crd_c31abedb3b3b4b0fa489a81a926c5544' where card_id='crd_custom_692485_woody_jungle_participant';
update graded_sales            set card_id='crd_c31abedb3b3b4b0fa489a81a926c5544' where card_id='crd_custom_692485_woody_jungle_participant';

update collection_items        set card_id='crd_6f2320ba4a3d46c682bcde01adf01fc1' where card_id='crd_custom_692486_woody_jungle_sc';
update deck_cards              set card_id='crd_6f2320ba4a3d46c682bcde01adf01fc1' where card_id='crd_custom_692486_woody_jungle_sc';
update graded_collection_items set card_id='crd_6f2320ba4a3d46c682bcde01adf01fc1' where card_id='crd_custom_692486_woody_jungle_sc';
update graded_sales            set card_id='crd_6f2320ba4a3d46c682bcde01adf01fc1' where card_id='crd_custom_692486_woody_jungle_sc';

update collection_items        set card_id='crd_cd7cdf11610c49d38bafb413eb06ba5e' where card_id='crd_custom_692487_violet_new_powers';
update deck_cards              set card_id='crd_cd7cdf11610c49d38bafb413eb06ba5e' where card_id='crd_custom_692487_violet_new_powers';
update graded_collection_items set card_id='crd_cd7cdf11610c49d38bafb413eb06ba5e' where card_id='crd_custom_692487_violet_new_powers';
update graded_sales            set card_id='crd_cd7cdf11610c49d38bafb413eb06ba5e' where card_id='crd_custom_692487_violet_new_powers';

-- Drop the now-orphaned duplicate rows.
delete from cards where id in (
  'crd_custom_692484_dash_lava_runner',
  'crd_custom_692485_woody_jungle_participant',
  'crd_custom_692486_woody_jungle_sc',
  'crd_custom_692487_violet_new_powers'
);

notify pgrst, 'reload schema';
