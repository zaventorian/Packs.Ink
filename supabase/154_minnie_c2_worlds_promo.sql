-- 154_minnie_c2_worlds_promo.sql
--
-- Minnie Mouse - Amethyst Champion, World Championship 2026 promo,
-- Lorcana Challenge Year 3 (C2) #20. Announced by Ravensburger on stream
-- 2026-09-17; Lorcast has not indexed it yet, so this is a manual insert
-- per CLAUDE.md's "Regional-exclusive promos" pattern (migration 52) --
-- Lorcast can overwrite this row later if it ever mints the same card_id,
-- or we can retire this row and re-point references if it lands under a
-- different id (see the catalog-watch `missing_set` note on Curator's CC1
-- for that shape of conflict).
--
-- One row, not two: the reveal said non-foil is what LGS players get, but
-- it isn't yet known whether a foil (Worlds prize) copy will carry a
-- DIFFERENT collector number. Rather than guess and mint a second row,
-- this follows the Challenge Promo (C1) pattern (e.g. Cinderella -
-- Stouthearted's Top Prize/Prize Wall split) -- one card_id, with
-- Non-Foil/Foil distinguished later via `printing` on whatever price rows
-- eventually show up under this tcgplayer_product_id, once one exists.
--
-- Stats/text/ink copied verbatim from the existing mainline printing
-- (crd_7667c79b34784802930a659a5c904ccf, Rare, cost 4/2/3/2 lore,
-- Amethyst) -- same card, different collector number. image_* also
-- borrow that row's Lorcast URLs as a placeholder (same character art),
-- until Lorcast indexes the real promo scan.

insert into public.cards (
  id, set_id, name, version, collector_number, rarity, ink, inks, cost,
  inkable, card_type, classifications, text, flavor_text, illustrators,
  strength, willpower, lore, move_cost, tcgplayer_product_id,
  image_small, image_normal, image_large
) values (
  'crd_c2minniewc2026amethystchamp20',
  'set_dacbe79496a14ffa99567e4ae8577e49', -- Lorcana Challenge Year 3 (C2)
  'Minnie Mouse', 'Amethyst Champion', '20', 'Promo', 'Amethyst', array['Amethyst'], 4,
  true, 'Character', array['Dreamborn','Hero'],
  'MYSTICAL BALANCE Whenever one of your other Amethyst characters is banished in a challenge, you may draw a card.',
  null, array['Lisa Parfenova'],
  2, 3, 2, null, null,
  'https://cards.lorcast.io/card/digital/small/crd_7667c79b34784802930a659a5c904ccf.avif?1761752092',
  'https://cards.lorcast.io/card/digital/normal/crd_7667c79b34784802930a659a5c904ccf.avif?1761752092',
  'https://cards.lorcast.io/card/digital/large/crd_7667c79b34784802930a659a5c904ccf.avif?1761752092'
)
on conflict (id) do nothing;

notify pgrst, 'reload schema';
