-- 160_retire_aotv_promos_set.sql
-- "Attack of the Vine! Promos" (set_aotv_promos) was never a real set. Its
-- three cards are Promo Set 4 #12 / #15 / #16, which Lorcast indexed on
-- 2026-09-18. Move every reference onto the Lorcast rows, drop the stand-ins,
-- and give P4 #9-16 + PD1 #2 their TCGplayer pids. Also adds P3 #61/#62.
--
-- Run step 1 (this whole file) in the SQL editor. Step 2, separately:
--   select public.refresh_card_prices_latest();
--   select public.refresh_graded_sales_rollup();
-- Then: python scripts/patch_pid_overrides.py  (builds P3 #58/#60/#63, PD1 #15)
--
-- User decks store card_id encrypted, so those refs cannot be moved from SQL;
-- a deck holding a stand-in card shows it as unknown until re-added.

begin;

create temp table _avp_map (old_id text primary key, new_id text not null) on commit drop;
insert into _avp_map values
  ('crd_avp_10_tigger_hunny_barbarian',           'crd_1db47bd68c9b4567a8aea3e935a1e0df'),
  ('crd_avp_15_rapunzel_escaping_sc_participant', 'crd_c34200b2cf674408be7b5c850d122434'),
  ('crd_avp_16_rapunzel_escaping_sc_champion',    'crd_d8f350129bf747ba9aaddc15077460c2');

-- Refuse to run if a target row is missing: deleting a stand-in without its
-- target would cascade-delete owned collection rows.
do $$
begin
  if (select count(*) from public.cards c join _avp_map m on c.id = m.new_id) <> 3 then
    raise exception 'P4 target cards missing - run the Lorcast load first';
  end if;
end $$;

-- collection_items: merge quantities where the owner already has the target.
insert into public.collection_items (user_id, card_id, printing, condition, quantity, notes, added_at, updated_at)
select ci.user_id, m.new_id, ci.printing, ci.condition, ci.quantity, ci.notes, ci.added_at, now()
from public.collection_items ci join _avp_map m on ci.card_id = m.old_id
on conflict (user_id, card_id, printing, condition)
do update set quantity = public.collection_items.quantity + excluded.quantity, updated_at = now();
delete from public.collection_items where card_id in (select old_id from _avp_map);

-- graded_collection_items: move, merging a duplicate slot (capped at 99).
update public.graded_collection_items g set quantity = least(99, g.quantity + o.quantity), updated_at = now()
from public.graded_collection_items o join _avp_map m on o.card_id = m.old_id
where g.card_id = m.new_id and g.user_id = o.user_id and g.printing = o.printing
  and g.grader = o.grader and g.grade = o.grade;
delete from public.graded_collection_items o using _avp_map m, public.graded_collection_items g
where o.card_id = m.old_id and g.card_id = m.new_id and g.user_id = o.user_id
  and g.printing = o.printing and g.grader = o.grader and g.grade = o.grade;
update public.graded_collection_items o set card_id = m.new_id
from _avp_map m where o.card_id = m.old_id;

-- watchlist_items / alert_events / deck_cards: move unless the target already
-- exists on the same list / alert / deck, then drop what could not move.
update public.watchlist_items w set card_id = m.new_id from _avp_map m
where w.card_id = m.old_id and not exists (
  select 1 from public.watchlist_items x
  where x.watchlist_id = w.watchlist_id and x.card_id = m.new_id and x.printing = w.printing);
delete from public.watchlist_items where card_id in (select old_id from _avp_map);

update public.alert_events a set card_id = m.new_id from _avp_map m
where a.card_id = m.old_id and not exists (
  select 1 from public.alert_events x
  where x.alert_id = a.alert_id and x.card_id = m.new_id and x.printing = a.printing
    and x.price_date = a.price_date);
delete from public.alert_events where card_id in (select old_id from _avp_map);

update public.deck_cards d set card_id = m.new_id from _avp_map m
where d.card_id = m.old_id and not exists (
  select 1 from public.deck_cards x
  where x.deck_id = d.deck_id and x.card_id = m.new_id and x.printing = d.printing);

-- Plain references with no uniqueness on card_id.
update public.graded_sales        t set card_id = m.new_id from _avp_map m where t.card_id = m.old_id;
update public.grading_submissions t set card_id = m.new_id from _avp_map m where t.card_id = m.old_id;
update public.scan_samples        t set card_id = m.new_id from _avp_map m where t.card_id = m.old_id;
update public.scan_samples        t set predicted_card_id = m.new_id from _avp_map m where t.predicted_card_id = m.old_id;

-- Drop the stand-ins and the set.
delete from public.cards where id in (select old_id from _avp_map);
delete from public.cards where set_id = 'set_aotv_promos';
delete from public.sets  where id = 'set_aotv_promos';

-- TCGplayer pids for Promo Set 4 #9-16 and PD1 #2 (Lorcast leaves them null).
update public.cards c set tcgplayer_product_id = v.pid
from (values
  ('crd_fcd5ed5584c345d5a704ae6ca63907d5', 705078),  -- P4 #9  Morph
  ('crd_c11f3dbe66b641c1b238f59a85d9ad9e', 705080),  -- P4 #10 Meilin Lee
  ('crd_0fc8c420ccb540c58dcee61bb7a0f5fd', 705079),  -- P4 #11 Randall Boggs
  ('crd_1db47bd68c9b4567a8aea3e935a1e0df', 705083),  -- P4 #12 Tigger
  ('crd_5f75f51d10264a9e8df15676a6d012fe', 705082),  -- P4 #13 Belle
  ('crd_5f81d8030a944df18a429df6529b5eb7', 705081),  -- P4 #14 If I Didn't Have You
  ('crd_c34200b2cf674408be7b5c850d122434', 705084),  -- P4 #15 Rapunzel (SC participant)
  ('crd_d8f350129bf747ba9aaddc15077460c2', 705085),  -- P4 #16 Rapunzel (SC, foil)
  ('crd_b1a43b5f8158413f81457f6268bfbc93', 711443)   -- PD1 #2 Rapunzel - Ethereal Protector
) as v(id, pid)
where c.id = v.id;

-- Promo Set 3 #61 / #62: Japan's Fabled Set Championship pair (Maleficent -
-- Monstrous Dragon, participant + Top 8 foil). Not on Lorcast or TCGplayer US,
-- so synthetic rows cloned off the English pair (P3 #4 / #5) with a null pid,
-- same as #59 in migration 108. Index.html labels them Japanese Exclusive.
insert into public.cards (id, set_id, name, version, collector_number, rarity, ink, cost, inkable,
  card_type, classifications, text, flavor_text, tcgplayer_product_id,
  image_small, image_normal, image_large, inks, illustrators, strength, willpower, lore, move_cost, split_printing, foil_split)
select v.new_id, c.set_id, c.name, c.version, v.cn, c.rarity, c.ink, c.cost, c.inkable,
  c.card_type, c.classifications, c.text, c.flavor_text, null,
  c.image_small, c.image_normal, c.image_large, c.inks, c.illustrators, c.strength, c.willpower, c.lore, c.move_cost, c.split_printing, c.foil_split
from (values
  ('crd_p3_61_maleficent_monstrous_dragon_ja', '61', 'crd_a79483514b7249cbb16c12a9ef1d065d'),
  ('crd_p3_62_maleficent_monstrous_dragon_ja', '62', 'crd_d0844776beac4b5e839cff0cb9c31c14')
) as v(new_id, cn, src_id)
join public.cards c on c.id = v.src_id
on conflict (id) do nothing;

commit;

notify pgrst, 'reload schema';
