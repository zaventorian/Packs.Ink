-- 175: the latest Discord movers report, kept for /reports send.
-- scripts/discord_reports.py writes one row per cadence each day (service key)
-- and puts the report's pictures in the public discord-reports bucket; the bot
-- Worker reads the row (service key) and posts it in the channel that asked.
-- RLS on with NO policies: nothing public reads or writes the table. The
-- pictures are public on purpose - they are posted to Discord anyway.
create table if not exists public.discord_report_latest (
  cadence    text primary key check (cadence in ('daily', 'weekly')),
  price_date date not null,
  embeds     jsonb not null,
  plain      jsonb not null,
  files      jsonb not null default '[]'::jsonb,
  built_at   timestamptz not null default now()
);

alter table public.discord_report_latest enable row level security;
revoke all on public.discord_report_latest from anon, authenticated;
grant select, insert, update, delete on public.discord_report_latest to service_role;

insert into storage.buckets (id, name, public)
  values ('discord-reports', 'discord-reports', true)
  on conflict (id) do nothing;

notify pgrst, 'reload schema';
