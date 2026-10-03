-- 179: Illumineer's Quest sets (Q1 Deep Trouble, Q2 Palace Heist) + the
-- "Quest" rarity for every quest card.
--
-- The cards inside an Illumineer's Quest box (the Ursula / Jafar / Vine
-- scenario decks) are game components for a co-op board game, not promos.
-- Lorcast indexed only Q3 (The Great Hunny Rescue, 2026-10-02) and filed its
-- 37 cards as rarity Promo. Q1 and Q2 were never indexed; their 31 + 35 cards
-- are loaded by scripts/import_quest_cards.py from LorcanaJSON.
--
-- The two sets are hand-minted with Lorcast's own codes (Q1 / Q2). If Lorcast
-- ever indexes them, load_lorcast.py skips the colliding set row (the code
-- UNIQUE check), so no duplicate set appears.
--
-- cards.rarity = 'Quest' for all three. load_lorcast.py now writes 'Quest' for
-- any set whose code starts with Q, so the daily Lorcast load keeps it.

insert into public.sets (id, code, name, released_at)
values
  ('set_quest_q1', 'Q1', 'Illumineer''s Quest: Deep Trouble', '2024-05-17'),
  ('set_quest_q2', 'Q2', 'Illumineer''s Quest: Palace Heist', '2025-05-30')
on conflict (id) do update
  set code = excluded.code, name = excluded.name, released_at = excluded.released_at;

update public.cards c
   set rarity = 'Quest'
  from public.sets s
 where s.id = c.set_id
   and s.code in ('Q1', 'Q2', 'Q3')
   and c.rarity is distinct from 'Quest';

notify pgrst, 'reload schema';
