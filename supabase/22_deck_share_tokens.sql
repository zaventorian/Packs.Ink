-- Per-deck share tokens. Closes the unlisted-deck enumeration hole introduced
-- by 18_deck_sharing.sql, where anyone (incl. anon) could pull every unlisted
-- deck via `/decks?visibility=eq.unlisted`. After this migration:
--
--   * Direct reads on `decks` and `deck_cards` are restricted to
--     (owner OR visibility = 'public'). Unlisted is no longer readable
--     via the table API.
--   * Public anon access to unlisted decks goes through a SECURITY DEFINER
--     RPC that requires the deck's share_token. Tokens are 128-bit
--     random strings, effectively unguessable.
--   * Flipping a deck back to Private auto-rotates the share_token via
--     a BEFORE UPDATE trigger — every existing share URL stops working
--     instantly.
--
-- Idempotent on re-run.

-- ── helpers ──────────────────────────────────────────────────────────────
-- Marked VOLATILE so each call returns a distinct value; this matters
-- because we UPDATE every existing row below and want unique tokens.
create or replace function public.gen_share_token()
returns text
language sql
volatile
as $$
  -- 16 random bytes -> 22-char URL-safe base64 (no '+', '/', or padding).
  select replace(replace(replace(encode(gen_random_bytes(16), 'base64'), '+', '-'), '/', '_'), '=', '');
$$;

-- ── decks.share_token column ─────────────────────────────────────────────
-- 1. Add nullable so we can backfill per-row uniquely (a NOT NULL DEFAULT
--    fn() would call the function once and assign the SAME token to every
--    existing row — exactly the opposite of what we want).
alter table public.decks
  add column if not exists share_token text;

-- 2. Per-row backfill on any deck that's missing one.
update public.decks
   set share_token = public.gen_share_token()
 where share_token is null or share_token = '';

-- 3. Tighten the column.
alter table public.decks
  alter column share_token set default public.gen_share_token(),
  alter column share_token set not null;

create index if not exists decks_share_token_idx on public.decks (share_token);

-- ── RLS rewrite ──────────────────────────────────────────────────────────
-- Replace the "owner OR not private" policy from 18_*.sql with a strict
-- "owner OR public" version. Unlisted decks now require the share-token
-- RPC for non-owners.
drop policy if exists "decks: select visible"   on public.decks;
drop policy if exists "decks: select own or public" on public.decks;
create policy "decks: select own or public"
  on public.decks for select
  using (auth.uid() = user_id OR visibility = 'public');

drop policy if exists "deck_cards: select visible"   on public.deck_cards;
drop policy if exists "deck_cards: select own or public" on public.deck_cards;
create policy "deck_cards: select own or public"
  on public.deck_cards for select
  using (exists (
    select 1 from public.decks d
    where d.id = deck_id
      and (d.user_id = auth.uid() OR d.visibility = 'public')
  ));

-- ── token-rotation trigger ───────────────────────────────────────────────
-- Whenever a deck transitions INTO 'private' visibility, rotate the
-- share token so every previously-shared URL dies immediately. Going
-- back out to unlisted/public regenerates trust — that's the user-
-- visible "if you switch to private it updates the link" behavior.
create or replace function public.rotate_share_token_on_private()
returns trigger
language plpgsql
as $$
begin
  if NEW.visibility = 'private'
     and (OLD.visibility is distinct from NEW.visibility) then
    NEW.share_token := public.gen_share_token();
  end if;
  return NEW;
end;
$$;

drop trigger if exists decks_rotate_token_on_private on public.decks;
create trigger decks_rotate_token_on_private
  before update on public.decks
  for each row execute function public.rotate_share_token_on_private();

-- ── share RPCs ───────────────────────────────────────────────────────────
-- Token-gated readers. Anyone (incl. anon) can call these, but they need
-- the token. Returns empty on mismatch or if the deck is private.
create or replace function public.get_shared_deck(p_deck_id uuid, p_token text)
returns table(
  id          uuid,
  user_id     uuid,
  name        text,
  description text,
  inks        text[],
  tags        text[],
  visibility  text,
  updated_at  timestamptz,
  share_token text
)
language sql
security definer
set search_path = public
as $$
  select id, user_id, name, description, inks, tags, visibility, updated_at, share_token
    from public.decks
   where id = p_deck_id
     and share_token = p_token
     and visibility <> 'private';
$$;

create or replace function public.get_shared_deck_cards(p_deck_id uuid, p_token text)
returns table(
  deck_id  uuid,
  card_id  text,
  printing text,
  quantity int
)
language sql
security definer
set search_path = public
as $$
  select dc.deck_id, dc.card_id, dc.printing, dc.quantity
    from public.deck_cards dc
    join public.decks d on d.id = dc.deck_id
   where dc.deck_id = p_deck_id
     and d.share_token = p_token
     and d.visibility <> 'private';
$$;

revoke all on function public.get_shared_deck(uuid, text)       from public;
revoke all on function public.get_shared_deck_cards(uuid, text) from public;
grant  execute on function public.get_shared_deck(uuid, text)       to anon, authenticated;
grant  execute on function public.get_shared_deck_cards(uuid, text) to anon, authenticated;

-- Owner-only RPC to rotate a deck's share token (revokes all in-the-wild
-- URLs without flipping the deck through private). Returns the new token.
create or replace function public.regenerate_deck_share_token(p_deck_id uuid)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_new text;
begin
  v_new := public.gen_share_token();
  update public.decks
     set share_token = v_new
   where id = p_deck_id
     and user_id = auth.uid();
  if not found then
    raise exception 'deck not found or not owned by caller';
  end if;
  return v_new;
end;
$$;

revoke all on function public.regenerate_deck_share_token(uuid) from public;
grant  execute on function public.regenerate_deck_share_token(uuid) to authenticated;

-- ── deck_favorites: capture the token used to favorite an unlisted deck ──
-- Lets the Favorites list re-fetch an unlisted deck later via the RPC
-- without re-typing the URL. If the creator rotates the token (or flips
-- private), the stored token stops matching and the favorite renders
-- as "no longer available" — correct behavior.
alter table public.deck_favorites
  add column if not exists share_token text;

notify pgrst, 'reload schema';
