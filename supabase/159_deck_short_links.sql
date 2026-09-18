-- Short deck links: packs.ink/?d=<code> instead of
-- packs.ink/decks?deck=<uuid>&token=<22 chars> (~100 chars -> ~25).
--
-- The code is 12 characters from a lowercase alphabet with the confusable
-- characters removed (no 0 o 1 l i), so it can be read off a printed poster and
-- typed on a phone. 31^12 is about 59 bits: it stands in for an Unlisted
-- deck's secret token, so it has to be unguessable, not just short.
--
-- A code never outlives the deck's current share state. It stores the token
-- it was minted under, and the resolver only answers while that token is
-- still the deck's token (Unlisted) or the deck is Public. Making a deck less
-- visible already rotates its token (rotate_share_token_on_private), which
-- kills every code minted before, with no trigger of our own.
--
-- One code per (deck, token): minting twice returns the same code, so the
-- table is bounded by the number of decks and cannot be spammed full.
--
-- RLS on with no policies; all access goes through the two definer RPCs.

create table if not exists public.deck_short_links (
  code        text primary key,
  deck_id     uuid not null references public.decks(id) on delete cascade,
  share_token text,
  created_at  timestamptz not null default now()
);

create unique index if not exists deck_short_links_deck_token_uidx
  on public.deck_short_links (deck_id, coalesce(share_token, ''));

alter table public.deck_short_links enable row level security;

-- Mint (or return) the code for a deck. The caller must present what a
-- viewer of the deck already has: nothing for a Public deck, the share token
-- for an Unlisted one. Private decks get no code.
create or replace function public.deck_short_code(p_deck_id uuid, p_token text)
returns text
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  d      public.decks%rowtype;
  tok    text;
  v_code    text;
  alpha  constant text := '23456789abcdefghjkmnpqrstuvwxyz';
  bytes  bytea;
  i      int;
begin
  select * into d from public.decks where id = p_deck_id;
  if not found or d.visibility = 'private' then
    raise exception 'deck not shareable';
  end if;
  if d.visibility = 'public' then
    tok := null;
  else
    if p_token is null or p_token <> d.share_token then
      raise exception 'deck not shareable';
    end if;
    tok := d.share_token;
  end if;

  select code into v_code from public.deck_short_links
   where deck_id = p_deck_id and coalesce(share_token, '') = coalesce(tok, '');
  if v_code is not null then return v_code; end if;

  for attempt in 1..5 loop
    bytes := gen_random_bytes(12);
    v_code := '';
    for i in 0..11 loop
      v_code := v_code || substr(alpha, (get_byte(bytes, i) % 31) + 1, 1);
    end loop;
    begin
      insert into public.deck_short_links (code, deck_id, share_token)
      values (v_code, p_deck_id, tok);
      return v_code;
    exception when unique_violation then
      -- Either a code collision (retry) or a concurrent mint for the same
      -- deck (return the winner's code).
      select code into v_code from public.deck_short_links
       where deck_id = p_deck_id and coalesce(share_token, '') = coalesce(tok, '');
      if v_code is not null then return v_code; end if;
    end;
  end loop;
  raise exception 'could not mint a short code';
end;
$$;

-- Resolve a code to what a full link carries. Returns no row when the code is
-- unknown, the deck went Private, or its token has rotated since minting.
create or replace function public.resolve_deck_short_code(p_code text)
returns table(deck_id uuid, share_token text)
language sql
security definer
set search_path = public
as $$
  select d.id,
         case when d.visibility = 'public' then null else d.share_token end
    from public.deck_short_links l
    join public.decks d on d.id = l.deck_id
   where l.code = lower(trim(p_code))
     and (d.visibility = 'public'
          or (d.visibility = 'unlisted' and l.share_token = d.share_token));
$$;

revoke all on function public.deck_short_code(uuid, text)      from public;
revoke all on function public.resolve_deck_short_code(text)    from public;
grant execute on function public.deck_short_code(uuid, text)   to anon, authenticated;
grant execute on function public.resolve_deck_short_code(text) to anon, authenticated;

notify pgrst, 'reload schema';
