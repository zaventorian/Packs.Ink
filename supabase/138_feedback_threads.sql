-- 138_feedback_threads.sql — replies and follow-ups on footer feedback (2026-09-11).
--
-- The feedback box was one-way: you sent a note and nothing could come back.
-- Now every submission is the first message of a conversation. An admin
-- replies from the inbox; the sender sees the reply the next time they open
-- the feedback box (with a badge on the button and a notice in the corner),
-- and can follow up in the same thread.
--
-- WHO A THREAD BELONGS TO
--   · signed in  → the account (feedback.user_id), on any device;
--   · anonymous  → a random secret the browser generated and keeps
--                  (feedback.reply_token, 128 bits, the shape of a trade-link
--                  token). It is sent in request bodies only, never in a URL.
--                  Clear site data and the thread is gone from that person's
--                  view, which is the honest limit of "no account".
--   Anonymous notes sent before this migration have neither, so nobody can
--   read a reply to them; the inbox says so instead of offering to send one.
--
-- UNREAD, BOTH WAYS
--   last_user_at / last_admin_at are the newest message from each side;
--   user_seen_at / admin_seen_at are how far each side has read. Unread for
--   the sender = last_admin_at > user_seen_at; new for admins =
--   last_user_at > admin_seen_at. Marking seen takes the timestamp the reader
--   actually SAW (p_until), clamped to now(), never a bare now(): a reply that
--   lands between loading a thread and marking it read must stay unread.
--
-- ACCESS
--   feedback and feedback_messages stay RLS-on with no policies, exactly like
--   106: every client path is a SECURITY DEFINER function below. A follow-up
--   spends from the same per-IP and global limits as a new note (133) — it is
--   just another message into the same queue.
--
-- EXISTING ROWS: last_user_at backfills to created_at and admin_seen_at to
-- now(). Everything already in the inbox has been seen; without that the first
-- load after this migration would flag the whole historical queue as new.
--
-- submit_feedback gains a 4th parameter, so the 3-argument version is DROPPED
-- first — two overloads would make PostgREST's call ambiguous. The new one
-- defaults the token to null, so a client that never sends it keeps working.
--
-- PRECONDITIONS: 106 (feedback), 119 (service_role grant) and 133
-- (_client_ip + the rate-limited submit_feedback) applied. Idempotent.

-- ── 1. Thread bookkeeping on feedback ─────────────────────────────────────
alter table public.feedback
  add column if not exists reply_token   text,
  add column if not exists last_user_at  timestamptz,
  add column if not exists last_admin_at timestamptz,
  add column if not exists user_seen_at  timestamptz,
  add column if not exists admin_seen_at timestamptz;

update public.feedback set last_user_at  = created_at where last_user_at  is null;
update public.feedback set admin_seen_at = now()      where admin_seen_at is null;

alter table public.feedback
  alter column last_user_at set default now(),
  alter column last_user_at set not null;

-- A token names exactly one thread. NULLs (signed-in notes, and everything
-- sent before this migration) never collide.
create unique index if not exists feedback_reply_token_key on public.feedback (reply_token);
-- "My feedback" reads by account; this also covers the auth.users foreign key.
create index if not exists feedback_user_id_idx on public.feedback (user_id);

-- ── 2. Messages after the first ───────────────────────────────────────────
-- The original note stays in feedback.comment — the inbox and the scripts that
-- work the queue read it there — and this table holds everything after it.
create table if not exists public.feedback_messages (
  id          uuid primary key default gen_random_uuid(),
  feedback_id uuid not null references public.feedback(id) on delete cascade,
  created_at  timestamptz not null default now(),
  from_admin  boolean not null,
  author_id   uuid references auth.users(id) on delete set null,
  body        text not null check (char_length(body) between 1 and 5000)
);
create index if not exists feedback_messages_thread_idx
  on public.feedback_messages (feedback_id, created_at);
create index if not exists feedback_messages_author_idx
  on public.feedback_messages (author_id);

alter table public.feedback_messages enable row level security;
-- No policies and no anon/authenticated grant: every path is a definer
-- function. service_role reads it for the reason 119 lets it read feedback —
-- the queue is worked from scripts too. A new table grants nothing implicitly
-- (the 126 lesson), so without this that read is a flat 403.
grant select on public.feedback_messages to service_role;

-- ── 3. Helpers (never callable through the API) ──────────────────────────
-- Keep well-formed tokens only, at most 100. A browser sends every token it
-- holds; the shape check means junk in that list can't widen the match.
create or replace function public._feedback_tokens(p_tokens text[])
returns text[]
language sql
immutable
set search_path = ''
as $$
  select array(
    select t from unnest(p_tokens) as t
     where t ~ '^[A-Za-z0-9_-]{22,64}$'
     limit 100);
