-- 165_graded_pop.sql -- PSA population counts for the English Lorcana sets.
--
-- Answers the one question graded_sales cannot: how many of this card exist at
-- this grade. Sales say what people paid; population says what the supply is,
-- and a PSA 10 that is 1-of-3 is a different asset from one that is 1-of-900 at
-- the same price. Loaded by scripts/psa_pop_load.py from what
-- scripts/psa_pop_pull.mjs reads out of a signed-in PSA session.
--
-- DESIGN NOTES, because two of these are easy to get wrong later:
--
--  * Rows are stored EXACTLY AS PSA PUBLISHES THEM -- their spec_id, their set
--    label, their subject name, their variety -- and are NOT resolved to our
--    card_id here. Resolution happens client-side against the catalog already in
--    memory, the same joinback the Screener uses for price_movers. That keeps a
--    stale card_id column from ever disagreeing with the catalog, and means
--    cataloguing a card we currently miss (the Illumineer's Quest decks) improves
--    pop coverage with no re-load.
--
--  * spec_id is PSA's own per-printing id and is the PRIMARY KEY, so a re-pull
--    upserts in place. It is stable across pulls; the heading a set lives under
--    is not always -- PSA splits promo sets by year, so P1-Promo is both 245594
--    (2023) and 263753 (2024). Never key a set on one heading.
--
--  * The full grade ladder is JSONB rather than ~30 columns: PSA carries
--    straight grades, half grades (Grade9_5) and qualifier counts (Grade9Q), and
--    a new grade should not need a migration. The three numbers a LIST surface
--    sorts and filters on -- total, pop_10, pop_9 -- are real columns so they can
--    be indexed; everything else is read per card.
--
-- History is deliberately NOT kept: one row per spec_id, latest wins. Population
-- only ever grows, so a time series would give submission velocity, which is
-- worth having later -- pulled_at is here so that day is a new table, not a
-- reinterpretation of this one.

create table if not exists public.graded_pop (
  spec_id      bigint primary key,
  heading_id   integer     not null,
  set_label    text        not null,
  year_issued  integer,
  subject_name text        not null,
  card_number  text,
  variety      text        not null default '',
  -- hot scalars, for sorting a list without opening the jsonb
  total        integer     not null default 0,
  pop_10       integer     not null default 0,
  pop_9        integer     not null default 0,
  -- {"auth":1,"1":0,"1.5":0,...,"9":23597,"9Q":4,"9.5":33,"10":42865,
  --  "gradeTotal":...,"halfTotal":...,"qualifiedTotal":...}
  grades       jsonb       not null default '{}'::jsonb,
  pulled_at    timestamptz not null default now()
);

create index if not exists graded_pop_heading_idx on public.graded_pop (heading_id);
-- The client joins on (subject name, card number); this is what makes that
-- lookup cheap when a single card is asked for rather than the whole table.
create index if not exists graded_pop_subject_idx
  on public.graded_pop (lower(subject_name), card_number);

alter table public.graded_pop enable row level security;

-- Public data, read by anyone, same posture as prices and graded_sales. Writes
-- are the loader's alone -- there is no INSERT/UPDATE policy, so PostgREST
-- cannot reach it with the anon or authenticated key at all.
drop policy if exists graded_pop_read on public.graded_pop;
create policy graded_pop_read on public.graded_pop
  for select to anon, authenticated using (true);

-- A new relation grants nothing implicitly, and service_role does NOT inherit.
grant select on public.graded_pop to anon, authenticated, service_role;
grant insert, update, delete on public.graded_pop to service_role;

notify pgrst, 'reload schema';
