-- 202: tournament import for whole fields (DLC Bangkok, 706 lists), from a local script.
--
-- 201 resolved each decklist in its own pass over the catalog, about 130 ms a
-- deck: fine for a top 8, about 90 s for a 700-deck field, past what one call
-- through the API gateway allows. import_resolve_decklists does every list of
-- an event in ONE pass, same rule as 201 (unchanged below, only batched);
-- import_resolve_decklist stays as its one-list wrapper for the replay check.
--
-- A field that size is also too much text to pass through the Supabase MCP, so
-- admin_import_tournament becomes callable with the service key, from
-- scripts/upload_tournament.py (key in the gitignored scripts/.env). It is now
-- SECURITY DEFINER for that, so the service role needs no grants on the tables.
-- Still revoked from anon and authenticated.

create or replace function public.import_resolve_decklists(p_texts text[])
returns jsonb
language sql
stable
set search_path = public
as $$
  with decks as (
    select d, txt from unnest(p_texts) with ordinality as u(txt, d)
  ),
  lines as (
    select d, ord, btrim(l) as line
      from decks, regexp_split_to_table(coalesce(txt, ''), '\r?\n') with ordinality as t(l, ord)
  ),
  parsed as (
    select d, ord, line, regexp_match(line, '^(\d{1,3})\s*[x×]?\s*(?:-\s*)?(.+?)\s*$', 'i') as m
      from lines
     where line <> '' and line not like '#%' and line not like '//%'
  ),
  want as (
    select d, ord, line, m[1]::int as qty, public.import_card_key(m[2]) as k
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
    select w.d, w.ord, w.line, w.qty, b.id, b.ink, b.inks
      from want w left join best b on b.k = w.k and w.k <> ''
  ),
  per_card as (
    select d, id, sum(qty)::int as qty, min(ord) as first_ord from hit where id is not null group by d, id
  ),
  ent as (
    select d, jsonb_agg(jsonb_build_object('card_id', id, 'quantity', qty) order by first_ord) as entries,
           sum(qty) as total
      from per_card group by d
  ),
  um as (
    select d, jsonb_agg(line order by ord) as unmatched
      from (select d, ord, line from hit where id is null
            union all
            select d, ord, line from parsed where m is null or m[1]::int = 0) x
     group by d
  ),
  oc as (
    select p.d, jsonb_agg(h.line || ' (' || p.qty || ' in all)' order by p.first_ord) as over_cap
      from per_card p join hit h on h.d = p.d and h.id = p.id and h.ord = p.first_ord
     where p.qty > 4 group by p.d
  ),
  ln as (
    select d, count(*) as n from parsed group by d
  ),
  ik as (
    select d, jsonb_agg(distinct i order by i) as inks
      from hit cross join lateral unnest(coalesce(nullif(inks, '{}'::text[]), array[ink])) as u(i)
     where id is not null and i is not null group by d
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'entries',   coalesce(ent.entries, '[]'::jsonb),
           'unmatched', coalesce(um.unmatched, '[]'::jsonb),
           'over_cap',  coalesce(oc.over_cap, '[]'::jsonb),
           'total',     coalesce(ent.total, 0),
           'lines',     coalesce(ln.n, 0),
           'inks',      coalesce(ik.inks, '[]'::jsonb)) order by decks.d), '[]'::jsonb)
    from decks
    left join ent using (d) left join um using (d) left join oc using (d)
    left join ln using (d) left join ik using (d)
$$;

create or replace function public.import_resolve_decklist(p_text text)
returns jsonb
language sql
stable
set search_path = public
as $$
  select public.import_resolve_decklists(array[p_text]) -> 0
$$;

-- Body as in 201, except that every list is resolved in one call before the loop.
create or replace function public.admin_import_tournament(p_event jsonb, p_commit boolean default false)
returns jsonb
language plpgsql
security definer
set search_path = public
set statement_timeout = '5min'
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
  v_all      jsonb;
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

  v_all := public.import_resolve_decklists(array(
    select e->>'decklist' from jsonb_array_elements(coalesce(p_event->'rows', '[]'::jsonb)) with ordinality as t(e, ord)
     order by ord));

  for r in select e from jsonb_array_elements(coalesce(p_event->'rows', '[]'::jsonb)) with ordinality as t(e, ord) order by ord loop
    i := i + 1;
    res := v_all -> (i - 1);
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

revoke all on function public.import_resolve_decklists(text[]) from public, anon, authenticated;
revoke all on function public.import_resolve_decklist(text) from public, anon, authenticated;
revoke all on function public.admin_import_tournament(jsonb, boolean) from public, anon, authenticated;
grant execute on function public.admin_import_tournament(jsonb, boolean) to service_role;
