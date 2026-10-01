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
  arrays, not an object per player; counting sort into point brackets; the intentional-draw
  guarantee check reads a precomputed suffix histogram, making it O(1) instead of O(N) per pairing.
  Benchmarked **9.5x the reference tool** (databorn.ink) at 256p/8r, and it uses up to 8 workers.
- **Odds come from pooling every simulated player who held your record**, not from tracking one
  player — under equal skill they're interchangeable, so a 10k-sim run yields ~10^5 samples per
  record instead of ~10^4, and changing your record re-reads the pool with **no re-simulation**.
  This is also why the numbers are path-aware: a 4-1 who loses cuts ~16% while 4-2 overall cuts
  ~6.7%, because their tiebreakers are better.
- **Guarded by `node scripts/test_swiss_engine.mjs`** (extracts the real engine out of swiss.html,
  house pattern): Swiss-triangle exactness at 64p/6r, conservation across odd fields/drops/IDs/tiers,
  flagship ID behavior (the 5-0 pair always IDs into 5-0-1 and cuts), tie-inclusive tier payouts,
  and determinism. Run it after touching the engine, pairing, ID rule, or sharding.
- **Reproducibility is exact, cross-device — keep it that way.** The run is split into a FIXED
  ≤16-shard plan (`shardPlan`) with seeds derived from the shard index, workers pull shards off a
  queue, and results fold IN SHARD ORDER. Counts are exact in f64, but the tiebreaker accumulators
  are float sums, so fold order is part of the guarantee — folding on arrival order (or splitting by
  `hardwareConcurrency`, as v1 did) makes the same Copy link give different numbers on a 4-core
  phone vs an 8-core desktop (measured: 137026 vs 137027 vs 136949 for one cell).
- **The ID guarantee counts the OPPONENT as a threat** when the post-draw opponent can still tie or
  beat you (`bMin` floor in the engine) — a same-bracket opponent ties you forever, and excluding
  them let knife-edge pairs "safely" draw each other into a 9th-place tiebreaker. Ties with third
  parties already counted (>= not >). Don't simplify either away.
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
- Every match is 50/50 — this measures bracket structure, not decks. Say so in any UI copy.
- Not built: PlayHub standings import. It needs a server-side fetch (PlayHub is CORS-blocked); the
  Cloudflare worker is the natural place, mirroring the existing `/img-proxy` pattern.
