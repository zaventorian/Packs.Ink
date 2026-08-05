-- 115_scan_samples_daily_cap.sql
-- Abuse bound on scanner uploads, needed now that the scanner is a public beta.
--
-- Every scan writes one scan_samples row and up to three storage objects (the
-- rectified card, the raw camera frame, the approach filmstrip) — measured
-- 2026-08-04 at ~149 KB per object, so ~400 KB per scan. Four allowlisted
-- testers had already put 500 MB in the bucket. With the allowlist gone, a
-- single authenticated account looping the upload path is a storage bill, and
-- the RLS policy alone doesn't bound it: it says WHERE, not HOW MUCH.
--
-- The cap is deliberately generous rather than tight. Real sessions are large —
-- the biggest genuine day on record is 343 scans (a tester running physical
-- binders), and throttling that would break the exact behaviour we want from
-- beta users. 1000/24h is ~3x the largest real session and still bounds one
-- account to a few hundred MB a day, which is a monitorable problem rather than
-- an unbounded one.
--
-- Rolling 24h, not calendar-day: a calendar cap is trivially doubled by
-- straddling midnight, and it would also punish a legitimate late-night session
-- for no reason.
--
-- Client behaviour on hit: uploadSample is best-effort and swallows insert
-- errors, so scanning keeps working normally — identification is local and the
-- collection-save path never touched scan_samples. The user loses nothing but
-- the flywheel contribution, which is the correct thing to shed under abuse.

create index if not exists scan_samples_user_created_idx
  on public.scan_samples (user_id, created_at desc);

create or replace function public.scan_samples_daily_cap()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  recent integer;
begin
  -- SECURITY DEFINER so the count sees the user's own rows regardless of the
  -- caller's RLS view. Bounded by the (user_id, created_at desc) index.
  select count(*) into recent
    from public.scan_samples
   where user_id = new.user_id
     and created_at >= now() - interval '24 hours';

  if recent >= 1000 then
    raise exception 'scan sample rate limit reached (1000 per 24h)'
      using errcode = 'check_violation';
  end if;

  return new;
end;
$$;

drop trigger if exists scan_samples_daily_cap_trg on public.scan_samples;
create trigger scan_samples_daily_cap_trg
  before insert on public.scan_samples
  for each row execute function public.scan_samples_daily_cap();

-- Statement-level backstop. The row trigger alone is bypassable: inside a BEFORE
-- ROW trigger, rows inserted earlier by the SAME command are not yet visible, so
-- one `insert ... select from generate_series(1, 100000)` would sail through
-- 100k times seeing the same pre-command count. PostgREST will happily accept a
-- bulk array body, so that isn't theoretical.
--
-- This one runs once per statement, after the rows land, and sees all of them —
-- raising here rolls the whole statement back. Kept as a second trigger rather
-- than replacing the row one because the row check is the cheap common path
-- (single-row inserts from the client, indexed count of one user) while this
-- scans the window across users only once per statement.
create or replace function public.scan_samples_daily_cap_stmt()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform 1
     from public.scan_samples
    where created_at >= now() - interval '24 hours'
    group by user_id
   having count(*) > 1000
    limit 1;

  if found then
    raise exception 'scan sample rate limit reached (1000 per 24h)'
      using errcode = 'check_violation';
  end if;

  return null;
end;
$$;

drop trigger if exists scan_samples_daily_cap_stmt_trg on public.scan_samples;
create trigger scan_samples_daily_cap_stmt_trg
  after insert on public.scan_samples
  for each statement execute function public.scan_samples_daily_cap_stmt();

notify pgrst, 'reload schema';
