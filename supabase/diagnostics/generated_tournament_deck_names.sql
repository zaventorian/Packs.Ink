-- Dry run for migration 117. Read-only — counts and samples only.
-- Paste into the Supabase SQL editor and review before applying 117.
--
-- Expected shape of the answer: most rows land in `ink_combo`, not
-- `players_deck`, because the client's fallback chain tried inks first and
-- every row whose decklist parsed has inks.

with named as (
  select d.id, d.name, d.inks, td.player_name, t.name as tournament_name
    from public.decks d
    join public.tournament_decks td on td.deck_id = d.id
    join public.tournaments t on t.id = td.tournament_id
   where d.name is not null
     and btrim(d.name) <> ''
), tokens as (
  select n.*,
         (select array_agg(lower(v) order by lower(v))
            from unnest(coalesce(n.inks, '{}'::text[])) v
           where btrim(v) <> '')                                      as ink_sorted,
         (select array_agg(w order by w)
            from unnest(regexp_split_to_array(lower(btrim(n.name)), '[\s/,\-]+')) w
           where w <> '')                                             as name_sorted
    from named n
), classified as (
  select t.*,
         case
           when t.player_name is not null
            and lower(btrim(t.name)) = lower(btrim(t.player_name)) || '''s deck'
             then 'players_deck'
           when t.ink_sorted is not null
            and t.name_sorted is not null
            and t.name_sorted = t.ink_sorted
             then 'ink_combo'
           when lower(btrim(t.name)) = 'untitled deck'
             then 'untitled'
           else 'real_name'
         end as pattern
    from tokens t
)
select pattern,
       count(*)                                        as rows_affected,
       count(distinct tournament_name)                 as tournaments_touched,
       (array_agg(name order by name))[1:5]            as sample_names
  from classified
 group by pattern
 order by rows_affected desc;

-- Sanity check — eyeball that nothing in `real_name` looks auto-generated,
-- and nothing in the cleared buckets looks hand-typed.
--
-- with ... (same CTE) ...
-- select pattern, tournament_name, player_name, name, inks
--   from classified
--  where pattern <> 'real_name'
--  order by pattern, tournament_name
--  limit 100;
