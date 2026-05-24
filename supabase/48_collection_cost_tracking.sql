-- 48_collection_cost_tracking.sql — optional purchase-tracking metadata.
--
-- Adds two nullable columns to both sealed and graded collection-item tables:
--   amount_paid   numeric(12,2)  — what the user paid (USD, user-tracking only)
--   acquired_date date            — when the user acquired it. Used by the
--                                   collection value chart to gate this item's
--                                   contribution; values before acquired_date
--                                   roll up as $0 for that slot.
--
-- Both columns are nullable; a null acquired_date preserves the existing
-- behavior (item contributes from the earliest available price snapshot,
-- subject to the prerelease guard).
--
-- The two shared-collection RPCs (get_shared_collection_sealed / _graded) are
-- DROPPED + RECREATED because CREATE OR REPLACE can't change the RETURNS TABLE
-- signature (see CLAUDE.md "PostgREST gotchas").
--
-- Idempotent on re-run.

-- ── Sealed ──────────────────────────────────────────────────────────────
alter table public.sealed_collection_items
  add column if not exists amount_paid   numeric(12,2),
  add column if not exists acquired_date date;

-- ── Graded ──────────────────────────────────────────────────────────────
alter table public.graded_collection_items
  add column if not exists amount_paid   numeric(12,2),
  add column if not exists acquired_date date;

-- ── Recreate get_shared_collection_sealed with new columns ──────────────
drop function if exists public.get_shared_collection_sealed(uuid, text);

create function public.get_shared_collection_sealed(p_user_id uuid, p_token text)
returns table(
  user_id              uuid,
  tcgplayer_product_id bigint,
  condition            text,
  quantity             int,
  notes                text,
  amount_paid          numeric,
  acquired_date        date,
  updated_at           timestamptz
)
language sql
security definer
set search_path = public
as $$
  select sci.user_id, sci.tcgplayer_product_id, sci.condition, sci.quantity, sci.notes,
         sci.amount_paid, sci.acquired_date, sci.updated_at
    from public.sealed_collection_items sci
    join public.profiles p on p.user_id = sci.user_id
   where sci.user_id = p_user_id
     and (
       p.collection_sealed_visibility = 'public'
       OR (p.collection_sealed_visibility = 'unlisted' AND p.collection_share_token = p_token)
     );
$$;

revoke all     on function public.get_shared_collection_sealed(uuid, text) from public;
grant  execute on function public.get_shared_collection_sealed(uuid, text) to anon, authenticated;

-- ── Recreate get_shared_collection_graded with new columns ──────────────
drop function if exists public.get_shared_collection_graded(uuid, text);

create function public.get_shared_collection_graded(p_user_id uuid, p_token text)
returns table(
  user_id       uuid,
  card_id       text,
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
  select gci.user_id, gci.card_id, gci.grader, gci.grade, gci.quantity,
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
