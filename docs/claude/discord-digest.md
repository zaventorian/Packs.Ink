# Discord digest (`scripts/discord_digest.py`, 2026-09-10)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

A daily post to a Discord webhook. **It is not a movers list**, and the reason is the
whole design: the restock services already own *"this is in stock at Walmart for $6.00"*.
**They have gone WIDE, which is exactly why they cannot go deep — and that is the opening.**
TrackaLacker (whose `@LorcanaRestocks` handle is legacy SEO real estate; the account now
reads *"TCG Restocks — Magic, Lorcana, One Piece & More"*) tracks Pokémon, Magic, One Piece,
Lorcana, sports cards, LEGO, PS5, Switch, Xbox and GPUs. A service that also watches
graphics cards is never going to tell a Lorcana player whether $140 is a fair price for
that Enchanted. **What none of them can say is whether $6.00 is a good price.** We hold
daily prices back to 2024-02-08, so the digest leads with the judgement:

- **"Worth a look"** — cards that FELL on the window **and** now sit at a multi-month low.
  A faller merely off its high is noise; a faller at the bottom of its own year is the
  opportunity, and it is the one line in the post nobody else in the space can write.
- **"Heating up"** — the risers, each carrying a caution when it is near its 12-month high.

**⚠ The standing maths MUST match the site.** `priceStanding` in Index.html renders the
same claim next to a buy button, and two implementations of "is this a good price" that
disagree destroys the only thing the claim has going for it. The `STANDING_*` constants in
the script are the same numbers, and **`scripts/test_discord_digest.py` reads them back out
of Index.html** and fails when they drift. Same guard shape as `buildCustomIndex` vs
migration 130 — retuning means a deliberate edit in both places.

- **It reads `market_price`, never `low_price`** (`PRICE_COL`/`PCT_PREFIX`). Low is a
  published aggregate one listing can move, and a digest that calls a sticky Low a bargain
  is exactly the false confidence this feature exists to avoid. `MIN_PRICE = 5.0` for the
  same reason the ticker and Screener default there — a 10-cent common's +300% is not news.
- **DRY RUN BY DEFAULT.** Posting is public and irreversible, so `--post` is the deliberate
  act. Same asymmetry as `flag_intentional_draws.py`.
- **No webhook configured is a clean exit 0**, not a red run — the workflow stays green on a
  fork or before `DISCORD_WEBHOOK_URL` is set.
- **⚠ The freshness gate is what makes duplicate posts impossible.** The ETL fires up to
  three times a day (20:30 / 22:30 / 01:00 retries), so the script refuses to post unless
  the newest `card_prices_latest.price_date` **is today**. A retry therefore cannot re-post
  yesterday's digest, and a day the ETL never landed produces silence rather than a stale
  digest presented as today's. That is also why it is **its own workflow on one cron**
  (21:15 UTC, after the 20:30 ETL) rather than a job chained off `prices` — chaining would
  fire it once per dispatch. `--allow-stale` overrides it for a manual test.
- **The webhook URL is never logged.** It is a bearer credential in a URL: anyone holding it
  can post to that channel as us.
- Discord's embed limits are hard failures, not truncations — 1024 chars per field value,
  25 fields, 6000 total. The test asserts all three against a synthetic worst case.
- **⚠ A mover must have been PRICED inside its window** (2026-09-27). Before migration 172
  the matview reported a SKU's last-ever change as its "1D" move forever, and a dry run led
  "Heating up" with Cruella at +108% off a price 48 days old. The script checks the rule
  again against `prices_daily` itself (`observed_in_window` / `keep_fresh`) rather than
  trusting the matview, because a post cannot be taken back. It over-fetches 3x
  (`OVERFETCH`), drops stale rows, THEN truncates — cut first and a stale row still costs
  a real mover its slot — and logs each skip with its last-priced date. The test reads the
  newest price_movers migration and fails if `WINDOW_DAYS` drifts from its guard, and runs
  `main()` end to end against the pre-172 Cruella row.
- **It has never posted, and its schedule was removed 2026-09-30**: the `DISCORD_WEBHOOK_URL`
  repo secret was never created, so three weeks of daily runs each ended at the clean exit
  above. The workflow is manual-only now; `discord_reports.py` still imports this module.
  To use a plain webhook after all, create the secret and restore the cron (the workflow's
  header says how).

Guarded by `python scripts/test_discord_digest.py` (54 checks), which the workflow runs
BEFORE the digest for the same reason `catalog-watch.yml` tests its ack layer first: a
drifted constant or a blown embed limit fails by posting something wrong, not by failing.
