-- Index usage audit for Packs.Ink.
--
-- NOT a migration. Paste into the Supabase SQL editor and run.
-- Shows every index on the user-data tables, how many times Postgres has
-- actually used it (idx_scan), its size, and a verdict flag.
--
-- idx_scan = 0 on a long-lived index = strong "unused" signal. Caveats:
--   - Primary key / unique indexes that aren't directly queried still
--     enforce constraints. Don't drop those even with idx_scan=0.
--   - Stats reset on cluster restart, manual `pg_stat_reset()`, or
--     pg_upgrade. If `stats_age_days` is small, idx_scan=0 may mean
--     "not used since reset", not "never used."
--   - Indexes added in the last few days haven't had time to be hit.
--
-- Verdict legend:
--   PK/UNIQUE             — constraint-bearing, do not drop
--   REDUNDANT-WITH-PK     — leading columns already covered by the PK
--   UNUSED                — idx_scan = 0, age > 7d, not constraint-bearing
--   LOW-USE               — idx_scan < 100 over > 7d
--   ACTIVE                — idx_scan >= 100

with stats_age as (
  select extract(epoch from (now() - stats_reset)) / 86400 as days
  from pg_stat_database
  where datname = current_database()
),
target_tables (relname) as (values
  ('cards'), ('sets'), ('prices_daily'),
  ('collection_items'), ('decks'), ('deck_cards'),
  ('card_prices_latest'), ('rarity_avg_daily'), ('price_movers')
),
idx as (
  select
    s.schemaname,
    s.relname                              as table_name,
    s.indexrelname                         as index_name,
    s.idx_scan,
    pg_size_pretty(pg_relation_size(s.indexrelid)) as index_size,
    i.indexdef,
    ix.indisprimary                        as is_pk,
    ix.indisunique                         as is_unique,
    -- indkey is an int2vector; "1 2 3" -> {1,2,3}
    string_to_array(ix.indkey::text, ' ')::int[] as colnums
  from pg_stat_user_indexes s
  join pg_index ix on ix.indexrelid = s.indexrelid
  join pg_indexes i on i.schemaname = s.schemaname
                   and i.tablename  = s.relname
                   and i.indexname  = s.indexrelname
  where s.schemaname = 'public'
    and s.relname in (select relname from target_tables)
),
pk_cols as (
  select
    s.relname as table_name,
    string_to_array(ix.indkey::text, ' ')::int[] as pk_colnums
  from pg_stat_user_indexes s
  join pg_index ix on ix.indexrelid = s.indexrelid
  where ix.indisprimary
    and s.schemaname = 'public'
    and s.relname in (select relname from target_tables)
)
select
  i.table_name,
  i.index_name,
  i.idx_scan,
  i.index_size,
  case
    when i.is_pk                                  then 'PK/UNIQUE'
    when i.is_unique                              then 'PK/UNIQUE'
    when exists (
      select 1 from pk_cols p
      where p.table_name = i.table_name
        and array_length(i.colnums, 1) <= array_length(p.pk_colnums, 1)
        and p.pk_colnums[1:array_length(i.colnums, 1)] = i.colnums
    )                                              then 'REDUNDANT-WITH-PK'
    when i.idx_scan = 0  and (select days from stats_age) > 7  then 'UNUSED'
    when i.idx_scan < 100 and (select days from stats_age) > 7 then 'LOW-USE'
    else 'ACTIVE'
  end as verdict,
  i.indexdef,
  round((select days from stats_age)::numeric, 1) as stats_age_days
from idx i
order by
  case
    when i.is_pk or i.is_unique then 3
    when i.idx_scan = 0 then 0
    else 1
  end,
  i.table_name,
  i.idx_scan;
