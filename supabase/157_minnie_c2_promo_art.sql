-- 157_minnie_c2_promo_art.sql
--
-- Follow-up to 156: swaps the Minnie Mouse - Amethyst Champion (C2 #20)
-- placeholder art (the mainline printing's Lorcast URLs) for the real
-- promo photo, which is already a committed site asset -- the same file
-- the Worlds-2026 news article uses (see the `{type:"img", ...}` entry
-- referencing it in Index.html). Idempotent.

update public.cards
set image_small  = 'Logos/news/worlds-2026-minnie-promo.jpg',
    image_normal = 'Logos/news/worlds-2026-minnie-promo.jpg',
    image_large  = 'Logos/news/worlds-2026-minnie-promo.jpg'
where id = 'crd_c2minniewc2026amethystchamp20';

notify pgrst, 'reload schema';
