-- 173: Discord bot movers-report subscriptions.
-- One row per (server, channel, cadence). Written by the Discord bot Worker
-- (service key) when a server manager runs /reports; read by
-- scripts/discord_reports.py (service key) to post the report.
-- RLS on with NO policies: nothing public reads or writes it.
create table if not exists public.discord_report_subscriptions (
  guild_id       text not null,
  channel_id     text not null,
  cadence        text not null check (cadence in ('daily', 'weekly')),
  created_by     text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  last_posted_on date,
  last_error     text,
  primary key (guild_id, channel_id, cadence)
);

alter table public.discord_report_subscriptions enable row level security;
revoke all on public.discord_report_subscriptions from anon, authenticated;
grant select, insert, update, delete on public.discord_report_subscriptions to service_role;

notify pgrst, 'reload schema';
