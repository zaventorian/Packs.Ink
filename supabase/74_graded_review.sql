-- 74_graded_review.sql
-- Review/moderation for the per-sale graded dataset (graded_sales, migration 71):
--   • users can REPORT a sale they think is wrong (mislabeled grade/grader, a raw
--     card listed as graded, a non-card lot, …) with an optional comment;
--   • a small admin allowlist can EDIT (fix grader/grade/card) or DELETE a sale,
--     and work a queue of open reports.
-- Admin actions hit graded_sales directly (the card-detail scatter reads that
-- table, so fixes show immediately); the rollup (Screener / collection value)
-- reflects them after admin_refresh_graded_rollup() or the next nightly refresh.

------------------------------------------------------------------------------
-- Admin allowlist
------------------------------------------------------------------------------
create table if not exists public.graded_admins (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  granted_at timestamptz default now()
);
alter table public.graded_admins enable row level security;
grant select, insert, delete on public.graded_admins to service_role;

create or replace function public.is_graded_admin()
returns boolean
language sql stable security definer set search_path = public
as $$ select exists(select 1 from public.graded_admins a where a.user_id = auth.uid()); $$;
grant execute on function public.is_graded_admin() to anon, authenticated;

insert into public.graded_admins(user_id)
select id from auth.users where lower(email) = 'zaventorian@gmail.com'
on conflict (user_id) do nothing;

------------------------------------------------------------------------------
-- Reports
------------------------------------------------------------------------------
create table if not exists public.graded_sale_reports (
  report_id   bigint generated always as identity primary key,
  item_id     text not null references public.graded_sales(item_id) on delete cascade,
  user_id     uuid references auth.users(id) on delete set null,
  comment     text,
  status      text not null default 'open',   -- open | resolved | dismissed
  created_at  timestamptz default now(),
  resolved_at timestamptz,
  resolved_by uuid
);
create index if not exists graded_sale_reports_status_idx on public.graded_sale_reports(status, created_at desc);
create index if not exists graded_sale_reports_item_idx   on public.graded_sale_reports(item_id);

alter table public.graded_sale_reports enable row level security;
-- Users may only INSERT their own report; reading/curating is admin-only via RPC.
drop policy if exists "graded report insert own" on public.graded_sale_reports;
create policy "graded report insert own" on public.graded_sale_reports
  for insert to authenticated with check (user_id = auth.uid());
grant insert on public.graded_sale_reports to authenticated;
grant select, insert, update, delete on public.graded_sale_reports to service_role;

-- User-facing report RPC (validates the sale exists, stamps user_id server-side).
create or replace function public.report_graded_sale(p_item_id text, p_comment text)
returns void language plpgsql security definer set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'sign in to report'; end if;
  if not exists(select 1 from public.graded_sales where item_id = p_item_id) then
    raise exception 'unknown sale';
  end if;
  insert into public.graded_sale_reports(item_id, user_id, comment)
  values (p_item_id, auth.uid(), nullif(btrim(coalesce(p_comment, '')), ''));
end;
$$;
grant execute on function public.report_graded_sale(text, text) to authenticated;

------------------------------------------------------------------------------
-- Admin curation RPCs
------------------------------------------------------------------------------
-- Edit a sale. Null args leave the field unchanged. grade is normalized to text.
create or replace function public.admin_update_graded_sale(
  p_item_id text,
  p_grader  text default null,
  p_grade   text default null,
  p_card_id text default null)
returns void language plpgsql security definer set search_path = public
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  update public.graded_sales set
    grader  = coalesce(nullif(btrim(p_grader), ''), grader),
    grade   = coalesce(nullif(btrim(p_grade),  ''), grade),
    card_id = coalesce(nullif(btrim(p_card_id),''), card_id)
  where item_id = p_item_id;
end;
$$;
grant execute on function public.admin_update_graded_sale(text, text, text, text) to authenticated;

-- Hard-delete a sale (e.g. a raw card mislisted as graded, or a lot).
create or replace function public.admin_delete_graded_sale(p_item_id text)
returns void language plpgsql security definer set search_path = public
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  delete from public.graded_sales where item_id = p_item_id;
end;
$$;
grant execute on function public.admin_delete_graded_sale(text) to authenticated;

-- Queue: open (or any-status) reports joined to their sale details. Non-admins
-- get an empty set (the is_graded_admin gate is in the WHERE).
create or replace function public.admin_list_graded_reports(p_status text default 'open')
returns table(
  report_id bigint, item_id text, comment text, status text, created_at timestamptz,
  title text, grader text, grade text, card_id text,
  sale_price numeric, sold_date date, listing_url text, image_url text)
language sql stable security definer set search_path = public
as $$
  select r.report_id, r.item_id, r.comment, r.status, r.created_at,
         s.title, s.grader, s.grade, s.card_id, s.sale_price, s.sold_date, s.listing_url, s.image_url
  from public.graded_sale_reports r
  join public.graded_sales s on s.item_id = r.item_id
  where public.is_graded_admin()
    and (p_status is null or r.status = p_status)
  order by r.created_at desc;
$$;
grant execute on function public.admin_list_graded_reports(text) to authenticated;

-- Resolve / dismiss a report.
create or replace function public.admin_resolve_report(p_report_id bigint, p_status text)
returns void language plpgsql security definer set search_path = public
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  update public.graded_sale_reports
    set status = p_status, resolved_at = now(), resolved_by = auth.uid()
  where report_id = p_report_id;
end;
$$;
grant execute on function public.admin_resolve_report(bigint, text) to authenticated;

-- Admin-triggered rollup refresh so edits/deletes reach the Screener + collection
-- value without waiting for the nightly job. Separate from the edit RPCs (a
-- concurrent refresh shouldn't share a transaction with a write).
create or replace function public.admin_refresh_graded_rollup()
returns void language plpgsql security definer set search_path = public, extensions
set statement_timeout = '5min'
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  refresh materialized view concurrently public.graded_sales_rollup;
exception when others then
  refresh materialized view public.graded_sales_rollup;
end;
$$;
grant execute on function public.admin_refresh_graded_rollup() to authenticated;

notify pgrst, 'reload schema';
