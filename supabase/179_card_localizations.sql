-- 179: card_localizations - one card's name, text and art in another language.
--
-- Filled by scripts/sync_intl_cards.py from the publishers' own card lists:
-- Ravensburger's gallery (de / fr / it) and Takara Tomy's (ja). Read by the
-- site's language setting. Additive only; nothing reads it until the client
-- ships, and the client treats a missing table as "English only".
--
-- One row per (card, language). image_url is NULL on a 'name' match: every
-- printing of a card shares its translated NAME, but only the printing that
-- was actually printed in that language may show foreign art.

create table if not exists public.card_localizations (
  card_id          text not null references public.cards(id) on delete cascade,
  lang             text not null check (lang ~ '^[a-z]{2}(-[a-z]{2,4})?$'),
  name             text,
  version          text,
  text             text,
  flavor_text      text,
  classifications  text[],
  image_url        text,
  image_thumb_url  text,
  source           text not null,
  source_id        text,
  source_ref       text,
  match_how        text not null,
  updated_at       timestamptz not null default now(),
  primary key (card_id, lang)
);

create index if not exists card_localizations_lang_idx on public.card_localizations (lang);

alter table public.card_localizations enable row level security;

drop policy if exists card_localizations_read on public.card_localizations;
create policy card_localizations_read on public.card_localizations
  for select to anon, authenticated using (true);

grant select on public.card_localizations to anon, authenticated;
grant select, insert, update, delete on public.card_localizations to service_role;

notify pgrst, 'reload schema';
