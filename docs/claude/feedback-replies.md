# Feedback replies (migration 138)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

The footer feedback box was one-way. Now every submission is the first message of a
conversation: an admin replies from the inbox, the sender reads it the next time they open the
box, and can follow up in the same thread. `FeedbackModal` / `FeedbackAdminModal` sit above
`Footer` in Index.html. Guarded by `node scripts/test_feedback_threads.mjs`, which also checks
the migration against the client (every RPC defined, every grant on the declared signature).

- **A signed-in thread is keyed on the account; an anonymous one on `reply_token`**, a 128-bit
  secret the browser mints with `genTradeToken` and keeps in
  `localStorage["packsink:feedback:tokens"]`. It travels in request BODIES only, never a URL,
  and it is the only thing that can carry a reply back to someone who never signed in. Notes
  sent anonymously before 138 have neither, so the inbox hides Reply on them
  (`reachable: false`) rather than letting a reply go nowhere.
- **⚠ `packsink:feedback:` must never match `AUX_EVICTABLE_PREFIXES`.** A wiped token strands an
  anonymous sender's conversation with no error anywhere. The test pins it.
- **Unread is timestamps, both ways**: `last_user_at` / `last_admin_at` (newest message per
  side) against `user_seen_at` / `admin_seen_at`. **Marking seen takes the timestamp the reader
  actually saw (`p_until`), clamped to now()** — a reply that lands between loading a thread and
  marking it read has to stay unread.
- **Three surfaces for one fact**: the badge on the footer's Send feedback button (the literal
  ask), the badge on the admin's Feedback inbox button, and a corner notice
  (`.feedback-reply-notice`). The notice exists because the footer is below the fold on every
  long page, and a badge nobody scrolls to is not a notification. It dismisses PER REPLY
  (`packsink:feedback:noticeDismissed` holds the newest reply's time), so reading one of two
  replies can't resurrect it for the other. z-index 50: under the Lore Tracker board (60) and
  every modal, over the deck editor's docked bars.
- **App asks for one cheap count** (`get_my_feedback_unread`, plus `get_feedback_admin_unread`
  for admins) on sign-in change, on return to the tab (at most every 30s), **every 2 minutes
  while the tab is visible** (`FEEDBACK_POLL_MS`), and when either box closes — and **not at
  all for an anonymous visitor holding no tokens**, which is almost everyone. ⚠ The poll is
  the fix for "an admin replied and the user never saw a badge" (2026-09-23): asking only on
  load and on a 5-minute-throttled return meant someone with the site already open never
  learned a reply had landed until they reloaded. After a `feedbackThreadsUnavailable` error it stops asking for the session.
- **Opening the box lands on the newest unread thread**; the badge or the notice is why it was
  opened. Opening a thread marks it read.
- **A follow-up reopens a resolved thread** and spends from the same limits as a new note
  (`_feedback_rate_limit()`: 10 an hour per account or address, then the per-pool backstop of
  migration 190 — see `docs/claude/trade-comparison-tool.md`, which shares the scheme).
- **The inbox marks sender activity seen when it LOADS**, up to the newest activity that load
  returned; the "New" chips stay up for that visit. An admin reply never touches
  `admin_seen_at` (a follow-up typed meanwhile hasn't been seen), and an admin's own
  submissions arrive already seen.
- **Pre-138 databases degrade to the old one-way box** via `feedbackThreadsUnavailable`
  (PGRST202 / 42883 / 42P01 / 42703). An anonymous send retries without `p_reply_token` on that
  error and stores no token. Safe to ship the client first.
- `submit_feedback` gained a 4th parameter, so 138 DROPS the 3-argument version first — two
  overloads make PostgREST's resolution ambiguous. The new one defaults the token to null, so a
  client that never sends it still works.
- `feedback_messages` is RLS-on with no policies (definer-only, like `feedback`). `service_role`
  gets SELECT so the scripts that work the queue can read follow-ups; the original note stays in
  `feedback.comment` where they already read it.
- **No email and no push.** A reply reaches someone only when they come back to the site. Say
  "shows up in your feedback box", never "we'll notify you" — same honesty rule as price alerts.
