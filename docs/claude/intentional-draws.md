# Intentional draws — flat, not skipped (2026-09-08)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

An ID is a scheduling decision, not evidence about who is better, and because IDs happen at the
top tables it is the leaderboard's best players whose ratings get dragged toward whoever they
shook hands with. `matches.is_intentional_draw` marks them; `elo.py` then holds both ratings
FLAT for that match.

- **⚠ Flat rows, never a skip.** Every W/L/D count and `mw_pct` in the Supabase views is derived
  from `elo_ratings.score` (`0.5` = draw), so dropping the row would delete the draw from the
  player's record AND silently restate their match-win percentage. A flagged match writes
  `rating_before == rating_after` with `score = 0.5` — the record is unchanged, only the rating
  stops moving. `elo.py` already did exactly this for `source='forfeit'`. Measured on a 1516 vs
  1484 pair: ID moves both 0.00, an identical unflagged draw moves them ∓0.52.
- **RPH publishes NO intent field — settled by dumping the whole payload**, not assumed.
  `probe_rph_draw_fields.py --event <id> [--round N]` prints every key on a match and on a
  player and which ones `ingest.py` ignores. All of them are scoring, structural or cosmetic:
  `status` is `COMPLETE` on draws and decisive alike, `match_is_loss` false on both,
  `matches_won/lost/drawn` are the player's running tournament record. There is nothing to read,
  so classification is inference and always will be.
- **The rule is a UNION of two independent signals, and neither half subsumes the other.**
  `DEFAULT_RULE = "score-or-position"` in `draw_classify.py` (the single source of truth — the
  report, the writer and `refresh_elo.py` all import it, so they cannot drift, and
  `test_intentional_draws.py` pins it). A draw is intentional if **0-0 at ANY round**, OR **any
  score in the closing rounds of Swiss with both players in cut contention**.
  - **The 1-1-1 half.** Zaven was asked to enter an ID as **1-1-1** — a game each plus a drawn
    game. `matches` has no `games_drawn` column, so it stores as `games_won` 1/1, identical to a
    Bo3 that timed out at one game each. Requiring 0-0 misses that whole convention: `e881262` R5
    is the confirmed shape, tables **1, 2 and 3 all drawing, every one entered 1-1**, with tables
    4+ decisive.
  - **⚠ The 0-0 half takes NO position gate**, and that is deliberate rather than an oversight.
    `position-only` left `e100267947` R3 unflagged — a 0-0 at 6 points each in a 3-round,
    8-player event, where nothing about the standings marks it and it is an ID all the same.
    Zaven's rule, in his words: *"0-0 is always ID no matter the round."* Nobody finished a game;
    that IS the agreement. This overrules an earlier reading here that a round-1 0-0 cannot be an
    ID — the scene is the authority on its own conventions, and 0-0 is only ~3% of draws outside
    the closing rounds, so the exposure is small either way.
  - **The branch order matters.** The 0-0 test sits ABOVE the `not _closing` bail, which would
    otherwise call an early 0-0 real before the score is ever consulted.
  - Measured over 2548 real draws: **0-0 is 93% closing / 71% contested / median table 1**;
    **1-1 is 49% / 31% / median table 3**. So most 1-1 draws are genuinely played out, which is
    why the position gate stays on that half.
  - `position` (0-0 AND closing AND contending), `position-only` (closing AND contending, any
    score) and `score-only` (0-0 alone) are all kept as options. Switching is a re-run of the
    flagger, not a repair.
- **Contention is judged ENTERING the round, never by who finally made the cut.** A player can
  agree a draw in the second-to-last round, lose the last one and miss; an outcome gate calls that
  real, which is backwards. On the bubble fixture the outcome gate lost 2 of 2.
- **The cluster signal counts only agreed-looking draws.** A played-out 1-1 beside an ID is not
  evidence that the table next to it shook hands.
- **The refresh workflow holds a `concurrency: elo-refresh` group** (`cancel-in-progress: false`).
  `refresh_elo.py` downloads the canonical SQLite at the top and uploads it at the bottom, so two
  overlapping runs each publish a DB missing the other's work. It queues rather than cancels,
  because the upload is the last step and a queued run therefore starts from the finished one's
  result.
