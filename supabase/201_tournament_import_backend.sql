-- 201: upload a tournament straight from the database, no Bulk Upload modal.
--
-- The inkDecks import (.claude/skills/inkdecks-import) used to end with Claude
-- typing every decklist into the modal by keyboard, which closed under it twice
-- on 2026-11-01. Now Claude calls, over the Supabase connection:
--
--   select public.admin_import_tournament($j${
--     "name": "...", "event_date": "2026-10-31", "format": "core", "num_players": 64,
--     "rows": [{"place": "1st", "player_name": "...", "decklist": "4 Card - Version\n..."}]
--   }$j$::jsonb);                -- dry run: the report only, nothing written
--   select public.admin_import_tournament($j${...}$j$::jsonb, true);  -- upload
--
-- The upload itself is still bulk_upload_tournament, run as the tournament
-- admin, so tournaments / decks / deck_cards / tournament_decks are written by
-- the same code as the modal's. What this file adds is the card matcher, which
-- in the app is parseDeckText in Index.html. It is a SECOND COPY of that rule:
--   name key   lowercase, & -> and, accents folded, everything but a-z0-9 dropped
--   candidates every card except Format Coconut leaders and connecting-foil
--              companions ("184f"), which the app's catalog leaves out
--   best       +100 a mainline set (150+ cards, so a new set needs no list edit)
--              -80  a chase: Enchanted / Iconic / Epic, or a mainline number past 204
--              -60  a crd_custom_* row
--              then the lowest card id, which is the app's tie-break (reprints)
-- Replayed 2026-11-04 over all 500 stored tournament decks: every card came back
-- to the id the modal had stored.
--
-- Not callable by site users: execute is revoked from anon and authenticated.

create or replace function public.import_card_key(p text)
returns text
language sql
immutable
set search_path = public
as $$
  select regexp_replace(
           replace(translate(lower(coalesce(p, '')),
                             'āáàâäãåēéèêëīíìîïōóòôöõūúùûüñç',
                             'aaaaaaaeeeeeiiiiiooooooouuuuunc'),
                   '&', 'and'),
           '[^a-z0-9]', '', 'g')
$$;

-- Decklist text -> {entries:[{card_id,quantity}], unmatched:[line], over_cap:[...],
-- total, lines, inks}. Lines are "4 Name - Version" ("4x" and "4 -" too); blank,
-- "#" and "//" lines are skipped. Quantities of one card are summed.
create or replace function public.import_resolve_decklist(p_text text)
returns jsonb
language sql
stable
set search_path = public
as $$
  with lines as (
    select ord, btrim(l) as line
      from regexp_split_to_table(coalesce(p_text, ''), '\r?\n') with ordinality as t(l, ord)
  ),
  parsed as (
    select ord, line, regexp_match(line, '^(\d{1,3})\s*[x×]?\s*(?:-\s*)?(.+?)\s*$', 'i') as m
      from lines
     where line <> '' and line not like '#%' and line not like '//%'
  ),
  want as (
    select ord, line, m[1]::int as qty, public.import_card_key(m[2]) as k
      from parsed where m is not null and m[1]::int > 0
  ),
  mainline as (
    select set_id from public.cards group by set_id having count(*) >= 150
  ),
  cand as (
    select c.id, c.ink, c.inks,
           public.import_card_key(c.name || coalesce(' - ' || nullif(c.version, ''), '')) as k,
           (case when c.set_id in (select set_id from mainline) then 100 else 0 end)
           - (case when c.rarity in ('Enchanted', 'Iconic', 'Epic')
                     or (c.set_id in (select set_id from mainline)
                         and case when c.collector_number ~ '^\d{1,6}$'
                                  then c.collector_number::int end > 204)
                   then 80 else 0 end)
           - (case when c.id like 'crd\_custom%' then 60 else 0 end) as score
      from public.cards c
      join public.sets s on s.id = c.set_id
     where s.name <> 'Format Coconut'
       and coalesce(c.collector_number, '') !~ '^\d+f$'
  ),
  best as (
    select distinct on (k) k, id, ink, inks from cand where k <> '' order by k, score desc, id
  ),
  hit as (
    select w.ord, w.line, w.qty, b.id, b.ink, b.inks
      from want w left join best b on b.k = w.k and w.k <> ''
  ),
  per_card as (
    select id, sum(qty)::int as qty, min(ord) as first_ord from hit where id is not null group by id
  )
  select jsonb_build_object(
    'entries',   coalesce((select jsonb_agg(jsonb_build_object('card_id', id, 'quantity', qty) order by first_ord) from per_card), '[]'::jsonb),
    'unmatched', coalesce((select jsonb_agg(line order by ord) from hit where id is null), '[]'::jsonb)
                 || coalesce((select jsonb_agg(line order by ord) from parsed where m is null or m[1]::int = 0), '[]'::jsonb),
    'over_cap',  coalesce((select jsonb_agg(h.line || ' (' || p.qty || ' in all)')
                             from per_card p join hit h on h.id = p.id and h.ord = p.first_ord
                            where p.qty > 4), '[]'::jsonb),
    'total',     coalesce((select sum(qty) from hit where id is not null), 0),
    'lines',     (select count(*) from parsed),
    'inks',      coalesce((select jsonb_agg(distinct i order by i)
                             from hit cross join lateral unnest(coalesce(nullif(inks, '{}'::text[]), array[ink])) as u(i)
                            where id is not null and i is not null), '[]'::jsonb)
  )
