-- Footer "Send feedback" widget (every page). Anyone — signed in or not — can
-- submit a short comment; we capture their account (auth.uid + email) when
-- logged in plus the page they were on, so the admin can follow up. Graded
-- admins read + triage it in-app (get_feedback / set_feedback_resolved /
-- delete_feedback), gated on the existing is_graded_admin() helper.

create table if not exists public.feedback (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  user_id     uuid references auth.users(id) on delete set null,
  user_email  text,
  page        text,
  comment     text not null,
  user_agent  text,
  resolved    boolean not null default false
);

create index if not exists feedback_created_idx on public.feedback (created_at desc);

-- RLS on with no policies: every access path is a SECURITY DEFINER function
-- below (anon/auth submit; admin read + triage). No direct table reads/writes.
alter table public.feedback enable row level security;

-- Anonymous-write hardening (submit_feedback is anon-callable): cap submissions
-- per source IP, tracked by a salted SHA-256 of the caller's IP — no raw IPs
-- stored, same posture as create_trade (migration 102). Self-prunes each call.
create table if not exists public.feedback_submit_events (
  ip_hash    text        not null,
  created_at timestamptz not null default now()
);
create index if not exists feedback_submit_events_hash_time_idx
  on public.feedback_submit_events (ip_hash, created_at);
alter table public.feedback_submit_events enable row level security;

-- Submit — callable by anon + authenticated. Captures the caller's uid/email
-- server-side (client can't spoof it) plus the page + user agent.
create or replace function public.submit_feedback(
  p_comment text, p_page text default null, p_user_agent text default null)
returns uuid
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $$
declare
  v_id     uuid;
  v_email  text;
  v_ip     text;
  v_hash   text;
  v_recent int;
begin
  if p_comment is null or length(btrim(p_comment)) = 0 then
    raise exception 'empty feedback';
  end if;

  -- IP-hash rate limit: 10 submissions / hour / IP.
  begin
    v_ip := split_part(coalesce(
      (current_setting('request.headers', true))::jsonb ->> 'x-forwarded-for', ''), ',', 1);
  exception when others then
    v_ip := '';
  end;
  v_hash := encode(digest('packsink-feedback|' || coalesce(nullif(v_ip, ''), 'unknown'), 'sha256'), 'hex');
  delete from public.feedback_submit_events where created_at < now() - interval '2 hours';
  select count(*) into v_recent from public.feedback_submit_events
    where ip_hash = v_hash and created_at > now() - interval '1 hour';
  if v_recent >= 10 then
    raise exception 'rate limited: too much feedback submitted — try again in an hour';
  end if;
  insert into public.feedback_submit_events (ip_hash) values (v_hash);

  if auth.uid() is not null then
    select email into v_email from auth.users where id = auth.uid();
  end if;

  insert into public.feedback (user_id, user_email, page, comment, user_agent)
  values (auth.uid(), v_email,
          left(coalesce(p_page, ''), 400),
          left(p_comment, 5000),
          left(coalesce(p_user_agent, ''), 500))
  returning id into v_id;
  return v_id;
end;
$$;
grant execute on function public.submit_feedback(text, text, text) to anon, authenticated;

-- Admin read — gated on is_graded_admin(). Newest first.
create or replace function public.get_feedback()
returns setof public.feedback
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  return query select * from public.feedback order by created_at desc limit 2000;
end;
$$;
grant execute on function public.get_feedback() to authenticated;

-- Admin triage — mark resolved / reopen.
create or replace function public.set_feedback_resolved(p_id uuid, p_resolved boolean)
returns void
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  update public.feedback set resolved = coalesce(p_resolved, false) where id = p_id;
end;
$$;
grant execute on function public.set_feedback_resolved(uuid, boolean) to authenticated;

-- Admin delete.
create or replace function public.delete_feedback(p_id uuid)
returns void
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  delete from public.feedback where id = p_id;
end;
$$;
grant execute on function public.delete_feedback(uuid) to authenticated;

-- CREATE FUNCTION grants EXECUTE to PUBLIC by default, which would let anon
-- reach the admin RPCs (they'd fail the is_graded_admin() gate, but shouldn't
-- be exposed at all). Strip PUBLIC so the grants above are the whole story:
-- submit_feedback = anon + authenticated; the rest = authenticated only.
revoke execute on function public.submit_feedback(text, text, text) from public;
revoke execute on function public.get_feedback() from public;
revoke execute on function public.set_feedback_resolved(uuid, boolean) from public;
revoke execute on function public.delete_feedback(uuid) from public;

notify pgrst, 'reload schema';
