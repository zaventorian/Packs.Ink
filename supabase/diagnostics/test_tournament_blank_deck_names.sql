-- Behaviour test for migration 116. Paste into the Supabase SQL editor.
--
-- Covers the three cases that were broken:
--   1. insert with a blank deck name        → stored NULL
--   2. update an existing name to blank     → cleared to NULL
--   3. update from blank back to a real name → stored
--
-- Self-cleaning: the block deliberately raises at the end, so every row it
-- created is rolled back. Seeing the "TEST COMPLETE" error IS the pass signal.
-- Any other error is a real failure.
--
-- Needs a row in public.tournament_admins (it borrows that uid to satisfy the
-- admin gate, since auth.uid() is NULL in the SQL editor).

do $$
declare
  v_admin uuid;
  v_tid   uuid;
  v_rid   uuid;
  v_did   uuid;
  v_name  text;
begin
  select user_id into v_admin from public.tournament_admins limit 1;
  if v_admin is null then
    raise exception 'no row in tournament_admins — cannot exercise the admin-gated RPCs';
  end if;
  perform set_config('request.jwt.claims',
    json_build_object('sub', v_admin, 'role', 'authenticated')::text, true);

  ---------------------------------------------------------------- 1. insert
  v_tid := public.bulk_upload_tournament(
    'ZZ test — blank deck names', current_date, 'core', 8,
    jsonb_build_array(
      jsonb_build_object('place','1st','place_rank',1,'player_name','Nerf',
                         'deck_name','', 'entries','[]'::jsonb,
                         'inks', jsonb_build_array('Amber','Emerald')),
      jsonb_build_object('place','2nd','place_rank',2,'player_name','Other',
                         'deck_name','   ', 'entries','[]'::jsonb,
                         'inks', jsonb_build_array('Ruby')),
      jsonb_build_object('place','Top 4','place_rank',4,'player_name','Third',
                         'deck_name','Ruby Sapphire Control', 'entries','[]'::jsonb,
                         'inks', jsonb_build_array('Ruby','Sapphire'))
    )
  );

  select d.name into v_name
    from public.tournament_decks td join public.decks d on d.id = td.deck_id
   where td.tournament_id = v_tid and td.place_rank = 1;
  assert v_name is null,
    '1a: blank name should insert as NULL, got ' || coalesce(v_name, '<null>');
  raise notice 'ok   1a  insert with blank name -> NULL';

  select d.name into v_name
    from public.tournament_decks td join public.decks d on d.id = td.deck_id
   where td.tournament_id = v_tid and td.place_rank = 2;
  assert v_name is null,
    '1b: whitespace-only name should insert as NULL, got ' || coalesce(v_name, '<null>');
  raise notice 'ok   1b  insert with whitespace-only name -> NULL';

  select d.name into v_name
    from public.tournament_decks td join public.decks d on d.id = td.deck_id
   where td.tournament_id = v_tid and td.place_rank = 4;
  assert v_name = 'Ruby Sapphire Control',
    '1c: a real name must be preserved, got ' || coalesce(v_name, '<null>');
  raise notice 'ok   1c  insert with a real name -> preserved';

  select td.id, d.id into v_rid, v_did
    from public.tournament_decks td join public.decks d on d.id = td.deck_id
   where td.tournament_id = v_tid and td.place_rank = 1;

  ---------------------------------------------------- 2. update -> blank
  perform public.admin_update_tournament_deck(v_rid, '1st', 1, 'Nerf', 'Amber Steel Aggro');
  select name into v_name from public.decks where id = v_did;
  assert v_name = 'Amber Steel Aggro',
    '2a: setup rename failed, got ' || coalesce(v_name, '<null>');
  raise notice 'ok   2a  update to a real name -> stored';

  perform public.admin_update_tournament_deck(v_rid, '1st', 1, 'Nerf', '');
  select name into v_name from public.decks where id = v_did;
  assert v_name is null,
    '2b: THE BUG — blank should clear the name, got ' || coalesce(v_name, '<null>');
  raise notice 'ok   2b  update to blank -> cleared to NULL';

  perform public.admin_update_tournament_deck(v_rid, '1st', 1, 'Nerf', 'Temp');
  perform public.admin_update_tournament_deck(v_rid, '1st', 1, 'Nerf', null);
  select name into v_name from public.decks where id = v_did;
  assert v_name is null,
    '2c: explicit NULL should clear the name, got ' || coalesce(v_name, '<null>');
  raise notice 'ok   2c  update to NULL -> cleared to NULL';

  ---------------------------------------------- 3. blank -> real, round trip
  perform public.admin_update_tournament_deck(v_rid, '1st', 1, 'Nerf', 'Sapphire Steel Midrange');
  select name into v_name from public.decks where id = v_did;
  assert v_name = 'Sapphire Steel Midrange',
    '3a: blank -> real name should store, got ' || coalesce(v_name, '<null>');
  raise notice 'ok   3a  update from blank back to a real name -> stored';

  perform public.admin_update_tournament_deck(v_rid, '1st', 1, 'Nerf', '  Trimmed Name  ');
  select name into v_name from public.decks where id = v_did;
  assert v_name = 'Trimmed Name',
    '3b: name should be trimmed, got ' || coalesce(v_name, '<null>');
  raise notice 'ok   3b  surrounding whitespace trimmed';

  --------------------------------------------- 4. single-deck add path
  v_rid := public.admin_add_tournament_deck(
    v_tid, 'Top 8', 8, 'Fourth', '', array['Amber']::text[], '[]'::jsonb);
  select d.name into v_name
    from public.tournament_decks td join public.decks d on d.id = td.deck_id
   where td.id = v_rid;
  assert v_name is null,
    '4a: admin_add with blank name should store NULL, got ' || coalesce(v_name, '<null>');
  raise notice 'ok   4a  admin_add_tournament_deck blank name -> NULL';

  raise exception 'TEST COMPLETE — all assertions passed, transaction rolled back';
end $$;
