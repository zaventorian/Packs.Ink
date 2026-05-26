-- 52_promo_set_1_snow_white_japanese.sql — add the Japanese-only Snow White
-- promo to Promo Set 1.
--
-- Lorcast does not index this card (their /search returns only the Rise of
-- the Floodborn #24 version). It's a Japanese-market exclusive promo
-- numbered #41 in the Promo Set 1 sequence. Without this row the card is
-- invisible in Collection / Cards / completion math and users can't track
-- it as owned.
--
-- Pattern mirrors the existing 25ja / 25zh entries already in Promo Set 1
-- (Mickey Mouse - True Friend). tcgplayer_product_id is null (no TCGPlayer
-- listing for the Japanese-only printing). Image fields are null — the
-- client's JAPAN_ONLY_NONFOIL map points the catalog at a locally-hosted
-- image (Logos/cards/snow-white-unexpected-houseguest-japanese.png).
--
-- If/when Lorcast indexes the card, load_lorcast.py's upsert will just
-- overwrite this stub with the canonical Lorcast metadata.

-- Stats read off the card image (41/P1 · JA · 2):
--   Cost 2, Strength 1, Willpower 2
--   Amber ink, inkable
--   Classifications: Storyborn, Hero, Princess
--   Card type: Character (implied by the Strength + Willpower stats)
insert into public.cards (id, set_id, name, version, collector_number, rarity, ink, inks,
  cost, inkable, card_type, classifications, strength, willpower,
  tcgplayer_product_id, image_small, image_normal, image_large, inserted_at, updated_at)
values (
  'crd_promo1_41_snowwhite_uhg_ja',
  'set_c254adfcbf6d4e3482a675ecece86dcc',  -- Promo Set 1
  'Snow White',
  'Unexpected Houseguest',
  '41',
  'Promo',
  'Amber',
  ARRAY['Amber']::text[],
  2,           -- cost
  true,        -- inkable
  'Character',
  ARRAY['Storyborn','Hero','Princess']::text[],
  1,           -- strength
  2,           -- willpower
  null,        -- no TCGPlayer listing
  null, null, null,  -- images served client-side via JAPAN_ONLY_NONFOIL
  now(), now()
)
on conflict (id) do nothing;

notify pgrst, 'reload schema';