$$;

-- The per-IP and global limits submit_feedback has carried since 133, moved
-- here unchanged so a follow-up spends from the same bucket as a new note. A
-- plain (invoker) function called only from the definer functions below, so
-- it runs with their owner's privileges — same arrangement as _client_ip().
create or replace function public._feedback_rate_limit()
returns void
language plpgsql
set search_path to 'public', 'extensions'
as $$
declare
  v_ip     text;
  v_hash   text;
  v_recent int;
  v_total  int;
begin
  -- IP-hash rate limit: 10 messages / hour / IP.
  v_ip := public._client_ip();
  v_hash := encode(digest('packsink-feedback|' || coalesce(nullif(v_ip, ''), 'unknown'), 'sha256'), 'hex');
  delete from public.feedback_submit_events where created_at < now() - interval '2 hours';
  select count(*) into v_recent from public.feedback_submit_events
    where ip_hash = v_hash and created_at > now() - interval '1 hour';
  if v_recent >= 10 then
    raise exception 'rate limited: too much feedback submitted — try again in an hour';
  end if;
  -- Global backstop across every caller (120 / hour).
  select count(*) into v_total from public.feedback_submit_events
    where created_at > now() - interval '1 hour';
  if v_total >= 120 then
    raise exception 'rate limited: too much feedback submitted — try again in an hour';
  end if;
  insert into public.feedback_submit_events (ip_hash) values (v_hash);
end;
$$;

-- ── 4. Submit (anon + authenticated) ──────────────────────────────────────
drop function if exists public.submit_feedback(text, text, text);

create or replace function public.submit_feedback(
  p_comment text, p_page text default null, p_user_agent text default null,
  p_reply_token text default null)
returns uuid
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $$
declare
  v_id    uuid;
  v_email text;
  v_token text;
begin
  if p_comment is null or length(btrim(p_comment)) = 0 then
    raise exception 'empty feedback';
  end if;

  -- A signed-in thread is keyed on the account; only an anonymous one needs
  -- the token, so a signed-in caller's is ignored rather than stored.
  if auth.uid() is null and p_reply_token is not null then
    if p_reply_token !~ '^[A-Za-z0-9_-]{22,64}$' then
      raise exception 'invalid reply token';
    end if;
    v_token := p_reply_token;
  end if;

  perform public._feedback_rate_limit();

  if auth.uid() is not null then
    select email into v_email from auth.users where id = auth.uid();
  end if;

  insert into public.feedback
    (user_id, user_email, page, comment, user_agent, reply_token, last_user_at, admin_seen_at)
  values (auth.uid(), v_email,
          left(coalesce(p_page, ''), 400),
          left(p_comment, 5000),
          left(coalesce(p_user_agent, ''), 500),
          v_token,
          now(),
          -- An admin's own note is not news to the admins.
          case when public.is_graded_admin() then now() end)
  returning id into v_id;
  return v_id;
end;
$$;

-- ── 5. The sender's side (anon + authenticated) ───────────────────────────
-- Every thread the caller owns — by account, or by a token this browser holds —
-- newest activity first, messages included. Never returns the email, the user
-- agent or the token: the caller already has everything of theirs they need.
create or replace function public.get_my_feedback(p_tokens text[] default null)
returns jsonb
language plpgsql
stable
security definer
set search_path to 'public'
as $$
declare
  v_uid    uuid   := auth.uid();
  v_tokens text[] := public._feedback_tokens(p_tokens);
begin
  if v_uid is null and cardinality(v_tokens) = 0 then
    return '[]'::jsonb;
  end if;
  return coalesce((
    select jsonb_agg(s.thread order by s.last_at desc)
      from (
        select greatest(f.last_user_at, f.last_admin_at) as last_at,
               jsonb_build_object(
                 'id',            f.id,
                 'created_at',    f.created_at,
                 'page',          f.page,
                 'comment',       f.comment,
                 'resolved',      f.resolved,
                 'last_user_at',  f.last_user_at,
                 'last_admin_at', f.last_admin_at,
                 'unread',        coalesce(f.last_admin_at > coalesce(f.user_seen_at, '-infinity'::timestamptz), false),
                 'messages',      coalesce((
                    select jsonb_agg(jsonb_build_object(
                             'id',         m.id,
                             'created_at', m.created_at,
                             'from_admin', m.from_admin,
                             'body',       m.body)
                           order by m.created_at, m.id)
                      from public.feedback_messages m
                     where m.feedback_id = f.id), '[]'::jsonb)
               ) as thread
          from public.feedback f
         where (v_uid is not null and f.user_id = v_uid)
            or (f.reply_token is not null and f.reply_token = any(v_tokens))
         order by f.created_at desc
         limit 100
      ) s
  ), '[]'::jsonb);
