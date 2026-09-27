-- 171: two more playmat sections.
--
-- Zaven, 2026-09-27: the Disney-location mats and the Ravensburger online-store
-- mats each get a header of their own on the Playmats tab, instead of sitting
-- in Retail with the shop named on the tile. The section is the grouping, so
-- the table has to accept the two new values (see scripts/load_playmats.py).
--
-- Widens the CHECK from 170 and nothing else. Safe before or after the client:
-- nothing reads a section it does not know (an unknown one lands in "Other").

alter table public.playmats drop constraint if exists playmats_section_chk;
alter table public.playmats add constraint playmats_section_chk
  check (section in ('retail', 'disney', 'ravensburger', 'set_champ', 'dlc', 'event', 'other'));

notify pgrst, 'reload schema';
