-- 137_amazon_stock_checks.sql — the manual Amazon stock check (2026-09-10).
--
-- Until Creators API access (10 shipped sales in 30 days), whether a shelf
-- product is in stock on Amazon is checked BY A PERSON: an admin opens each
-- listing from the checklist on /gear and marks it. A product marked out of
-- stock is HIDDEN from the home "Lorcana on Amazon" row and from /gear.
--
-- Two things this table must never become:
--   · a display source. Amazon licenses stock and price only through its API,
--     so nothing here is ever shown — the flag only decides which links we
--     feature, which is ordinary editorial curation;
--   · filled by a script. Reading Amazon pages on a schedule is the automated
--     data gathering Amazon's Conditions of Use prohibit, and it trips their
--     bot checks anyway.
--
-- listing_key is the ASIN for a product page, or "s:" + the lowercased search
-- terms for a search (amazonListingKey in Index.html) — never the tagged URL,
-- so a change of associate tag can't orphan every check.

create table if not exists public.amazon_stock_checks (
  listing_key  text primary key check (char_length(listing_key) between 3 and 300),
  out_of_stock boolean not null default false,
  checked_at   timestamptz not null default now()
);

alter table public.amazon_stock_checks enable row level security;

-- Anyone can read: the home row has to know what to hide for signed-out
-- visitors too. It is our own curation flag, not Amazon data.
drop policy if exists amazon_stock_checks_read on public.amazon_stock_checks;
create policy amazon_stock_checks_read on public.amazon_stock_checks
  for select to anon, authenticated using (true);

-- Only graded admins write. The client upserts, and ON CONFLICT DO UPDATE needs
-- BOTH an insert and an update policy or it is refused.
drop policy if exists amazon_stock_checks_admin_insert on public.amazon_stock_checks;
create policy amazon_stock_checks_admin_insert on public.amazon_stock_checks
  for insert to authenticated with check ((select public.is_graded_admin()));

drop policy if exists amazon_stock_checks_admin_update on public.amazon_stock_checks;
create policy amazon_stock_checks_admin_update on public.amazon_stock_checks
  for update to authenticated
  using ((select public.is_graded_admin()))
  with check ((select public.is_graded_admin()));

drop policy if exists amazon_stock_checks_admin_delete on public.amazon_stock_checks;
create policy amazon_stock_checks_admin_delete on public.amazon_stock_checks
  for delete to authenticated using ((select public.is_graded_admin()));

-- A new table grants nothing implicitly (the migration-126 lesson): without
-- these, every read is a flat 403 before RLS is even consulted.
grant select on public.amazon_stock_checks to anon, authenticated;
grant insert, update, delete on public.amazon_stock_checks to authenticated;
grant select, insert, update, delete on public.amazon_stock_checks to service_role;

notify pgrst, 'reload schema';
