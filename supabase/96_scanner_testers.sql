-- 96_scanner_testers.sql
-- Separate allowlist for QA camera-scanner access, INDEPENDENT of graded_admins.
-- A scanner tester gets the camera scanner (locked to QA-only mode by the
-- client's SCANNER_QA_ONLY flag) but NO graded-curation powers and NO ability to
-- read anyone else's scans — the existing scan_samples RLS already scopes reads
-- to owner-or-graded-admin, and the per-user storage-folder policy means each
-- tester can only write/read their own QA photos. Zaven (a graded admin) reads
-- everyone's for review; the service-key downloader pulls them for analysis.
--
-- Email-keyed (not user_id) so an account can be granted before/without having
-- signed in yet — access activates the moment they log in with that Google email.

create table if not exists public.scanner_testers (
  email     text primary key,
  note      text,
  added_at  timestamptz not null default now()
);

-- Lock the table: no direct client access. The SECURITY DEFINER function below
-- is the only read path (it bypasses RLS as its owner).
alter table public.scanner_testers enable row level security;
revoke all on public.scanner_testers from anon, authenticated;

create or replace function public.is_scanner_tester()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.scanner_testers t
    where lower(t.email) = lower((select u.email from auth.users u where u.id = auth.uid()))
  );
$$;
grant execute on function public.is_scanner_tester() to anon, authenticated;

insert into public.scanner_testers (email) values
  ('amp3878@gmail.com'),
  ('ayyadpauljacobiii@gmail.com'),
  ('cjdummer18@gmail.com'),
  ('cody.braun1@gmail.com'),
  ('coocoolorcana@gmail.com'),
  ('daniel.vicens77@gmail.com'),
  ('drayton.hammond@gmail.com'),
  ('evan.knobloch@gmail.com'),
  ('paulaxelpaxel@gmail.com'),
  ('rabbid.ygo@gmail.com'),
  ('rhauge01@gmail.com'),
  ('saysay.konishi@gmail.com'),
  ('sayumikonishi@gmail.com'),
  ('shawn.tang.7@gmail.com'),
  ('zaven1718@gmail.com'),
  ('zavenganbatte@gmail.com'),
  ('zavensbackup@gmail.com')
on conflict (email) do nothing;

notify pgrst, 'reload schema';