end;
$$;

-- The badge: how many owned threads hold a reply the sender hasn't read, and
-- when the newest one landed (the corner notice dismisses per reply, by this).
create or replace function public.get_my_feedback_unread(p_tokens text[] default null)
returns jsonb
language plpgsql
stable
security definer
set search_path to 'public'
as $$
declare
  v_uid    uuid   := auth.uid();
  v_tokens text[] := public._feedback_tokens(p_tokens);
  v_count  int;
  v_latest timestamptz;
begin
  if v_uid is null and cardinality(v_tokens) = 0 then
    return jsonb_build_object('unread', 0, 'latest', null);
  end if;
  select count(*), max(f.last_admin_at) into v_count, v_latest
    from public.feedback f
   where ((v_uid is not null and f.user_id = v_uid)
       or (f.reply_token is not null and f.reply_token = any(v_tokens)))
     and f.last_admin_at is not null
     and f.last_admin_at > coalesce(f.user_seen_at, '-infinity'::timestamptz);
  return jsonb_build_object('unread', v_count, 'latest', v_latest);
end;
$$;

-- A follow-up from the sender. Reopens a resolved thread: an answer to
-- "resolved" usually means it isn't, and the inbox's Open list is where that
-- has to land.
create or replace function public.reply_my_feedback(
  p_id uuid, p_body text, p_tokens text[] default null)
returns jsonb
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $$
declare
  v_uid    uuid   := auth.uid();
  v_tokens text[] := public._feedback_tokens(p_tokens);
  v_n      int;
  v_msg    public.feedback_messages;
begin
  if p_body is null or length(btrim(p_body)) = 0 then
    raise exception 'empty message';
  end if;
  -- Ownership check and row lock in one: two follow-ups racing can't both
  -- slip under the cap below.
  perform 1 from public.feedback f
   where f.id = p_id
     and ((v_uid is not null and f.user_id = v_uid)
       or (f.reply_token is not null and f.reply_token = any(v_tokens)))
     for update;
  if not found then
    raise exception 'feedback not found';
  end if;
  select count(*) into v_n from public.feedback_messages where feedback_id = p_id;
  if v_n >= 100 then
    raise exception 'this conversation is full — please send new feedback instead';
  end if;

  perform public._feedback_rate_limit();

  insert into public.feedback_messages (feedback_id, from_admin, author_id, body)
  values (p_id, false, v_uid, left(btrim(p_body), 5000))
  returning * into v_msg;

  update public.feedback
     set last_user_at = v_msg.created_at,
         user_seen_at = greatest(coalesce(user_seen_at, '-infinity'::timestamptz), v_msg.created_at),
         resolved     = false
   where id = p_id;

  return jsonb_build_object('id', v_msg.id, 'created_at', v_msg.created_at,
                            'from_admin', false, 'body', v_msg.body);
end;
$$;

-- The sender opened a thread: mark it read up to the reply they saw.
create or replace function public.mark_my_feedback_seen(
  p_id uuid, p_until timestamptz default null, p_tokens text[] default null)
returns integer
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_uid    uuid   := auth.uid();
  v_tokens text[] := public._feedback_tokens(p_tokens);
  v_n      int;
begin
  if v_uid is null and cardinality(v_tokens) = 0 then
    return 0;
  end if;
  update public.feedback f
     set user_seen_at = greatest(coalesce(f.user_seen_at, '-infinity'::timestamptz),
                                 least(coalesce(p_until, now()), now()))
   where f.id = p_id
     and ((v_uid is not null and f.user_id = v_uid)
       or (f.reply_token is not null and f.reply_token = any(v_tokens)));
  get diagnostics v_n = row_count;
  return v_n;
end;
$$;

-- ── 6. The admin side (authenticated, gated on is_graded_admin) ──────────
-- The inbox: every thread with its messages, newest activity first. is_new
-- marks activity no admin has seen; reachable says whether a reply can reach
-- anyone at all (an account, or a token some browser holds).
create or replace function public.get_feedback_threads()
returns jsonb
language plpgsql
stable
security definer
set search_path to 'public'
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  return coalesce((
    select jsonb_agg(s.thread order by s.last_at desc)
      from (
        select greatest(f.last_user_at, f.last_admin_at) as last_at,
               jsonb_build_object(
                 'id',            f.id,
                 'created_at',    f.created_at,
                 'user_email',    f.user_email,
                 'page',          f.page,
                 'comment',       f.comment,
                 'user_agent',    f.user_agent,
                 'resolved',      f.resolved,
                 'last_user_at',  f.last_user_at,
                 'last_admin_at', f.last_admin_at,
                 'is_new',        f.last_user_at > coalesce(f.admin_seen_at, '-infinity'::timestamptz),
                 'reachable',     (f.user_id is not null or f.reply_token is not null),
                 'messages',      coalesce((
                    select jsonb_agg(jsonb_build_object(
                             'id',         m.id,
                             'created_at', m.created_at,
                             'from_admin', m.from_admin,
                             'body',       m.body)
                           order by m.created_at, m.id)
                      from public.feedback_messages m
                     where m.feedback_id = f.id), '[]'::jsonb)
               ) as thread
          from public.feedback f
         order by f.created_at desc
         limit 2000
      ) s
  ), '[]'::jsonb);
