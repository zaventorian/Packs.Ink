# Swiss simulator (`/lab/swiss`) — unlisted, added 2026-08-20

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Monte Carlo odds for Lorcana Swiss events. **Standalone `swiss.html`, NOT part of the SPA** — the
engine is ~15KB of hot loop that no ordinary visitor should download, and keeping it out of
Index.html avoids fighting the concurrent-session churn there. Links `styles.css` for tokens, so
all seven themes work with no extra CSS, and reuses Index.html's pre-paint theme boot verbatim.

- **Route**: `/lab/swiss` → `swiss.html`, rewritten in BOTH `worker/index.js` (prod) and
  `scripts/dev_server.py` (local). Listed in `build_dist.mjs`, `Disallow`d in robots.txt, `noindex`
  in the head. "Hidden" here means undiscoverable, **not access-controlled** — anyone with the URL
  can load it. Don't put anything sensitive on it.
- **The Analytics embed only works because `_headers` carries a `/swiss` rule** detaching the
  site-wide `X-Frame-Options: DENY` + enforced `frame-ancestors 'none'` and re-setting them to
  SAMEORIGIN / `'self'` — the `/*` block refuses framing even from packs.ink itself, which
  rendered the iframe as the gray broken-page icon on prod until 2026-08-21. Local dev never
  shows this (dev_server.py doesn't apply `_headers`) — verify framing changes with
  `npx wrangler@4 dev`, which applies the file like prod. Any NEW same-origin iframe surface
  needs the same carve-out, and the parent side needs `frame-src 'self'` (already in the
  report-only policy) or enforcement will block it from the other end.
- **The engine is one self-contained `swissEngine()`** stringified into a Blob worker, so the
  worker and the main-thread fallback literally run the same text and can't drift. Flat typed
  arrays, not an object per player; counting sort into point brackets; the intentional-draw plan
  is built once per round from point histograms, O(tables + point range), never O(N) per pairing.
  Benchmarked **9.5x the reference tool** (databorn.ink) at 256p/8r, and it uses up to 8 workers.
- **Odds come from pooling every simulated player who held your record**, not from tracking one
  player — under equal skill they're interchangeable, so a 10k-sim run yields ~10^5 samples per
  record instead of ~10^4, and changing your record re-reads the pool with **no re-simulation**.
  This is also why the numbers are path-aware: a 4-1 who loses cuts ~16% while 4-2 overall cuts
  ~6.7%, because their tiebreakers are better.
- **Guarded by `node scripts/test_swiss_engine.mjs`** (extracts the real engine out of swiss.html,
  house pattern): Swiss-triangle exactness at 64p/6r, conservation across odd fields/drops/IDs/tiers,
  flagship ID behavior (the 5-0 pair always IDs into 5-0-1 and cuts), the coordinated rule's exact
  64/6/top8 answer (one 4-1 table joins them), "a planned final-round draw always lands" across six
  field shapes incl. prize tiers, the day-two cut, tie-inclusive tier payouts, and determinism. Run
  it after touching the engine, pairing, ID rule, or sharding.
- **Reproducibility is exact, cross-device — keep it that way.** The run is split into a FIXED
  ≤16-shard plan (`shardPlan`) with seeds derived from the shard index, workers pull shards off a
  queue, and results fold IN SHARD ORDER. Counts are exact in f64, but the tiebreaker accumulators
  are float sums, so fold order is part of the guarantee — folding on arrival order (or splitting by
  `hardwareConcurrency`, as v1 did) makes the same Copy link give different numbers on a 4-core
  phone vs an 8-core desktop (measured: 137026 vs 137027 vs 136949 for one cell).
- **Intentional draws are COORDINATED, and that rule was chosen by replaying real events
  (2026-10-06).** In the last two rounds, `planDraws` takes tables best-first by their LOWER
  player's points; a table draws if, with it and every table above it drawing out the event, every
  drawing player still finishes inside the cut — while each other table PLAYS and so puts at most
  ONE player (its winner, who then wins out) above them. Ties count as threats for the cut (a tie
  goes to tiebreakers); with prize tiers on, tables below keep drawing into each wider tier, where
  only players strictly ahead count (tiers are tie-inclusive).
  - **It replaced a "guarantee" rule that assumed every player who could reach your total might ALL
    win out.** They can't — they're paired against each other — so it told 4-1s at a 64-player Top 8
    "you need the win" while real 4-1s drew in and made it 96% of the time.
  - **`python scripts/swiss_replay.py check`** scores both rules on the last two rounds of every
    cached event (546 RPH events: 8 two-day Challenges, ~45 qualifiers/championships, 492 SCs; run
    `fetch` first, ~10 min, cache gitignored). Measured: coordinated calls **92%** of the final-round
    draws that got both players in (and 99% of its calls that players took got both in); the old
    rule called **63%**. With two rounds left: **50% vs 7%**.
  - **What it still misses, on purpose:** gambles. ~23% of real final-round 0-0s were draws into
    spots that were only *likely* (71% got both in), and with two rounds left real players draw
    about twice as often as the rule allows (80% success). Modelling them would mean simulating
    risk appetite; the pooled "If you draw" odds already show what a draw is worth.
  - **Don't "fix" it back to a guarantee.** Simulated at each real event's size/rounds/cut, the
    coordinated engine lands on the exact real cut line 76% of the time for 17-32 player Top 8s
    (old: 63%) and 74% for 227+ player Top 32s (old: 34%), and it stops overstating a bubble loss
    (33-64 player Top 8, 4-1 loses the last round: real 6%, old 45%, now 22%).
- **`pct()` only says 100%/0% when literally every/no sample hit** — near-certain values render as
  >99.9% / <0.1% bands. On a draw-safety tool, rounding 99.5% up to "100%" is the one dishonesty
  that matters.
- **A click during a run queues one rerun** (`PENDING` in run()/done()) — the IDs seg and tier
  toggle update visually on click, so dropping the request would leave the UI disagreeing with the
  results forever.
- **The theme toggle is transient when the stored mode is "system"** (attributes only, no
  localStorage write), matching the main app's deliberate system-mode semantics. Explicit
  light/dark persists to the shared keys.
- **Drops default OFF on purpose.** They're supported, but modelling attrition removes dropped
  players from the conditional pools (64p/6r at 3 losses halves the sample), which makes losing
  records read "no data". The threshold list is regenerated from the round count — you can't lose
  an eighth match in a seven-round event.
- **Prize tiers (toggle, off by default)** cover payouts past the cut — Nats cuts to 16 but 32 and
  64 also collect. They are **tie-inclusive**: a tier's cutoff is the point total of the player
  sitting at that placement, and everyone level with them is paid, so "Top 16" pays ~18 people at
  136/8. That rule is also why it needs no sorting — the final-points histogram answers
  `pts >= cutoff` directly. The **cut stays strict** (only N enter the bracket), so the two numbers
  differ on purpose: a 6-2 at 136/8 makes the cut 77% of the time but takes Top-16 prizing 100% of
  the time. Every surface that shows both must label them or it reads as a bug.
- **There is deliberately no on-the-play setting.** If who plays first is a coin flip, a first-player
  win rate of w makes each match 0.5w + 0.5(1-w) = 0.5 regardless of w, so it cannot move any output.
  Verified empirically at 50/55/60/70% — identical record distributions. It was removed rather than
  left as a knob that appears to do something. A real version would have to model winning the die
  roll more often than half the time, which the pooled-odds design can't express.
- **No awarded-byes setting either.** A bye for one player is statistically invisible once the odds
  pool the whole field, and a bye is just a win for record purposes. The meaningful version is
  "N players receive a first-round bye", which changes the field's point spread — not built.
- **Defaults are measured, not guessed (2026-10-06, same replay).** Time draws ("unintentional
  draw rate") default to **3%**: middle rounds run 3-5% at Set Championships and qualifiers, 1.3%
  at two-day Challenges. **Top cut follows the field** (`CUT_STEPS`): no cut to 8 players, Top 4 to
  16 (182 of 195 real 9-16 player SCs), Top 8 to 128, Top 16 to 226, then Top 32 — set on every
  Players edit, the same way rounds already were. The round ladder matched what organisers run.
- **Two-day events (`day2After` / `day2Pts`, link param `d2=8.18`).** Every RPH-published Disney
  Lorcana Challenge plays 8 rounds, then everyone on **18+** points (all of them — it is a points
  line, not a top-N) plays 4 more into a Top 32. Players below the line are marked `elim` and leave
  pairing like a drop, but **stay in the conditional pools for the rounds they played** — leaving
  them out (as drops are) would pool only the day-one records that made day two and inflate every
  day-one odd. From 410 players the rounds hint offers "Use that format" (12 rounds, Top 32, day
  two on, 1.5% time draws). It matters below ~1,200 players: at 560 a 5-3 who wins out reaches 27
  against a real line of 26; at 2,000 the line is 30 either way (and the sim agrees: 30, with 10-2
  getting in 91% against a real 77-84%). "Where do I stand" adds the exact day-two odds.
- **Real events drop 10-30% of the field by the last round.** Drops stay off by default for the
  reason above; the cut maths barely moves because the droppers are the losing records.
- Every match is 50/50 — this measures bracket structure, not decks. Say so in any UI copy.
- Not built: PlayHub standings import. It needs a server-side fetch (PlayHub is CORS-blocked); the
  Cloudflare worker is the natural place, mirroring the existing `/img-proxy` pattern.
