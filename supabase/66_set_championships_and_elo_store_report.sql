-- 66_set_championships_and_elo_store_report.sql
-- Record of objects created live via the Supabase MCP across 2026-06-10/11 for
-- the RPH Set-Championship feature + the credential-gated ELO store report.
-- Idempotent; safe to re-run.

-- ── Upcoming Set Championships (scraped from Ravensburger Play) ──────────────
-- Populated by scripts/elo/discover_wu_scs.py (RPH /api/v2/events/).
create table if not exists public.set_championships (
  event_id        bigint primary key,
  name            text,
  set_name        text not null default 'Wilds Unknown',
  store_id        bigint,
  store_name      text,
  store_website   text,
  start_datetime  timestamptz,
  end_datetime    timestamptz,
  timezone        text,
  full_address    text,
  city text, state text, country text,
  latitude double precision, longitude double precision,
  registered_user_count integer,
  capacity integer,
  cost_cents integer, currency text,
  gameplay_format text,
  display_status text,
  url text,
  scraped_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists set_championships_start_idx   on public.set_championships (start_datetime);
create index if not exists set_championships_country_idx on public.set_championships (country);
alter table public.set_championships enable row level security;
drop policy if exists "public read set_championships" on public.set_championships;
create policy "public read set_championships" on public.set_championships for select using (true);
grant select on public.set_championships to anon, authenticated;

-- ── ELO-tracked stores + the "Upcoming SCs" tab view ────────────────────────
-- Populated by scripts/elo/sync_elo_tracked_stores.py (lorcana_elo.db ∩ scrape,
-- region-guarded to IL/IN/WI/MI).
create table if not exists public.elo_tracked_stores (
  store_id bigint primary key, store_name text, added_at timestamptz not null default now()
);
alter table public.elo_tracked_stores enable row level security;
drop policy if exists "public read elo_tracked_stores" on public.elo_tracked_stores;
create policy "public read elo_tracked_stores" on public.elo_tracked_stores for select using (true);
grant select on public.elo_tracked_stores to anon, authenticated;

create or replace view public.elo_upcoming_scs with (security_invoker = on) as
  select sc.* from public.set_championships sc
  join public.elo_tracked_stores t on t.store_id = sc.store_id;
grant select on public.elo_upcoming_scs to anon, authenticated;

-- ── Store scouting report (credential-gated) ────────────────────────────────
-- Allowlist: admins always pass; insert user_ids here to grant non-admins.
create table if not exists public.elo_report_viewers (
  user_id uuid primary key, note text, added_at timestamptz not null default now()
);
alter table public.elo_report_viewers enable row level security;  -- only SECURITY DEFINER fns read it

create or replace function public.can_view_store_report()
returns boolean language sql security definer set search_path = public, extensions stable as $$
  select coalesce(public.is_tournament_admin(auth.uid()), false)
      or exists (select 1 from public.elo_report_viewers v where v.user_id = auth.uid());
$$;
revoke all on function public.can_view_store_report() from public;
grant execute on function public.can_view_store_report() to authenticated;

-- Full report for one store (matched by normalized name across elo_events):
-- summary, past events (+winner), and every player who's played there ranked by
-- current ELO with visit count, last-seen, and store wins. See the live
-- definition created via MCP (public.get_store_report(text)); kept there as the
-- source of truth — re-create from that if this file and the DB ever diverge.

notify pgrst, 'reload schema';