end;
$$;

-- The inbox button's badge.
create or replace function public.get_feedback_admin_unread()
returns integer
language plpgsql
stable
security definer
set search_path to 'public'
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  return (select count(*)::int from public.feedback f
           where f.last_user_at > coalesce(f.admin_seen_at, '-infinity'::timestamptz));
end;
$$;

-- An admin reply, optionally resolving the thread in the same breath. It does
-- NOT touch admin_seen_at: a follow-up that arrived while the reply was being
-- typed has not been seen, and marking seen is the inbox's job.
create or replace function public.admin_reply_feedback(
  p_id uuid, p_body text, p_resolve boolean default false)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_msg public.feedback_messages;
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  if p_body is null or length(btrim(p_body)) = 0 then
    raise exception 'empty message';
  end if;
  perform 1 from public.feedback where id = p_id for update;
  if not found then
    raise exception 'feedback not found';
  end if;

  insert into public.feedback_messages (feedback_id, from_admin, author_id, body)
  values (p_id, true, auth.uid(), left(btrim(p_body), 5000))
  returning * into v_msg;

  update public.feedback
     set last_admin_at = v_msg.created_at,
         resolved      = case when coalesce(p_resolve, false) then true else resolved end
   where id = p_id;

  return jsonb_build_object('id', v_msg.id, 'created_at', v_msg.created_at,
                            'from_admin', true, 'body', v_msg.body);
end;
$$;

-- The inbox was opened: mark what it showed as seen, up to the newest user
-- activity it actually loaded.
create or replace function public.mark_feedback_seen_admin(
  p_ids uuid[], p_until timestamptz default null)
returns integer
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_n int;
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  update public.feedback f
     set admin_seen_at = greatest(coalesce(f.admin_seen_at, '-infinity'::timestamptz),
                                  least(coalesce(p_until, now()), now()))
   where f.id = any(coalesce(p_ids, '{}'::uuid[]));
  get diagnostics v_n = row_count;
  return v_n;
end;
$$;

-- ── 7. Grants ─────────────────────────────────────────────────────────────
-- CREATE FUNCTION grants EXECUTE to PUBLIC, and Supabase's default privileges
-- add anon/authenticated on top, so strip every function to nothing first and
-- then grant exactly the callers it is meant for.
revoke all on function public._feedback_tokens(text[])  from public, anon, authenticated;
revoke all on function public._feedback_rate_limit()     from public, anon, authenticated;

revoke all on function public.submit_feedback(text, text, text, text)          from public, anon, authenticated;
revoke all on function public.get_my_feedback(text[])                          from public, anon, authenticated;
revoke all on function public.get_my_feedback_unread(text[])                   from public, anon, authenticated;
revoke all on function public.reply_my_feedback(uuid, text, text[])            from public, anon, authenticated;
revoke all on function public.mark_my_feedback_seen(uuid, timestamptz, text[]) from public, anon, authenticated;
grant execute on function public.submit_feedback(text, text, text, text)          to anon, authenticated;
grant execute on function public.get_my_feedback(text[])                          to anon, authenticated;
grant execute on function public.get_my_feedback_unread(text[])                   to anon, authenticated;
grant execute on function public.reply_my_feedback(uuid, text, text[])            to anon, authenticated;
grant execute on function public.mark_my_feedback_seen(uuid, timestamptz, text[]) to anon, authenticated;

revoke all on function public.get_feedback_threads()                           from public, anon, authenticated;
revoke all on function public.get_feedback_admin_unread()                      from public, anon, authenticated;
revoke all on function public.admin_reply_feedback(uuid, text, boolean)        from public, anon, authenticated;
revoke all on function public.mark_feedback_seen_admin(uuid[], timestamptz)    from public, anon, authenticated;
grant execute on function public.get_feedback_threads()                        to authenticated;
grant execute on function public.get_feedback_admin_unread()                   to authenticated;
grant execute on function public.admin_reply_feedback(uuid, text, boolean)     to authenticated;
grant execute on function public.mark_feedback_seen_admin(uuid[], timestamptz) to authenticated;

notify pgrst, 'reload schema';
