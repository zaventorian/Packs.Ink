-- 177_inkbox.sql
-- Ink.Box cloud relay: lets a signed-in packs.ink user send print jobs to
-- their Ink.Box (the thermal card printer) from anywhere.
--
-- The box never accepts inbound connections. It holds a device id + a random
-- secret and polls two definer RPCs: one to claim queued jobs (which doubles
-- as its heartbeat), one to report the result. A user binds a box to their
-- account by typing the short pairing code the box prints on a slip.
--
-- Trust model:
--   * device secret  - 256 bits, generated on the box, stored here only as a
--                      SHA-256 hash. Proves "I am that box".
--   * pairing code   - 8 chars, 15-minute life, single use. Proves "I am
--                      standing next to that box" (it came out of the printer).
--   * jobs           - only the device's owner can queue; only the device
--                      (by secret) can claim. Payloads are small JSON
--                      descriptions (card ids + quantities), never files.
--
-- Delivery is at-most-once: a job flips to 'sent' in the statement that
-- hands it to the box, and nothing re-queues it, so a dropped connection can
-- lose a print but never duplicate one. While a job waits or prints, the box
-- lists it as active on every poll; a job the box stops mentioning for 20
-- minutes is marked failed.
--
-- NOT PUBLIC: the whole feature is behind an allow-list (inkbox_testers,
-- email-keyed like scanner_testers). An account that is not on it cannot pair
-- a box, queue a job or see a device, and the /box page shows it nothing.
--
-- Tables have RLS on; anon has no table access at all. Every write goes
-- through the RPCs below.
-- Idempotent; safe to re-run.

-- Who may use Ink.Box at all. Email-keyed so an account can be granted before
-- it has ever signed in. Rows are personal emails and are NOT tracked in the
-- repo; manage them in the SQL editor:
--   insert into public.inkbox_testers (email) values ('...') on conflict do nothing;
create table if not exists public.inkbox_testers (
  email     text primary key,
  note      text,
  added_at  timestamptz not null default now()
);
alter table public.inkbox_testers enable row level security;
revoke all on public.inkbox_testers from anon, authenticated;
grant all on public.inkbox_testers to service_role;

create or replace function public.is_inkbox_user()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.inkbox_testers t
    where lower(t.email) = lower((select u.email from auth.users u where u.id = (select auth.uid())))
  );
$$;

create table if not exists public.inkbox_devices (
  id              uuid primary key,
  secret_hash     text not null,
  name            text not null default 'Ink.Box',
  owner_id        uuid references auth.users(id) on delete cascade,
  pair_code       text,
  pair_expires_at timestamptz,
  status          jsonb not null default '{}'::jsonb,
  last_seen_at    timestamptz,
  created_at      timestamptz not null default now()
);

create unique index if not exists inkbox_devices_pair_code_uidx
  on public.inkbox_devices (pair_code) where pair_code is not null;
create index if not exists inkbox_devices_owner_idx
  on public.inkbox_devices (owner_id);

