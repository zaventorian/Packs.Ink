-- scout_any_event_checks.sql - assertions for the scouting chain. Run AFTER the
-- fixture and the four migrations (see the fixture's header). Every check raises
-- on failure, so a silent run is a pass and the last line says so.

-- Who we are: an ordinary scout, on the list by email, not an admin.
insert into auth.users(id, email) values ('11111111-1111-1111-1111-111111111111','scout@example.com');
insert into auth._who values ('11111111-1111-1111-1111-111111111111');
insert into public.profiles values ('11111111-1111-1111-1111-111111111111','Zaven');
insert into public.scout_members(email) values ('Scout@Example.com');

-- One TRACKED store running an SC; one UNTRACKED store out of the bubble.
insert into public.elo_tracked_stores values (100,'Gemini Games');
insert into public.set_championships values
  (900,'AotV Set Championship',100,'Gemini Games',now()+interval '2 days','America/Chicago','Elgin','IL',32,'Attack of the Vine!',24);
insert into public.lorcana_events values
  (901,'Thursday Locals',555,'Far Away Cards',now()+interval '3 days','America/Denver','Denver','CO',16,'other',null,8),
  (902,'Old League Night',555,'Far Away Cards',now()-interval '40 days','America/Denver','Denver','CO',16,'other',null,4);
insert into public.elo_players values (7,'rph','Known Player',null);
insert into public.elo_event_roster values (901,16,8,now());
insert into public.elo_event_roster_members values
  (901,'Known Player','known',null),(901,'Nobody Special','nobody',null);

do $$
declare
  d jsonb;
  n int;
begin
  -- 1. An out-of-bubble event is refused until somebody adds it. This is the
  --    half Zaven's "don't auto add any more" constraint protects.
  d := public.get_scout_event(901);
  if (d->>'scoutable')::boolean or d->>'reason' <> 'untracked_store' then
    raise exception 'check 1: an untracked event should refuse with untracked_store, got %', d;
  end if;
  begin
    perform public.save_scout_note(901,'Known Player',null,'Amber/Steel',null);
    raise exception 'check 1b: save_scout_note wrote to an event we do not scout';
  exception when others then
    if sqlerrm not like '%is not one we scout%' then raise; end if;
  end;

  -- 2. Adding it opens everything, and says who put it there.
  perform public.scout_event_add(901);
  d := public.get_scout_event(901);
  if not (d->>'scoutable')::boolean then raise exception 'check 2: still refused after add: %', d; end if;
  if not (d->'event'->>'added')::boolean then raise exception 'check 2: event should be marked added'; end if;
  if (d->'event'->>'store_tracked')::boolean then raise exception 'check 2: store_tracked must stay false'; end if;
  if d->'event'->>'added_by' <> 'Zaven' then raise exception 'check 2: added_by lost'; end if;
  if d->'event'->>'registered_count' <> '8' then raise exception 'check 2: registered_count should fall back to the feed'; end if;

  -- 3. A player the Elo board has never heard of is loggable and renders unrated.
  perform public.save_scout_note(901,'Nobody Special',null,'Cosmic Destroyers','tapped out turn 4');
  d := public.get_scout_event(901);
  select count(*) into n from jsonb_array_elements(d->'players') p
   where p->>'best_identifier' = 'Nobody Special' and (p->>'matched')::boolean is false
     and p->>'deck' = 'Cosmic Destroyers';
  if n <> 1 then raise exception 'check 3: the non-Elo player did not come back logged and unrated'; end if;

  -- 4. The slate carries both, and only the hand-added one is marked.
  select count(*) into n from jsonb_array_elements(public.get_roster_scout()) e
   where (e->>'event_id') in ('900','901');
  if n <> 2 then raise exception 'check 4: slate should hold both events, has %', n; end if;
  select count(*) into n from jsonb_array_elements(public.get_roster_scout()) e
   where e->>'event_id' = '900' and (e->>'added')::boolean;
  if n <> 0 then raise exception 'check 4: the automatic SC must not be marked added'; end if;
  select count(*) into n from jsonb_array_elements(public.get_roster_scout()) e
   where e->>'event_id' = '901' and (e->>'added')::boolean and e->>'added_by' = 'Zaven';
  if n <> 1 then raise exception 'check 4: the added event should be marked with who added it'; end if;

  -- 5. The 24-hour window applies to added events too - adding something from
  --    last month must not resurrect it onto the tab.
  perform public.scout_event_add(902);
  select count(*) into n from jsonb_array_elements(public.get_roster_scout()) e where e->>'event_id' = '902';
  if n <> 0 then raise exception 'check 5: a 40-day-old added event is on the slate'; end if;
  perform public.scout_event_remove(902);

  -- 6/7. A tracked SC is untouched, and adding one cannot list it twice.
  d := public.get_scout_event(900);
  if (d->'event'->>'added')::boolean or not (d->'event'->>'store_tracked')::boolean then
    raise exception 'check 6: the tracked SC reads wrong: %', d->'event';
  end if;
  perform public.scout_event_add(900);
  select count(*) into n from jsonb_array_elements(public.get_roster_scout()) e where e->>'event_id' = '900';
  if n <> 1 then raise exception 'check 7: an added tracked SC listed % times', n; end if;
  perform public.scout_event_remove(900);

  -- 8. Durability: the upcoming feed prunes what has happened, so the ledger's
  --    own stored label has to keep the sheet reachable.
  delete from public.lorcana_events where event_id = 901;
  d := public.get_scout_event(901);
  if not (d->>'scoutable')::boolean or d->'event'->>'name' <> 'Thursday Locals' then
    raise exception 'check 8: an added event stopped resolving once the feed dropped it: %', d;
  end if;

  -- 9. Removal is REVERSIBLE. Without scout_notes as a resolution source this
  --    orphans the sheet permanently - the graded per-card Hide failure.
  d := public.scout_event_remove(901);
  if (d->>'notes_kept')::int <> 1 then raise exception 'check 9: remove should report the notes it leaves behind'; end if;
  if (public.get_scout_event(901)->>'scoutable')::boolean then raise exception 'check 9: removal did not take effect'; end if;
  if public.get_scout_event(901)->>'reason' <> 'untracked_store' then
    raise exception 'check 9: a removed event with notes must still RESOLVE, so the UI can offer Add again (got %)',
      public.get_scout_event(901)->>'reason';
  end if;
  perform public.scout_event_add(901);
  d := public.get_scout_event(901);
  if jsonb_array_length(d->'players') <> 2 or d->'field'->>'n_logged' <> '1' then
    raise exception 'check 9: re-adding did not restore the sheet: %', d->'field';
  end if;

  -- 10. The player's own log is untouched by any of it.
  if jsonb_array_length(public.get_scout_player('name:nobody special')) <> 1 then
    raise exception 'check 10: the player history lost its entry';
  end if;
end $$;

-- 11. can_scout() is the only door: an off-list session is refused everywhere.
do $$
begin
  delete from auth._who;
  insert into auth._who values ('22222222-2222-2222-2222-222222222222');
  begin perform public.get_scout_event(901); raise exception 'check 11: get_scout_event let a stranger in';
  exception when others then if sqlerrm not like '%not authorized%' then raise; end if; end;
  begin perform public.scout_event_add(901); raise exception 'check 11: scout_event_add let a stranger in';
  exception when others then if sqlerrm not like '%not authorized%' then raise; end if; end;
  begin perform public.scout_event_remove(901); raise exception 'check 11: scout_event_remove let a stranger in';
  exception when others then if sqlerrm not like '%not authorized%' then raise; end if; end;
  begin perform public.get_roster_scout(); raise exception 'check 11: get_roster_scout let a stranger in';
  exception when others then if sqlerrm not like '%not authorized%' then raise; end if; end;
  delete from auth._who;
  insert into auth._who values ('11111111-1111-1111-1111-111111111111');
end $$;

-- 12. The ledger itself is definer-only: no direct PostgREST read.
do $$
declare n int;
begin
  select count(*) into n from information_schema.role_table_grants
   where table_schema='public' and table_name='scout_events' and grantee in ('anon','authenticated');
  if n <> 0 then raise exception 'check 12: scout_events is directly readable by % grants', n; end if;
  if not (select relrowsecurity from pg_class where oid = 'public.scout_events'::regclass) then
    raise exception 'check 12: scout_events has RLS off';
  end if;
end $$;

select 'ALL SCOUT CHECKS PASSED' as result;
