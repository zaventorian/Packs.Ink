-- 155_calendar_dlc_bangkok_notes.sql — add ticket-tier pricing and the Main
-- Event prizing ladder to the DLC Bangkok calendar_events row's notes.
--
-- Source: a "My Table Side" promotional graphic (2026-09-17), covering the
-- add-on packages and prizing for the same event migration 150 already dated
-- and linked (Oct 31 - Nov 1, sakasakaevent.com). Free text in `notes` — the
-- table has no ticket-tier or prize-ladder columns, and one Bangkok-specific
-- price sheet doesn't earn a schema change.
--
-- ⚠ Two card names on the source graphic were too low-resolution to read with
-- confidence (the second Premium-tier card, and several prize-ladder cards
-- shown only as unlabelled foil art) — described by TIER, not by name, rather
-- than guessing. Ursula (Premium), Gaston and Madam Mim (VIP) were legible.
--
-- Idempotent: matches the same `where title = 'DLC Bangkok'` migration 150
-- used, so a re-run just re-applies the same notes.

update public.calendar_events set
  notes = 'Main event Oct 31 - Nov 1; Friday Oct 30 is early check-in and side events (15:00-20:00). '
    || 'Ticket tiers (My Table Side): Participate 550 HKD / 2,300 THB (foil Ursula). '
    || 'Premium add-on 3,100 HKD / 13,000 THB: 2 foil cards (incl. Ursula), a Challenge playmat, a premium tote bag, a premium foil card. '
    || 'VIP add-on 5,350 HKD / 22,400 THB: 2 foil cards (Gaston, Madam Mim), a VIP pin, a VIP foil card, a backpack. '
    || 'Main Event prizing: Participate/3 wins/Day 2/Top 64/Top 32/Top 16 = a foil card each; Top 8 = uncut sheet; Top 4 = a gold card; Top 2 = full foil set + Enchanted + Epic + Iconic; Champion = World Championship invite.',
  updated_at = now()
where title = 'DLC Bangkok';

notify pgrst, 'reload schema';
