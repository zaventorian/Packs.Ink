-- Add youtube_url column to decks for optional video embed.
--
-- The decks table already has `description` (free-form notes); youtube_url
-- is a parallel optional field for creators who include a deck-profile
-- video. When set we render an embedded iframe alongside the notes; when
-- blank both fields are hidden so non-curating users see no clutter.
--
-- No constraint on URL format — UI does best-effort extraction of the
-- video id and falls back to a plain link if it can't be parsed.
--
-- Idempotent.

alter table public.decks
  add column if not exists youtube_url text;

notify pgrst, 'reload schema';
