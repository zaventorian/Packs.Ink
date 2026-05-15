-- Fix: matview refresh RPCs hit Supabase's default PostgREST statement
-- timeout (PG error 57014, "canceling statement due to statement timeout").
-- The card_prices_latest / rarity_avg_daily / price_movers refreshes have
-- grown past it as prices_daily crossed several million rows. Sealed was
-- still small enough to fit.
--
-- Fix: pin each function to statement_timeout = '5min'. Bounded so a
-- runaway never hangs, but generous enough to absorb the full concurrent
-- refresh of every matview we have today plus growth. SECURITY DEFINER
-- functions inherit role-level timeout by default; an explicit SET on the
-- function overrides it.
--
-- Idempotent: each create-or-replace just rebuilds the function body.

create or replace function public.refresh_card_prices_latest()
returns void
language plpgsql
security definer
set search_path = public, extensions, pg_catalog
set statement_timeout = '5min'
as $$
begin
  begin
    refresh materialized view concurrently public.card_prices_latest;
  exception when others then
    refresh materialized view public.card_prices_latest;
  end;
end $$;

create or replace function public.refresh_rarity_avg_daily()
returns void
language plpgsql
security definer
set search_path = public, extensions, pg_catalog
set statement_timeout = '5min'
as $$
begin
  begin
    refresh materialized view concurrently public.rarity_avg_daily;
  exception when others then
    refresh materialized view public.rarity_avg_daily;
  end;
end $$;

create or replace function public.refresh_price_movers()
returns void
language plpgsql
security definer
set search_path = public, extensions, pg_catalog
set statement_timeout = '5min'
as $$
begin
  begin
    refresh materialized view concurrently public.price_movers;
  exception when others then
    refresh materialized view public.price_movers;
  end;
end $$;

create or replace function public.refresh_sealed_prices_latest()
returns void
language plpgsql
security definer
set search_path = public, extensions, pg_catalog
set statement_timeout = '5min'
as $$
begin
  begin
    refresh materialized view concurrently public.sealed_prices_latest;
  exception when others then
    refresh materialized view public.sealed_prices_latest;
  end;
end $$;

notify pgrst, 'reload schema';
