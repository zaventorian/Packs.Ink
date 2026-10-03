-- 178_challenge_c3_set.sql
-- A set row for the 2026-27 Challenge season's promos, printed N/C3. Lorcast
-- has not indexed the set, so this is our own id, like set_curators_cc1 (107).
-- code is NULL for the reason 166 gives: a claimed code would make
-- load_lorcast skip the real set, and every card in it, the day Lorcast
-- publishes it. The two cards we know (Mother Knows Best 1/C3 and 13/C3) are
-- REPRINT_PROMOS rows in scripts/patch_pid_overrides.py, which inserts them.
insert into public.sets (id, code, name, released_at, card_count, tcgplayer_group_id)
values ('set_challenge_c3', null, 'Lorcana Challenge Promo (C3)', '2026-08-15', null, null)
on conflict (id) do update
  set name = excluded.name, released_at = excluded.released_at;
notify pgrst, 'reload schema';
