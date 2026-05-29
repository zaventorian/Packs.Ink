-- Shareable Trade Comparison links. The Trade Compare tool (Analytics tab)
-- serializes a two-sided trade and shares it via a short URL
-- (packs.ink/t/<token>) so the other party can open and review it.
--
-- Why a table instead of stuffing the trade into the URL: the original
-- implementation base64-encoded the whole trade into ?trade=<blob>, which
-- blew past Discord's 2000-char message cap for large trades (~16 cards/side).
-- Persisting the payload here keyed by an unguessable token keeps the link
-- tiny regardless of trade size.
--
-- Access model: RLS is enabled with NO direct policies, so anon/authenticated
-- cannot read or enumerate the table. All access goes through two SECURITY
-- DEFINER RPCs:
--   * create_trade(token, payload) — writes one row. The token is supplied by
--     the client (same 22-char URL-safe scheme as deck share tokens) so the
--     share link can be copied synchronously inside the click gesture.
--   * get_trade(token) — reads the payload back. "Anyone with the link" works
--     because the token is unguessable (~128 bits); without it the row is
--     invisible.
--
-- Idempotent on re-run.

create table if not exists public.trades (
  token       text primary key,
  payload     jsonb not null,
  user_id     uuid references auth.users(id) on delete set null,
  created_at  timestamptz not null default now()
);

create index if not exists trades_created_at_idx on public.trades (created_at);

alter table public.trades enable row level security;
-- Intentionally no policies: every read/write goes through the definer RPCs
-- below. Direct PostgREST access by anon/authenticated is denied.

-- ── create ────────────────────────────────────────────────────────────────
-- Token is client-generated (lets the browser copy the link synchronously in
-- the click handler — clipboard writes after an await are unreliable in
-- Safari). We validate its shape and bound the payload size to limit abuse.
-- A duplicate token (astronomically unlikely at 128 bits) raises a unique
-- violation, which the client surfaces as "try again".
create or replace function public.create_trade(p_token text, p_payload jsonb)
returns text
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_token is null or p_token !~ '^[A-Za-z0-9_-]{16,64}$' then
    raise exception 'invalid token';
  end if;
  if p_payload is null or length(p_payload::text) > 100000 then
    raise exception 'invalid or oversized payload';
  end if;
  insert into public.trades (token, payload, user_id)
  values (p_token, p_payload, auth.uid());
  return p_token;
end;
$$;

revoke all on function public.create_trade(text, jsonb) from public;
grant execute on function public.create_trade(text, jsonb) to anon, authenticated;

-- ── read ──────────────────────────────────────────────────────────────────
create or replace function public.get_trade(p_token text)
returns jsonb
language sql
security definer
set search_path = public
as $$
  select payload from public.trades where token = p_token;
$$;

revoke all on function public.get_trade(text) from public;
grant execute on function public.get_trade(text) to anon, authenticated;

notify pgrst, 'reload schema';