- **`flag_intentional_draws.py` runs INSIDE `refresh_elo.py`, before `elo.py`, and must stay
  there.** Flagging by hand once decays on its own: flags survive the storage round trip, but a
  match ingested next week has never been classified, so its IDs go back to moving ratings on a
  green run with nothing red — the same silent-no-op shape as the board freezing at set rotation.
  Idempotent and reconciles both directions, so a rule change is a re-run, not a repair.
- Manual runs are a **dry run by default** and `--unflag` reverses a whole pass, because the
  errors are asymmetric: wrongly flagging a real draw deletes genuine evidence from a rating,
  while missing an ID only leaves today's behaviour in place. Same reasoning as
  `graded_sales.exclude_reason`.
- **`analyze_draws.py` is the read-only report** — `--rule`, `--player` (prints the GATES, not
  the verdict, because which gate rejected a draw is the whole answer), `--event`, `--since`.
  Neither it nor the probe needs a laptop: **Actions → ELO draw report** runs both against the
  canonical DB with no flag write, no export and no upload, so it cannot race the weekly refresh.
- **⚠ A round holding a draw is NEVER elimination, and `cut_rounds()` has to be told so.**
  The cut is inferred by walking back from the last round expecting 1, 2, 4, 8 … matches, since
  `phase_type` is stored only for GAP rounds. Counting alone cannot work: once players drop, a
  Swiss round lands on the very count the walk wants (a 23-player event with 8 matches left in
  R5, above a 4/2/1 cut, reads as a round of 16) — and the round it swallows is always the **LAST
  Swiss round, precisely where the IDs are**. Those draws were discarded as `in-cut` before any
  rule saw them: **86 across the DB**, including `e200747` R5, a confirmed ID Zaven reported as
  missing from his own profile. Single elimination must produce a winner, so a drawn match is the
  tiebreaker the count cannot supply and the walk stops there. The stop KEEPS rounds already
  collected, so a bogus draw row inside a genuine cut costs only its own round, not the bracket.
- One open item, not blocking: **184 of 840 events recorded no cut at all**, so contention is
  unanswerable there and their 190 closing draws can only ever be `unclear`.
- **The board says `ID`, not `DRAW`** (migration 136). The only visible sign an ID had been
  honoured was its Elo Δ sitting at `+0.0` — exactly the thing a reader has to already know to
  notice. `elo_player_rounds_v` carries `is_intentional_draw` through to the profile's
  round-by-round table and the H2H table; the pill reads ID in its own colour, titled with the
  fact that it moved neither rating. The client asks for the column and **retries without it on
  42703**: the migration lands on Zaven's schedule, and a missing column 400s the whole select,
  which would blank the profile rather than degrade it.
- **`scripts/elo/draw_overrides.py` is the last resort, and it has to be CODE.** Every automatic
  signal is an inference over position and score; a 1-1 in an early round at ordinary standings
  carries neither, so the data does not contain the answer and someone who was in the room has to
  supply it (`e605246` R2 is the case that forced this — Zaven's own agreed draw, invisible to
  every rule). **⚠ A hand-edit of `is_intentional_draw` in the DB does NOT survive**:
  `flag_intentional_draws.py` reconciles both directions on every run (`drop = already - want`),
  so a manual flag is cleared by the next weekly refresh, silently and with nothing red. An entry
  in this file is re-applied every run instead.
  - Keyed on **`(event_id, round_number, table_number)`**, all three straight from RPH, so the key
    survives a rebuild of the local SQLite. `match_id` would NOT — it is a bare autoincrement
    rowid, so a rebuilt DB renumbers it and every override would quietly point at a different
    match. The draw report prints exactly this key: `e605246 R2 t0` is `(605246, 2, 0)`.
  - Overrides run **LAST, after every tier including `in-cut`** — a person who was at the table
    outranks an inference — and land in their own tiers (`ID-manual` / `real-manual`) so the
    report never hides that a number came from a ruling rather than the rule.
  - **A key matching no draw is an ERROR that fails the flagger**, not a warning: an override that
    stopped applying is a decision that silently reverted, the same failure shape as the board
    freezing at set rotation. A `--season` run downgrades it to a note, since the event is simply
    out of scope there.
  - `FORCE_REAL` is the other direction, empty today — kept so a false positive has somewhere to
    go that isn't retuning the rule for everybody.
- Guarded by `python scripts/elo/test_intentional_draws.py`.
