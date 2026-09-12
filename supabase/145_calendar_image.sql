-- 145_calendar_image.sql (2026-09-12)
--
-- A per-event image, so the calendar can show what a thing IS rather than a
-- coloured dot.
--
-- Most of it needs no column: a set release and a product drop resolve their own
-- art from sealed_products (a set's Booster Pack photo is the set's art), and
-- those are TCGplayer catalog photos the site already shows on /gear and the
-- Amazon shelf.
--
-- This column is for everything that has no product behind it -- a Challenge, a
-- qualifier, a convention -- and for overriding a bad automatic match. It is the
-- "customise over time" hook: paste a URL in the editor on /calendar and that
-- event uses it, no deploy.
--
-- !! WHAT NOT TO PUT IN IT. Official Disney Lorcana Challenge / championship
-- marks are Disney and Ravensburger trademarks, and the site's footer disclaims
-- any affiliation -- using their event logos is exactly what that disclaimer
-- says we do not do. Art we are entitled to show only. Events with nothing
-- suitable fall back to a drawn glyph, which is ours and themes correctly.
--
-- !! The URL must be on a host the Content-Security-Policy allows, or the browser
-- drops the image with no visible error. Today that means tcgplayer-cdn,
-- cards.lorcast.io, ravensburger.cloud or our own Supabase storage -- see
-- img-src in _headers, and add a host to BOTH copies of the policy if you need
-- a new one.

alter table public.calendar_events add column if not exists image_url text;

notify pgrst, 'reload schema';
