# Set conventions

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

- **`MAINLINE_SETS`** = booster-pack sets (TFC → Attack of the Vines). Used by EV, Pack Sim, Box Sim, Playset Cost, Price Graphing, Card Averages, Heatmap, Home "newest set".
- **`SET_ORDER`** = `[EXTRAS_SET_NAME, "Promo Set 1/2/3", ...MAINLINE_SETS]`. `reverse()` puts mainlines on top.
- **`MAINLINE_RELEASE_ORDER`** = `MAINLINE_SETS` minus unreleased. Drives Core Constructed rotation.
- Decks pick up format automatically (`checkDeckLegality`): core-legal sets → "Core Constructed"; structurally legal → "Infinity"; otherwise → "Invalid Deck".
- **`TCGCSV_GROUP_SET_ALIASES` (`scripts/tcgcsv_common.py`) is how a TCGplayer group binds to a Lorcast set when their names don't match.** Both `etl_tcgcsv_daily.update_set_group_mapping` (writes `sets.tcgplayer_group_id`) and `load_sealed_products.build_group_to_setid` (writes `sealed_products.set_id`) resolve through `group_name_candidates()`, which tries the alias, then the literal group name, then the post-colon form ("Disney Lorcana: Fabled" → "Fabled"). An unmatched group is quietly expensive: `link_preorder_pids.py` only walks sets that HAVE a `tcgplayer_group_id`, so that set's new cards never get a pid linked and stay priceless/invisible until Lorcast fills `tcgplayer_id` itself. Seeded with `"d23 promos" → "D23 Collection"` — TCGplayer files every D23 drop (2024 #1-9, 2026 #10-15, both years' sealed collection SKUs) under one "D23 Promos" group. Add an entry whenever a new promo group appears under a name that isn't the set's.
- **Check one product with `python scripts/reconcile_catalog.py --pid <id>`** — reports it across TCGCSV / `cards` / `sealed_products` / `prices_daily` and exits 1 if it's in neither catalog table.

### Catalog watch — the thing that tells you a new set exists

`.github/workflows/catalog-watch.yml`, daily at 03:30 UTC (after the ETL window), running `python scripts/reconcile_catalog.py --watch`. It answers "is there anything Lorcana out there we don't know about?" across six checks:

| kind | what it catches |
|---|---|
| `missing_single` | TCGplayer sells a card, it's in neither `cards` nor `sealed_products` |
| `missing_sealed` | same for a sealed SKU |
| `unbound_group` | a TCGCSV group no `sets.tcgplayer_group_id` points at — **how a new set announces itself, weeks before a card of it is listed** |
| `sealed_no_set` | sealed row loaded with `set_id` null → renders under "Other / Promo" |
| `card_no_pid` | `cards.tcgplayer_product_id` null → `card_prices_latest` is an INNER JOIN, so that card can never show a price |
| `missing_set` | Lorcast published a set id we've never seen — **not the same as a set we don't have**, see below |
| `review_due` | a **scheduled review** came due — see below |
| `pop_stale` | **PSA population data is over a week old** — see below |
| `scrape_stale` | **a feed refreshed from Zaven's own machine has gone quiet** (2026-09-30): `graded_sales` with nothing scraped for 3 days, or no tournament newer than 14 days. `STALE_FEEDS` in `reconcile_catalog.py`; the key carries the date, like `pop_stale` |

**⚠ A red run cannot get redder, so new findings are called out separately (2026-09-30).** The watch sat red from 9/24 to 9/30 on the same twelve findings, and a thirteenth would have sent the identical failure email. Each run now restores the previous run's report from `actions/cache` (`--prev`), prints a "NEW since the last run" block, rewrites the body of ONE tracking issue ("Catalog watch: open findings") with the whole open list, and **comments on it only when something is new** — GitHub emails that comment, with the finding's name in it. No previous report (first run, evicted cache) means nothing is called new. The calendar watch is its own job in the same workflow, so a red catalog job no longer hides it.

### ⚠ `missing_set` is an ID test, and a set id is not a set (2026-09-13)

When Lorcast is late to a promo set we mint our own id and build the cards by hand —
migration 107's **`set_curators_cc1`**, whose six singles ship as `REPRINT_PROMOS`. The day
Lorcast finally indexes that set it arrives under *its* id, which we have never seen, so the
check calls a set we already own "missing". That is survivable. What was not: the hint said
**"run `scripts/load_lorcast.py` to create the set + its cards"**, and `load_lorcast` upserts
`sets` **`on_conflict="id"`** — so following it would have added a SECOND row for one physical
set, reloaded its six cards under the new id, given every Curator's card two tiles, and left the
collection refs migration 107 deliberately repointed sitting on the orphan side. An alert whose
remedy is the damage.

- **The sweep now matches the `code` too** (it didn't even `select` it before) and, on a hit,
  says *we already hold this as `<id>`, do NOT run load_lorcast* — naming the real decision,
  which is whether to converge onto Lorcast's id or keep ours.
- **It still REPORTS, it does not suppress.** This check is how a genuinely new set announces
  itself; silencing on a code match would trade a bad hint for a blind spot. Both directions are
  pinned in `test_catalog_watch.py`, which stubs the network and runs the real `collect_findings`.
- **Settled 2026-09-30: we keep `set_curators_cc1`** and do not converge onto Lorcast's id (acked
  with no expiry). History: it was acked to **2026-09-28**, the `promo-printing-policy` review — all six CC1
  cards are already in that review's scope, so "do promo printings get a tile" and "which set id
  do they hang off" get settled in one sitting rather than two.

### Source watch: the sites we research from (2026-09-30)

`scripts/watch_sources.py`, the `sources` job in `catalog-watch.yml`. Written 2026-09-14 on a
branch that never merged; landed 2026-09-30 with its baseline refreshed. It reads the public
pages we otherwise check by hand and diffs each against `scripts/source_watch.json`:

| source | what a change means |
|---|---|
| `lp-pins` / `lp-counters` | lorcanaplayer's product sitemaps, compared against `LORCANA_PINS` / `LORCANA_LORE_COUNTERS`: a pin or counter we do not hold |
| `lp-products` / `lp-sets` | a product or set slug that site has never listed before |
| `ja-products` | Takara Tomy's card search: a Japanese product's card count moved (`ja_core_numbers.py --check` says what) |
| `official-gallery` | cards.disneylorcana.com's per-set counts: a new `EN n` bucket is spoiler season starting (`import_official_set.py`) |
| `duels-renders` | duels.ink's count of clean reveal renders and of placeholders: better art exists for a stand-in (`import_duels_art.py`) |

- **A source that reads ZERO items is an error, not "nothing new"** (`source_empty`, `shrank`): a
  redesign, a moved URL and a bot wall all produce an empty list, and an empty list diffs clean.
- It never writes to the site's data. Act on a finding, `--ack KEY --why "..."` it, or
  `--baseline` to accept what the sources read now (then commit the JSON).
- **Not yet proven from a GitHub runner.** It was verified from a residential IP; lorcanaplayer is
  Cloudflare-fronted and may refuse a datacenter address, which would show as `source_error` on
  every run. If that happens, move the job to the desktop's daily scheduled task rather than
  ack it.
- The Japan Core half of that branch (new `JAPAN_CORE_*` consts in Index.html) was NOT merged;
  `ja_core_numbers.py` came across as a script only.
- Guarded by `python scripts/test_watch_sources.py` (stubbed fetches).

**It is its own workflow, not an ETL job, deliberately.** ETL red = prices are broken, act now. Catalog watch red = something new exists, decide what to do with it. Sharing one light teaches you to ignore both. It also stopped firing 3–4x a day (once per prices dispatch) to answer a question that changes daily at most.

**Red means something NEW.** Everything already ruled on lives in `scripts/catalog_watch.json`:
- `acks` — one exact `kind:id`, with a `why` and an optional `until` date that **expires the ack and re-alerts**. That's how "revisit when Q3 ships" is expressed as a mechanism instead of a promise someone has to remember.
- `rules` — a regex over the finding name, scoped to a kind, for a whole class we don't model (puzzle inserts, Lore Cards, Case File Cards). A new member of the class never re-alerts.

Acknowledge from the CLI, don't hand-edit: `python scripts/reconcile_catalog.py --ack missing_single:711520 --why "…" [--until YYYY-MM-DD]`. `--why` is mandatory — the file is a decision record, and an entry with no reason can't be told apart from sweeping something under the rug. Commit the file so CI sees it.

**Why any of this exists:** the old `reconcile` job ran green every single day with **18 genuinely missing singles in its output**, because it exited 0, `RECONCILE_ALERT_WEBHOOK` was never set, and its report went to a Step Summary nobody opens. An alert with no delivery is not an alert. The other half was coverage — it only looked at pids with a recent PRICE, so a product listed before release (a new Quest set, next set's boxes) was invisible to it.

Two things it does NOT re-report, structurally rather than by ack: `load_sealed_products.SKIP_NAME_PATTERNS` is **imported** (so a deliberate loader exclusion can't come back as a finding — add a pattern there and it's silent here in the same commit), and `sealed_no_set` skips `product_type='Promo Single'` / `card_no_pid` skips Format Coconut, where a null is the correct steady state.

### The PSA population refresh — weekly, and half of it cannot be automated

`pop_stale` is a third shape of finding, next to a machine-read check and a
`review_due`: the data is real and lives in a real table, but **its collector can
never run in CI.** PSA is Cloudflare-fronted (a datacenter IP gets the
interstitial) and every page below `/Pop` redirects to a collectors.com login, so
the pull needs a real browser, on a residential IP, signed in as Zaven. A runner
has none of the three.

So the two halves are split:

- **Doing it: `powershell -File scripts\pop_run.ps1`** — opens the burner Chrome
  (the same profile `graded_run.ps1` uses, so the collectors.com session usually
  persists between weeks), waits for a psacard.com tab, runs
  `psa_pop_pull.mjs` (~70 sequential jittered requests, ~4 min), then **dry-run
  loads**. `-Commit` writes; `-SkipLoad` pulls only; `-DryRun` prints the plan.
- **Remembering it: `reconcile_catalog.py --watch`**, already daily, already
  emailing. It reads `max(graded_pop.pulled_at)` and reports once it is over
  `POP_MAX_AGE_DAYS` (8) old.

**⚠ It checks the DATA's age, not a calendar, and that is the whole reason it is
not a `reviews` entry.** A review needs `--done` to roll forward, which is one
more thing to forget on a chore nobody is watching; a staleness check is cleared
by the act of doing it. 8 days is a weekly cadence plus a day of grace, so a pull
on Tuesday one week and Wednesday the next never alerts.

- **⚠ The ack key carries the last pull's DATE (`psa:2026-09-22`), never a bare
  `psa`.** Acks are keyed `kind:key`, so a constant key could be acked once and
  would then mute this permanently — for a staleness alert that is not a snooze,
  it is a mute with a reason attached. Keyed on the date, an ack can only ever
  cover the particular staleness in front of you.
- **⚠ Every failure of the check is SILENCE.** A database without migration 165
  has no `graded_pop`, and going red for a table a PR cannot create is the "red
  job everyone learns to ignore" the watch exists to avoid. An EMPTY table does
  speak up (`psa:never`) — that one is a real gap.
- **The steps travel with the alert**, the same rule `review_due` follows, because
  whoever reads the failure email needs a command they do not have memorised.
- **⚠ Never automate the collectors.com sign-in, and never retry past a wall.**
  `psa_pop_pull.mjs` treats a non-200, a sign-in redirect or a challenge-shaped
  body as fatal on purpose, and `pop_run.ps1` says to wait a day rather than loop.
  It is Zaven's real account. A set already pulled today is skipped, so re-running
  after a wall resumes rather than re-fetching.
- **`pop_run.ps1` reads the newest year heading out of `psa_pop_pull.mjs`'s own
  `YEARS` table** rather than carrying a copy. A stale hand-written heading opens
  a page that still exists and still renders — nothing errors, you just sign in on
  the wrong year.
- Unlike `graded_run.ps1` it does **not** kill a running Chrome: that script needs
  a fresh one because Terapeak freezes its date window, and PSA has no such window.

Guarded by `python scripts/test_catalog_watch.py`, which pins both directions —
a check that never fires freezes pop at whatever week it was last pulled while
every card page keeps confidently printing it, and one that fires on a missing
table trains everyone to ignore the run.

**Scheduled reviews — the parts no feed can watch.** Japan Core legality comes from a Japanese retailer's HTML; the pin and lore-counter lists come from a fan site; next set's spoilers come from press releases. Nothing can watch those, so `catalog_watch.json`'s `reviews` list carries them: each becomes a `review_due` finding on its date and rides the same red run and the same email. The `how` steps are printed **inside** the alert, because nobody is going to go dig them up. Four are seeded:

| id | due | what |
|---|---|---|
| `set-spoilers` | 2026-09-25 | prestage the next set's revealed cards before Lorcast indexes them |
| `promo-printing-policy` | 2026-09-28 | decide if promo *printings* are separate tracked items — most of the acks in the file defer to it, and it must land before Q3 prestaging. **Don't write the count down** — it has been wrong twice (this table said 9, the review said 13, it was 16); the review's `how` says how to enumerate them |
| `japan-core` | 2026-10-30 | re-scrape the Curator's Library waves into `JAPAN_CORE_PARTIAL_NUMBERS` |
| `pins-lore-counters` | 2026-10-30 | new season's pin + counters, and the still-missing photos |

`--done <id> [--next YYYY-MM-DD]` marks one done and rolls it forward (`every_days` is only the fallback when `--next` is omitted — these key off the release calendar, not a round number of days). A review is "acknowledged" exactly when its `due` is in the future; `acks` don't apply to it, so the only way to silence one is to do it or to deliberately push the date.

Guarded by `python scripts/test_catalog_watch.py` (no network) — it runs first in the workflow, because a bad state file fails by making the sweep pass. It checks `until` really expires, that a review actually comes due, that a rule can't match outside its kind, that every committed entry carries a reason, and that no review ships already overdue.
