-- 51_graded_custom_value.sql — per-user custom value override on graded slots.
--
-- Some graded slots have no TCGPriceLookup data (low-liquidity cards,
-- cards with zero recent eBay sales) and some have inaccurate data the
-- user would rather correct manually. This adds a nullable per-row
-- `custom_value` field that, when set, supersedes the API price in every
-- value-computation path.
--
-- - NULL  → use TCGPriceLookup price (current behavior)
-- - value → override; use this number instead, both in totals and on tiles
--
-- Recreates `get_shared_collection_graded` to project the new column so
-- shared-collection viewers see the same overridden value the owner sees.

alter table public.graded_collection_items
  add column if not exists custom_value numeric(12,2);

-- Drop & recreate the shared-collection RPC — RETURNS TABLE signatures
-- aren't alterable in place.
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
  custom_value  numeric,
  updated_at    timestamptz
)
language sql
security definer
set search_path = public
as $$
  select gci.user_id, gci.card_id, gci.printing, gci.grader, gci.grade, gci.quantity,
         gci.amount_paid, gci.acquired_date, gci.custom_value, gci.updated_at
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