create table if not exists public.inkbox_jobs (
  id         uuid primary key default gen_random_uuid(),
  device_id  uuid not null references public.inkbox_devices(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  payload    jsonb not null,
  status     text not null default 'queued'
             check (status in ('queued','sent','printing','done','error','canceled')),
  message    text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint inkbox_jobs_payload_size check (pg_column_size(payload) <= 262144)
);

create index if not exists inkbox_jobs_device_queue_idx
  on public.inkbox_jobs (device_id, status, created_at);
create index if not exists inkbox_jobs_user_idx
  on public.inkbox_jobs (user_id, created_at desc);

alter table public.inkbox_devices enable row level security;
alter table public.inkbox_jobs    enable row level security;

-- Owners see their own boxes and jobs. No INSERT/UPDATE policies on purpose:
-- those paths are the RPCs. secret_hash and pair_code are kept out of reach
-- with column-level grants, so "select *" by an owner still can't read them.
drop policy if exists inkbox_devices_owner_select on public.inkbox_devices;
create policy inkbox_devices_owner_select on public.inkbox_devices
  for select to authenticated
  using (owner_id = (select auth.uid()) and (select public.is_inkbox_user()));

drop policy if exists inkbox_devices_owner_delete on public.inkbox_devices;
create policy inkbox_devices_owner_delete on public.inkbox_devices
  for delete to authenticated
  using (owner_id = (select auth.uid()));

drop policy if exists inkbox_jobs_owner_select on public.inkbox_jobs;
create policy inkbox_jobs_owner_select on public.inkbox_jobs
  for select to authenticated
  using (user_id = (select auth.uid()) and (select public.is_inkbox_user()));

drop policy if exists inkbox_jobs_owner_delete on public.inkbox_jobs;
create policy inkbox_jobs_owner_delete on public.inkbox_jobs
  for delete to authenticated
  using (user_id = (select auth.uid()));

revoke all on public.inkbox_devices from anon, authenticated;
revoke all on public.inkbox_jobs    from anon, authenticated;
grant select (id, name, owner_id, status, last_seen_at, created_at)
  on public.inkbox_devices to authenticated;
grant delete on public.inkbox_devices to authenticated;
grant select, delete on public.inkbox_jobs to authenticated;
grant all on public.inkbox_devices to service_role;
grant all on public.inkbox_jobs    to service_role;

-- ── Box side (anon + device secret) ─────────────────────────────────────────

create or replace function public.inkbox_secret_hash(p_secret text)
returns text
language sql
immutable
set search_path = public
as $$
  select encode(sha256(convert_to(p_secret, 'UTF8')), 'hex');
$$;

-- Announce a box and get a fresh pairing code. A new device id creates the
-- row; a known one must present its secret. Re-registering an already-owned
-- box only issues a new code - the owner changes when someone claims it.
create or replace function public.inkbox_register_device(p_device_id uuid, p_secret text, p_name text)
returns text
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  d       public.inkbox_devices%rowtype;
  alpha   constant text := '23456789ABCDEFGHJKMNPQRSTUVWXYZ';
  bytes   bytea;
  v_code  text;
  i       int;
begin
  if p_device_id is null or p_secret is null or length(p_secret) < 32 then
    raise exception 'invalid device credentials';
  end if;

  select * into d from public.inkbox_devices where id = p_device_id;
  if found then
    if d.secret_hash <> public.inkbox_secret_hash(p_secret) then
      raise exception 'invalid device credentials';
    end if;
  else
    -- Unclaimed rows are the only thing an anonymous caller can create, so
    -- bound them: sweep stale ones, and refuse to grow past a sane backlog.
    delete from public.inkbox_devices
     where owner_id is null and created_at < now() - interval '1 day';
    if (select count(*) from public.inkbox_devices
         where owner_id is null and created_at > now() - interval '1 hour') >= 100 then
      raise exception 'too many new devices right now; try again in an hour';
    end if;
    insert into public.inkbox_devices (id, secret_hash, name)
    values (p_device_id, public.inkbox_secret_hash(p_secret),
            left(coalesce(nullif(trim(p_name), ''), 'Ink.Box'), 40));
  end if;

  for attempt in 1..5 loop
    bytes := gen_random_bytes(8);
    v_code := '';
    for i in 0..7 loop
      v_code := v_code || substr(alpha, (get_byte(bytes, i) % 31) + 1, 1);
    end loop;
    begin
      update public.inkbox_devices
         set pair_code = v_code, pair_expires_at = now() + interval '15 minutes'
       where id = p_device_id;
      return v_code;
    exception when unique_violation then
      null;  -- code collision with another box mid-pairing: draw again
    end;
  end loop;
  raise exception 'could not mint a pairing code';
end;
$$;

-- Heartbeat + fetch work. Returns
--   {"paired": bool, "jobs": [{"id","payload"}], "cancel": [job ids]}.
-- Claimed jobs move to 'sent' in the same statement, so two polls can't
-- hand out the same job. p_status may carry "active": [job ids the box still
-- holds]; "cancel" lists jobs the owner cancelled after the box took them.
create or replace function public.inkbox_claim_jobs(p_device_id uuid, p_secret text, p_status jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  d        public.inkbox_devices%rowtype;
  v_status jsonb := coalesce(p_status, '{}'::jsonb);
  v_active uuid[] := '{}';
  v_jobs   jsonb;
  v_cancel jsonb;
begin
  select * into d from public.inkbox_devices where id = p_device_id;
  if not found or d.secret_hash <> public.inkbox_secret_hash(coalesce(p_secret, '')) then
    raise exception 'invalid device credentials';
  end if;
  if pg_column_size(v_status) > 8192 or jsonb_typeof(v_status) <> 'object' then
    v_status := '{}'::jsonb;
  end if;

  update public.inkbox_devices
     set last_seen_at = now(), status = v_status - 'active'
   where id = p_device_id;

  -- Jobs the box says it still holds stay alive however long its queue is.
  if jsonb_typeof(v_status -> 'active') = 'array' then
    select coalesce(array_agg(x::uuid), '{}') into v_active
      from jsonb_array_elements_text(v_status -> 'active') as t(x)
     where x ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
    update public.inkbox_jobs
       set updated_at = now()
     where device_id = p_device_id and status in ('sent','printing') and id = any(v_active);
  end if;

  -- A job handed to a box that then lost power is never mentioned again.
  update public.inkbox_jobs
     set status = 'error', message = 'The box restarted before this finished.', updated_at = now()
   where device_id = p_device_id and status in ('sent','printing')
     and updated_at < now() - interval '20 minutes';
  -- Nobody wants this morning's queue printing the moment a box is plugged in.
  update public.inkbox_jobs
     set status = 'canceled', message = 'Expired before the box came online.', updated_at = now()
   where device_id = p_device_id and status = 'queued'
     and created_at < now() - interval '3 hours';
  delete from public.inkbox_jobs
   where device_id = p_device_id and created_at < now() - interval '30 days';

  if d.owner_id is null or not exists (
       select 1 from public.inkbox_testers t
        where lower(t.email) = lower((select u.email from auth.users u where u.id = d.owner_id))) then
    return jsonb_build_object('paired', false, 'jobs', '[]'::jsonb, 'cancel', '[]'::jsonb);
  end if;

  -- Cancellations the box may still be able to act on (it stops between cards).
  select coalesce(jsonb_agg(id), '[]'::jsonb) into v_cancel
    from public.inkbox_jobs
   where device_id = p_device_id and status = 'canceled' and id = any(v_active);

  with next as (
    select id from public.inkbox_jobs
     where device_id = p_device_id and status = 'queued'
     order by created_at
     limit 5
     for update skip locked
  ), claimed as (
    update public.inkbox_jobs j
       set status = 'sent', updated_at = now()
      from next
     where j.id = next.id
    returning j.id, j.payload, j.created_at
  )
  select coalesce(jsonb_agg(jsonb_build_object('id', id, 'payload', payload) order by created_at), '[]'::jsonb)
    into v_jobs from claimed;

  return jsonb_build_object('paired', true, 'jobs', v_jobs, 'cancel', v_cancel);
end;
$$;

create or replace function public.inkbox_finish_job(p_device_id uuid, p_secret text, p_job_id uuid, p_status text, p_message text default null)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_status not in ('printing','done','error','canceled') then
    raise exception 'invalid status';
  end if;
  if not exists (select 1 from public.inkbox_devices
                  where id = p_device_id
                    and secret_hash = public.inkbox_secret_hash(coalesce(p_secret, ''))) then
    raise exception 'invalid device credentials';
  end if;
  update public.inkbox_jobs
     set status = p_status, message = left(p_message, 300), updated_at = now()
   where id = p_job_id and device_id = p_device_id and status in ('sent','printing');
end;
$$;

-- ── User side (signed in) ───────────────────────────────────────────────────

-- Claim the box whose slip shows this code. Returns the device id + name.
create or replace function public.inkbox_pair_device(p_code text)
returns table(device_id uuid, device_name text)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid  uuid := (select auth.uid());
  v_code text := upper(regexp_replace(coalesce(p_code, ''), '[^A-Za-z0-9]', '', 'g'));
  v_id   uuid;
begin
  if v_uid is null then
    raise exception 'sign in to pair an Ink.Box';
  end if;
  if not public.is_inkbox_user() then
    raise exception 'Ink.Box is not available on this account.';
  end if;
  select id into v_id from public.inkbox_devices
   where pair_code = v_code and pair_expires_at > now()
   for update;
  if v_id is null then
    raise exception 'That pairing code is wrong or has expired. Print a new one from the box.';
  end if;
  -- A box changing hands shouldn't print the previous owner's leftovers.
  delete from public.inkbox_jobs j
   where j.device_id = v_id and j.status = 'queued' and j.user_id <> v_uid;
  update public.inkbox_devices
     set owner_id = v_uid, pair_code = null, pair_expires_at = null
   where id = v_id;
  return query select i.id, i.name from public.inkbox_devices i where i.id = v_id;
end;
$$;

create or replace function public.inkbox_rename_device(p_device_id uuid, p_name text)
returns void
language sql
security definer
set search_path = public
as $$
  update public.inkbox_devices
     set name = left(coalesce(nullif(trim(p_name), ''), 'Ink.Box'), 40)
   where id = p_device_id and owner_id = (select auth.uid());
$$;

-- Queue a job for a box the caller owns. Capped so a stuck client (or a
-- stolen session) can't bury the printer in paper.
create or replace function public.inkbox_send_job(p_device_id uuid, p_payload jsonb)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid uuid := (select auth.uid());
  v_id  uuid;
begin
  if v_uid is null then
    raise exception 'sign in to print';
  end if;
  if not public.is_inkbox_user() then
    raise exception 'Ink.Box is not available on this account.';
  end if;
  if not exists (select 1 from public.inkbox_devices where id = p_device_id and owner_id = v_uid) then
    raise exception 'That Ink.Box is not paired with your account.';
  end if;
  if p_payload is null or jsonb_typeof(p_payload) <> 'object' or not (p_payload ? 'type') then
    raise exception 'invalid job';
  end if;
  if pg_column_size(p_payload) > 262144 then
    raise exception 'That job is too large to send through the cloud.';
  end if;
  if (select count(*) from public.inkbox_jobs
       where device_id = p_device_id and status in ('queued','sent','printing')) >= 25 then
    raise exception 'That Ink.Box already has a full queue. Let it catch up first.';
  end if;
  if (select count(*) from public.inkbox_jobs
       where user_id = v_uid and created_at > now() - interval '1 hour') >= 200 then
    raise exception 'That is a lot of printing. Give it an hour.';
  end if;
  -- Keep only the 40 most recent finished jobs per box, so a send/cancel loop
  -- can't pile up rows.
  delete from public.inkbox_jobs
   where id in (select id from public.inkbox_jobs
                 where device_id = p_device_id and status in ('done','error','canceled')
                 order by created_at desc offset 40);
  insert into public.inkbox_jobs (device_id, user_id, payload)
  values (p_device_id, v_uid, p_payload)
  returning id into v_id;
  return v_id;
end;
$$;

create or replace function public.inkbox_cancel_job(p_job_id uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_hit int;
begin
  -- A queued job simply never leaves. One the box already took is flagged
  -- here and the box is told on its next poll; it stops before the next card.
  update public.inkbox_jobs
     set status = 'canceled', message = 'Canceled from the app.', updated_at = now()
   where id = p_job_id and user_id = (select auth.uid()) and status in ('queued','sent','printing');
  get diagnostics v_hit = row_count;
  return v_hit > 0;
end;
$$;

-- Supabase's default privileges grant EXECUTE on new functions to anon and
-- authenticated by name, so revoking from PUBLIC alone would leave those in place.
revoke all on function public.is_inkbox_user()                                  from public, anon, authenticated;
revoke all on function public.inkbox_secret_hash(text)                          from public, anon, authenticated;
revoke all on function public.inkbox_register_device(uuid, text, text)          from public, anon, authenticated;
revoke all on function public.inkbox_claim_jobs(uuid, text, jsonb)              from public, anon, authenticated;
revoke all on function public.inkbox_finish_job(uuid, text, uuid, text, text)   from public, anon, authenticated;
revoke all on function public.inkbox_pair_device(text)                          from public, anon, authenticated;
revoke all on function public.inkbox_rename_device(uuid, text)                  from public, anon, authenticated;
revoke all on function public.inkbox_send_job(uuid, jsonb)                      from public, anon, authenticated;
revoke all on function public.inkbox_cancel_job(uuid)                           from public, anon, authenticated;

-- The box is not a signed-in user: it calls with the publishable key.
grant execute on function public.inkbox_register_device(uuid, text, text)        to anon, authenticated;
grant execute on function public.inkbox_claim_jobs(uuid, text, jsonb)            to anon, authenticated;
grant execute on function public.inkbox_finish_job(uuid, text, uuid, text, text) to anon, authenticated;
grant execute on function public.is_inkbox_user()                                to anon, authenticated;
grant execute on function public.inkbox_pair_device(text)                        to authenticated;
grant execute on function public.inkbox_rename_device(uuid, text)                to authenticated;
grant execute on function public.inkbox_send_job(uuid, jsonb)                    to authenticated;
grant execute on function public.inkbox_cancel_job(uuid)                         to authenticated;

notify pgrst, 'reload schema';
