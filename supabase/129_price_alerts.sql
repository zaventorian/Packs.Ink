-- Migration 129: price alerts.
--
-- What turns a screener from a place you visit into a service that contacts
-- you. Built on watchlists (migration 127) rather than free-floating, because a
-- rule needs a subject and "the cards I already told you I care about" is the
-- one the user has already curated.
--
-- ── What this migration is and isn't ────────────────────────────────────────
-- It is the RULE STORE and the FIRING LEDGER. It is not a delivery mechanism.
-- The site has no web-push infrastructure today — no VAPID keys, no
-- subscription table, no sender; a grep for pushManager across Index.html and
-- sw.js returns nothing. Rules are therefore evaluated CLIENT-SIDE against the
-- price_movers snapshot the Screener already loads, and fired alerts land in an
-- in-app inbox.
--
-- That covers the common case honestly: prices move once a day, so "tell me
-- what happened while I was away" is answered the moment the user opens the
-- app. It does NOT cover "tell me while I'm not looking", and nothing here
-- pretends otherwise. The schema is deliberately shaped so a server-side sender
-- can be added without touching it: `alert_events` is written by whoever
-- evaluates, and `delivered_at` exists for a future sender to stamp.
--
-- ── Why the ledger is a table and not localStorage ──────────────────────────
-- An alert that fires on your phone and fires again on your laptop is noise.
-- The ledger is what makes a firing a single event across devices, and its
-- unique index is what makes re-evaluation idempotent: the same rule crossing
-- the same threshold on the same day inserts once and no-ops thereafter.
--
-- Idempotent.

create table if not exists public.price_alerts (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  -- Scope. A rule watches either one card or a whole watchlist; exactly one,
  -- enforced below. A list rule is the useful default — it keeps working as the
  -- list changes, instead of needing a new rule per card.
  watchlist_id uuid references public.watchlists(id) on delete cascade,
  card_id      text,
  printing     text not null default 'Normal',

  -- What to watch. 'low' | 'market' — the same two bases the Screener toggles.
  basis        text not null default 'market' check (basis in ('low','market')),
  -- 'above' | 'below'  -> absolute price crossing, threshold is dollars
  -- 'pct_up' | 'pct_down' -> Δ% over `window_key`, threshold is percent
  kind         text not null check (kind in ('above','below','pct_up','pct_down')),
  threshold    numeric(12,2) not null,
  -- Only read for the pct_* kinds. Matches the price_movers column suffixes.
  window_key   text not null default 'pct_7d'
                 check (window_key in ('pct_1d','pct_7d','pct_30d','pct_90d','pct_180d','pct_365d')),

  enabled      boolean not null default true,
  -- Re-arm delay. Without it a card sitting above its threshold fires every
  -- single day forever; with it, one firing then silence until the condition
  -- has been false again for this long. 0 = fire at most once per day.
  cooldown_days int not null default 7 check (cooldown_days between 0 and 365),

  note         text check (note is null or length(note) <= 300),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),

  constraint price_alerts_one_scope check (
    (watchlist_id is not null and card_id is null)
    or (watchlist_id is null and card_id is not null)
  )
);

create index if not exists price_alerts_user_idx
  on public.price_alerts (user_id, enabled);

create table if not exists public.alert_events (
  id           uuid primary key default gen_random_uuid(),
  alert_id     uuid not null references public.price_alerts(id) on delete cascade,
  user_id      uuid not null references auth.users(id) on delete cascade,
  -- Which card actually tripped. A watchlist rule can fire for several cards on
  -- the same day, and each is its own event — collapsing them would make the
  -- inbox say "your list moved" and leave the user to go find out which card.
  card_id      text not null,
  printing     text not null default 'Normal',
  -- The observed value and the price date it came from, snapshotted so the
  -- inbox still reads correctly weeks later when the price has moved on.
  observed     numeric(12,2),
  price_date   date not null,
  fired_at     timestamptz not null default now(),
  read_at      timestamptz,
  -- Reserved for a future server-side sender. Null forever under client-side
  -- evaluation, which is the honest representation of "nothing was sent".
  delivered_at timestamptz
);

-- Idempotency key. Re-running the evaluator — on a reload, on another device,
-- or later by a server job — must not duplicate a firing. price_date rather
-- than fired_at, because the price snapshot is what the rule actually saw.
create unique index if not exists alert_events_unique
  on public.alert_events (alert_id, card_id, printing, price_date);
create index if not exists alert_events_user_idx
  on public.alert_events (user_id, fired_at desc);
-- Partial index for the unread badge, which is the hot read on every page load.
create index if not exists alert_events_unread_idx
  on public.alert_events (user_id, fired_at desc) where read_at is null;

-- ── RLS ─────────────────────────────────────────────────────────────────
-- Owner-only throughout. auth.uid() wrapped in (select …) per migration 91.
alter table public.price_alerts enable row level security;
alter table public.alert_events enable row level security;

drop policy if exists "price_alerts: select own" on public.price_alerts;
drop policy if exists "price_alerts: insert own" on public.price_alerts;
drop policy if exists "price_alerts: update own" on public.price_alerts;
drop policy if exists "price_alerts: delete own" on public.price_alerts;

create policy "price_alerts: select own" on public.price_alerts for select
  using ((select auth.uid()) = user_id);
create policy "price_alerts: insert own" on public.price_alerts for insert
  with check ((select auth.uid()) = user_id);
create policy "price_alerts: update own" on public.price_alerts for update
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "price_alerts: delete own" on public.price_alerts for delete
  using ((select auth.uid()) = user_id);

drop policy if exists "alert_events: select own" on public.alert_events;
drop policy if exists "alert_events: insert own" on public.alert_events;
drop policy if exists "alert_events: update own" on public.alert_events;
drop policy if exists "alert_events: delete own" on public.alert_events;

create policy "alert_events: select own" on public.alert_events for select
  using ((select auth.uid()) = user_id);
-- The client evaluator inserts its own firings, so the insert policy also has
-- to confirm the alert being fired belongs to the same user — otherwise a
-- crafted request could stamp events onto someone else's alert_id.
create policy "alert_events: insert own" on public.alert_events for insert
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.price_alerts a
      where a.id = alert_id and a.user_id = (select auth.uid())
    )
  );
create policy "alert_events: update own" on public.alert_events for update
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "alert_events: delete own" on public.alert_events for delete
  using ((select auth.uid()) = user_id);

-- ⚠ A new relation grants NOTHING implicitly (the migration 125/126 lesson).
grant select, insert, update, delete on public.price_alerts to authenticated;
grant select, insert, update, delete on public.alert_events to authenticated;
grant select, insert, update, delete on public.price_alerts to service_role;
grant select, insert, update, delete on public.alert_events to service_role;

drop trigger if exists price_alerts_updated_at on public.price_alerts;
create trigger price_alerts_updated_at
  before update on public.price_alerts
  for each row execute function public.set_updated_at();

-- Retention. An inbox nobody prunes becomes a table nobody queries. 180 days is
-- well past any "what happened while I was away" window and keeps the unread
-- index small. Called by the daily selfheal job alongside cleanup_old_trades().
create or replace function public.cleanup_old_alert_events()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  delete from public.alert_events where fired_at < now() - interval '180 days';
end $$;

revoke all on function public.cleanup_old_alert_events() from public, anon, authenticated;
grant  execute on function public.cleanup_old_alert_events() to service_role;

notify pgrst, 'reload schema';
