-- 168_curators_cc2.sql
--
-- Create the "Curator's Collection: Beauty and the Beast" promo set (code
-- CC2), the second entry in the Curator's Collection line (see 107 for CC1,
-- "Curator's Collection: Heroines"). Announced at D23 2026; six premium
-- foil promo reprints, sold ~$99.99 at a handful of Disney locations
-- starting 2026-10-01. Not on TCGplayer yet, so tcgplayer_group_id stays
-- null — same steady state 107 shipped CC1 with.
--
-- The six cards themselves are added client/script-side via REPRINT_PROMOS
-- in scripts/patch_pid_overrides.py (clone of the base booster printing,
-- new id, this set + collector number, rarity=Promo). Run that script after
-- this migration lands.

insert into sets (id, code, name, released_at, card_count, tcgplayer_group_id)
values ('set_curators_cc2', 'CC2', 'Curator''s Collection: Beauty and the Beast', '2026-10-01', 6, null)
on conflict (id) do update
  set code = excluded.code, name = excluded.name,
      released_at = excluded.released_at, card_count = excluded.card_count;

notify pgrst, 'reload schema';
