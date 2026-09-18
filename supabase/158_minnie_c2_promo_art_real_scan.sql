-- 158_minnie_c2_promo_art_real_scan.sql
--
-- Follow-up to 157: swaps the Minnie Mouse - Amethyst Champion (C2 #20)
-- image again, this time for an isolated card-only photo (no slide chrome,
-- no announcement text) -- 157's asset was a screenshot of the whole
-- "Upcoming Challenge Events" prizing slide with the card floating inside
-- it, reused only because it was the one committed asset available at the
-- time. Now hosted at Logos/cards/minnie-mouse-amethyst-champion-c2-promo.jpg,
-- following the CHINA_ONLY_NONFOIL / JAPAN_ONLY_NONFOIL "local image" pattern
-- for a regional/promo-only card Lorcast hasn't indexed. Idempotent.
--
-- Already applied directly to prod (2026-09-18).

update public.cards
set image_small  = 'Logos/cards/minnie-mouse-amethyst-champion-c2-promo.jpg',
    image_normal = 'Logos/cards/minnie-mouse-amethyst-champion-c2-promo.jpg',
    image_large  = 'Logos/cards/minnie-mouse-amethyst-champion-c2-promo.jpg'
where id = 'crd_c2minniewc2026amethystchamp20';

notify pgrst, 'reload schema';
