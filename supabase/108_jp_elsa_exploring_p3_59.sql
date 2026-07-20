-- 108_jp_elsa_exploring_p3_59.sql
--
-- Japanese-exclusive promo: Elsa - Exploring the Unknown, 59/P3 (foil).
-- Not indexed by Lorcast and not sold on TCGplayer US (only JP retailers /
-- Cardmarket), so it never surfaced in the pid-based promo audit. Added as a
-- synthetic cards row the same way as Snow White - Unexpected Houseguest 41/P3
-- (JP, migration 52): clone the English "Exploring the Unknown" promo (P3 #22),
-- null the pid (no US price / buy link). Index.html REGIONAL_EXCLUSIVE_LABEL
-- stamps the "Japanese Exclusive" label; the row carries the shared English
-- illustration as interim art until a JP scan is dropped into Logos/cards/.
insert into cards (id, set_id, name, version, collector_number, rarity, ink, cost, inkable,
  card_type, classifications, text, flavor_text, tcgplayer_product_id,
  image_small, image_normal, image_large, inks, illustrators, strength, willpower, lore, move_cost, split_printing, foil_split)
select 'crd_promo3_59_elsa_exploring_ja', set_id, name, version, '59', rarity, ink, cost, inkable,
  card_type, classifications, text, flavor_text, null,
  image_small, image_normal, image_large, inks, illustrators, strength, willpower, lore, move_cost, split_printing, foil_split
from cards where id = 'crd_309a0e71b66c4ba492590374f92d9598'  -- Elsa - Exploring the Unknown, P3 #22
on conflict (id) do nothing;

notify pgrst, 'reload schema';
