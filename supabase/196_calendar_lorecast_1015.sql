-- 196_calendar_lorecast_1015.sql (2026-10-15) — the 2026-10-15 Lorecast / Organized Play slides.
--
-- Source: the Lorecast's "Challenge Update" (London, Melbourne, Ink Pair
-- Prizing) and "World Championship Update" (format, Super Sealed) slides.
--
-- 1. DLC London (Nov 13-15 2026): the two Villain Challenges (Gaston Sat Nov 14,
--    Ursula Sun Nov 15), their prizing, and Ink Pair Prizing. The Youth Division
--    policy that migration 174 wrote is kept, condensed, because `notes` is
--    capped at 1000 characters. The Villain Challenges are inside the existing
--    Nov 13-15 row, so they are NOT separate rows (side events stay off the
--    calendar).
--
-- 2. DLC Tampa (Dec 18-20 2026): the same Ink Pair Prizing test, appended to the
--    notes migration 195 wrote.
--
-- 3. World Championship 2026 (Dec 4-6, Aulani, Ko Olina HI) was NEVER on the
--    calendar; the Sept 17 news article carries the dates and venue but no
--    row was ever made. Added as kind='dlc' (the kind that covers the
--    Continental and World Championships) with the three-format structure from
--    today's slide. Dates and venue come from our own published article, not
--    from today's slide, which names neither.
--
-- 4. DLC Melbourne MOVED: Feb 26-28 -> Mar 5-7 2027, now at Pullman Melbourne Albert Park
--    (organiser statement on the slide). The coordinates are the hotel's
--    street address (65 Queens Rd), approximate to a few hundred metres, not
--    read off the slide. The Melbourne CCQ row (Feb 26) is left alone: the
--    slide does not mention it.
--
-- The Premium ($350) and VIP ($800) packages are in the news draft only: the
-- slides do not say which Challenges they apply to.
--
-- Prize items are NOT products here: the Gaston / Ursula playmats and the
-- non-foil Gaston, Ursula and Mickey promos have no release date, no TCGplayer
-- listing and, for the cards, no printed collector number we could read.
--
-- Idempotent: fixed ids, notes are full literals.

update public.calendar_events set
  notes      = 'Villain Challenges (Core Constructed, 2,400 players, 6 rounds of Swiss): Gaston Sat Nov 14, Ursula Sun Nov 15. Round 2: a Seasonal Promo Card for everyone; 3,000 prize tickets per win, 1,000 per loss; 5+ wins = non-foil Gaston - Superior Archer / Ursula - Deceiver; 6 wins = that villain''s playmat. Ink Pair Prizing at the Friday and Saturday Main Events: top finish for each of 15 ink pairs (single-ink decks ineligible) wins a non-foil Mickey Mouse - Brave Little Prince promo. Side events: on demand Format Coconut, Pack Rush, Booster Draft (4 Hyperia City packs); scheduled Core, Infinity, Super Sealed, Full Box Sealed, Team Up Trios, Madam Mim - Resourceful Trickster Pin Event. Youth Division: tickets include one free guardian badge; youth and guardian may play the Friday Main Event together, but if either reaches Day 2 and the youth is in a Youth Division event, they must choose one. Anyone 17 or under needs a guardian in the venue. Full policies on the DLC London ticket page.',
  updated_at = now()
where id = 'de8a8438-43e7-521b-a37f-bffe590f9268';  -- DLC London

update public.calendar_events set
  notes      = 'Format: Core Constructed. Badges for the Main Event, Youth Division and Attendee go on sale October 19, 2026 at 12:00pm ET: Main Events $85, Attendee $35, Youth Division $50. Premium and VIP add-ons and side events (including CCQ) will be announced later. Main Event and Youth Division structure is on the organiser''s Tampa page (Pastimes Events). Ink Pair Prizing is also tested at Tampa''s Friday and Saturday Main Events: the highest finish for each of the 15 ink pairs (30 winners; single-ink decks ineligible) gets a non-foil Mickey Mouse - Brave Little Prince promo. Announced on the October 15, 2026 Lorecast.',
  updated_at = now()
where id = 'c64532d8-3150-5211-b23f-712774b61d5f';  -- DLC Tampa

insert into public.calendar_events
  (id, kind, title, subtitle, starts_on, ends_on, location, country, latitude, longitude, source, confirmed, notes)
values
  ('57ccbec5-47c6-5087-97d0-e084a634b411', 'dlc', 'World Championship 2026', 'Disney Lorcana Challenge',
   date '2026-12-04', date '2026-12-06',
   'Aulani, A Disney Resort & Spa · Ko Olina, HI', 'US', 21.3367, -158.1285,
   'manual', true,
   'Three formats over three days. Friday: 3 rounds of Swiss Super Sealed, then 4 rounds of Core Constructed. Saturday: 4 rounds of Swiss Infinity Constructed, then a Core Constructed Top 8 single elimination. Sunday Grand Finals: best-of-three matches, Match 1 Super Sealed, Match 2 Core Constructed, Match 3 (if necessary) Infinity Constructed, each Bo3. Super Sealed: 6 packs each of Wilds Unknown, Attack of the Vine! and Hyperia City are provided on site; 60 minutes to build a 50-card deck restricted to three ink colors (dual-ink cards only within those colors); sideboarding between games is allowed, including changing colors, but you revert to the submitted deck after each round. Promo: Minnie Mouse - Amethyst Champion (LCP C2 #20). Format from the October 15, 2026 Lorecast; dates and venue from the September 17 Challenge season update.')
on conflict (id) do update set
  title = excluded.title, subtitle = excluded.subtitle, starts_on = excluded.starts_on,
  ends_on = excluded.ends_on, location = excluded.location, country = excluded.country,
  latitude = excluded.latitude, longitude = excluded.longitude, notes = excluded.notes,
  updated_at = now();

update public.calendar_events set
  starts_on  = date '2027-03-05',
  ends_on    = date '2027-03-07',
  location   = 'Pullman Melbourne Albert Park · Melbourne, Australia',
  latitude   = -37.8437,
  longitude  = 144.9773,
  source     = 'official-2026-27',
  notes      = 'Date and venue change announced on the October 15, 2026 Lorecast, after consultation with Modern Brands and TAK Games: now March 5-7, 2027 at Pullman Melbourne Albert Park (the season page had February 26-28). Special guest: Steve Warner, co-creator of Disney Lorcana TCG, in his first appearance in the Oceania region. Youth Division events will take place.',
  updated_at = now()
where id = 'e4c27703-447b-5f0a-a6ed-9b9cfea8bcf7';  -- DLC Melbourne

notify pgrst, 'reload schema';
