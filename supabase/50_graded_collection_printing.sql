-- 50_graded_collection_printing.sql — add `printing` to graded_collection_items
-- so users can track foil vs non-foil graded copies separately.
--
-- Without this, a user who owns both a Holofoil PSA 10 and a Normal PSA 10
-- of the same C1 card collapses them into one slot in the database. Adding
-- printing as a PK component lets each printing live as its own row, which
-- the UI then surfaces as separate tiles in the SECTION_SPLIT_SETS sections.
--
-- Companion to migration 49 (which added printing to graded_prices_daily).
-- For most cards (single printing), printing='Normal' and the schema change
-- is invisible. Migration backfills every existing row to 'Normal'.
--
-- Recreates get_shared_collection_graded RPC to project the new column.

alter table public.graded_collection_items drop constraint if exists graded_collection_items_pkey;

alter table public.graded_collection_items
  add column if not exists printing text not null default 'Normal';

-- Drop the default so future inserts must specify explicitly.
alter table public.graded_collection_items
  alter column printing drop default;

alter table public.graded_collection_items
  add constraint graded_collection_items_pkey
  primary key (user_id, card_id, printing, grader, grade);

-- Recreate the shared-collection RPC with printing in the returns table.
drop function if exists public.get_shared_collection_graded(uuid, text);

create function public.get_shared_collection_graded(p_user_id uuid, p_token text)
returns table(
  user_id       uuid,
  card_id       text,
  printing      text,
  grader        text,
  grade         text,
  quantity      integer,
  amount_paid   numeric,
  acquired_date date,
  updated_at    timestamptz
)
language sql
security definer
set search_path = public
as $$
  select gci.user_id, gci.card_id, gci.printing, gci.grader, gci.grade, gci.quantity,
         gci.amount_paid, gci.acquired_date, gci.updated_at
    from public.graded_collection_items gci
    join public.profiles p on p.user_id = gci.user_id
   where gci.user_id = p_user_id
     and (
       p.collection_graded_visibility = 'public'
       OR (p.collection_graded_visibility = 'unlisted' AND p.collection_share_token = p_token)
     );
$$;

revoke all     on function public.get_shared_collection_graded(uuid, text) from public;
grant  execute on function public.get_shared_collection_graded(uuid, text) to anon, authenticated;

notify pgrst, 'reload schema';
