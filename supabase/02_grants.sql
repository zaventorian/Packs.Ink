-- Grant explicit table access since "Automatically expose new tables" is off.
-- service_role: full read/write (used by ETL scripts via secret key)
-- anon / authenticated: read-only on public catalog/price data (used by the site)

-- service_role: full access on all three tables
grant select, insert, update, delete on public.sets         to service_role;
grant select, insert, update, delete on public.cards        to service_role;
grant select, insert, update, delete on public.prices_daily to service_role;

-- anon + authenticated: read only
grant select on public.sets               to anon, authenticated;
grant select on public.cards              to anon, authenticated;
grant select on public.prices_daily       to anon, authenticated;
grant select on public.card_prices_latest to anon, authenticated;

-- Ensure schema usage is granted (usually default, but safe to assert)
grant usage on schema public to anon, authenticated, service_role;
