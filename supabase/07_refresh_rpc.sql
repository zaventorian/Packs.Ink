-- Postgres function exposed via PostgREST RPC. Called by the daily ETL after
-- new prices are upserted to keep the rarity_avg_daily materialized view
-- current. SECURITY DEFINER so the service_role caller can refresh even
-- though anon/authenticated can only SELECT.

create or replace function public.refresh_rarity_avg_daily()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  -- CONCURRENTLY requires a unique index (we created one in 06_rarity_avg_daily.sql).
  -- Falls back to a plain refresh if concurrent isn't supported for some reason.
  begin
    refresh materialized view concurrently public.rarity_avg_daily;
  exception when others then
    refresh materialized view public.rarity_avg_daily;
  end;
end $$;

-- Only the service_role (used by the ETL) should be able to call this.
revoke all on function public.refresh_rarity_avg_daily() from public, anon, authenticated;
grant  execute on function public.refresh_rarity_avg_daily() to service_role;
