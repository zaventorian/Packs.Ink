-- 65: Privacy / retention hardening from the full-site review.
--   (1) Stop leaking purchase prices to collection-share viewers.
--   (2) Add a 30-day retention sweep for anonymous trade-share rows.
--   (3) Rotate a deck's share token when it becomes LESS visible (incl.
--       public -> unlisted), not only on -> private.
-- All three are behavior-preserving for the client (graceful) or additive, so
-- safe to apply live independent of the Index.html deploy.

-- ───────────────────────────────────────────────────────────────────────────
-- (1) Hide amount_paid (and graded custom_value) from the shared-collection
-- RPCs. These are anon-executable for sections the owner sets to 'public', so
-- they were exposing what the owner PAID for cards to the whole world. The
-- owner still sees their own cost data via direct table reads; viewers now see
-- quantities/values but not purchase price. acquired_date stays — the viewer's
-- value-history chart needs it to gate historical contributions, and it isn't a
-- price. RETURNS TABLE signatures change, so drop + recreate (can't REPLACE).
drop function if exists public.get_shared_collection_sealed(uuid, text);
create function public.get_shared_collection_sealed(p_user_id uuid, p_token text)
returns table(user_id uuid, tcgplayer_product_id bigint, condition text,
              quantity integer, notes text, acquired_date date,
              updated_at timestamptz)
language sql
security definer
set search_path to 'public'
as $function$
  select sci.user_id, sci.tcgplayer_product_id, sci.condition, sci.quantity, sci.notes,
         sci.acquired_date, sci.updated_at
    from public.sealed_collection_items sci
    join public.profiles p on p.user_id = sci.user_id
   where sci.user_id = p_user_id
     and (
       p.collection_sealed_visibility = 'public'
       OR (p.collection_sealed_visibility = 'unlisted' AND p.collection_share_token = p_token)
     );
$function$;
grant execute on function public.get_shared_collection_sealed(uuid, text) to anon, authenticated;

drop function if exists public.get_shared_collection_graded(uuid, text);
create function public.get_shared_collection_graded(p_user_id uuid, p_token text)
returns table(user_id uuid, card_id text, printing text, grader text, grade text,
              quantity integer, acquired_date date, updated_at timestamptz)
language sql
security definer
set search_path to 'public'
as $function$
  select gci.user_id, gci.card_id, gci.printing, gci.grader, gci.grade, gci.quantity,
         gci.acquired_date, gci.updated_at
    from public.graded_collection_items gci
    join public.profiles p on p.user_id = gci.user_id
   where gci.user_id = p_user_id
     and (
       p.collection_graded_visibility = 'public'
       OR (p.collection_graded_visibility = 'unlisted' AND p.collection_share_token = p_token)
     );
$function$;
grant execute on function public.get_shared_collection_graded(uuid, text) to anon, authenticated;

-- ───────────────────────────────────────────────────────────────────────────
-- (2) 30-day retention for trade-share rows. create_trade is anon-callable and
-- uncapped, so the table would grow without bound. The daily ETL (selfheal job)
-- calls this. service_role-only; SECURITY DEFINER so it bypasses the trades
-- RLS (which has no policies).
create or replace function public.cleanup_old_trades()
returns integer
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  n integer;
begin
  delete from public.trades where created_at < now() - interval '30 days';
  get diagnostics n = row_count;
  return n;
end;
$function$;
revoke all on function public.cleanup_old_trades() from public;
grant execute on function public.cleanup_old_trades() to service_role;

-- ───────────────────────────────────────────────────────────────────────────
-- (3) Rotate a deck's share token whenever its visibility DECREASES, not only
-- on -> private. public(2) > unlisted(1) > private(0). Previously a deck shared
-- while public kept its token after being set to unlisted, so a token someone
-- scraped while it was public still worked post-unlist. (Function keeps its name
-- so the existing BEFORE UPDATE trigger binding is unchanged.)
create or replace function public.rotate_share_token_on_private()
returns trigger
language plpgsql
set search_path to 'public', 'extensions'
as $function$
declare
  rank_old int := case OLD.visibility when 'public' then 2 when 'unlisted' then 1 else 0 end;
  rank_new int := case NEW.visibility when 'public' then 2 when 'unlisted' then 1 else 0 end;
begin
  if rank_new < rank_old then
    NEW.share_token := public.gen_share_token();
  end if;
  return NEW;
end;
$function$;

notify pgrst, 'reload schema';