$$;

-- One event per call. Dry run (the default) returns the report and writes
-- nothing. p_commit = true uploads, and refuses (raises, so nothing is written)
-- on any problem: an unmatched card line, an unreadable place, an empty list,
-- a format other than core/infinity, or a tournament already stored under the
-- same name and date. over_cap is a warning only: bulk_upload_tournament clamps
-- every quantity to 4.
create or replace function public.admin_import_tournament(p_event jsonb, p_commit boolean default false)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_name     text := btrim(coalesce(p_event->>'name', ''));
  v_date     date := nullif(btrim(p_event->>'event_date'), '')::date;
  v_format   text := lower(nullif(btrim(p_event->>'format'), ''));
  v_players  int  := nullif(btrim(p_event->>'num_players'), '')::int;
  v_admin    uuid;
  v_dup      uuid;
  v_problems text[] := '{}';
  v_rows     jsonb := '[]';
  v_report   jsonb := '[]';
  v_tid      uuid;
  r          jsonb;
  res        jsonb;
  v_place    text;
  v_key      text;
  v_rank     int;
  i          int := 0;
begin
  if v_name = '' then raise exception 'name is required'; end if;
  if v_date is null then v_problems := v_problems || 'event_date is missing'; end if;
  if v_format is null or v_format not in ('core', 'infinity') then
    v_problems := v_problems || ('format must be core or infinity, got ' || coalesce(v_format, 'nothing'));
  end if;

  select id into v_dup from public.tournaments
   where lower(btrim(name)) = lower(v_name) and event_date is not distinct from v_date limit 1;
  if v_dup is not null then
    v_problems := v_problems || ('already uploaded as tournament ' || v_dup);
  end if;

  for r in select * from jsonb_array_elements(coalesce(p_event->'rows', '[]'::jsonb)) loop
    i := i + 1;
    res := public.import_resolve_decklist(r->>'decklist');
    v_place := nullif(btrim(r->>'place'), '');
    -- parsePlaceRank in Index.html: 1st/2nd/3rd, "Top 8", "T16", "5th".
    v_key := regexp_replace(lower(coalesce(v_place, '')), '[^a-z0-9]', '', 'g');
    v_rank := case v_key when '1st' then 1 when '1' then 1 when '2nd' then 2 when '2' then 2
                         when '3rd' then 3 when '3' then 3
                         else (regexp_match(v_key, '^(?:top|t)?(\d{1,4})(?:th|st|nd|rd)?$'))[1]::int end;
    if v_rank is null then
      v_problems := v_problems || format('row %s: unreadable place %L', i, v_place);
    end if;
    if jsonb_array_length(res->'unmatched') > 0 then
      v_problems := v_problems || format('row %s: unmatched %s', i, res->'unmatched');
    end if;
    if (res->>'total')::int = 0 then
      v_problems := v_problems || format('row %s: empty decklist', i);
    end if;
    v_rows := v_rows || jsonb_build_object(
      'place', v_place, 'place_rank', v_rank,
      'player_name', nullif(btrim(r->>'player_name'), ''),
      'deck_name', nullif(btrim(r->>'deck_name'), ''),
      'entries', res->'entries', 'inks', res->'inks');
    v_report := v_report || jsonb_build_object(
      'row', i, 'place', v_place, 'player', r->>'player_name',
      'total', res->'total', 'lines', res->'lines', 'cards', jsonb_array_length(res->'entries'),
      'inks', res->'inks', 'unmatched', res->'unmatched', 'over_cap', res->'over_cap');
  end loop;
  if i = 0 then v_problems := v_problems || 'no rows'::text; end if;

  if p_commit then
    if cardinality(v_problems) > 0 then
      raise exception 'not uploaded: %', array_to_string(v_problems, '; ');
    end if;
    select user_id into strict v_admin from public.tournament_admins;
    -- bulk_upload_tournament checks auth.uid(), which reads this setting. Local to
    -- the transaction, and cleared again straight after.
    perform set_config('request.jwt.claim.sub', v_admin::text, true);
    v_tid := public.bulk_upload_tournament(v_name, v_date, v_format, v_players, v_rows);
    perform set_config('request.jwt.claim.sub', '', true);
  end if;

  return jsonb_build_object(
    'committed', v_tid is not null, 'tournament_id', v_tid,
    'name', v_name, 'event_date', v_date, 'format', v_format, 'num_players', v_players,
    'problems', to_jsonb(v_problems), 'rows', v_report);
end;
$$;

revoke all on function public.import_card_key(text) from public, anon, authenticated;
revoke all on function public.import_resolve_decklist(text) from public, anon, authenticated;
revoke all on function public.admin_import_tournament(jsonb, boolean) from public, anon, authenticated;
