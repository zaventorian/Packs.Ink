# Discord bot (`discord/`) — 2026-09-27

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Zaven's ask: call a card in Discord and get its picture and price history, plus
trend reports, with **plain-English, typo-tolerant lookup as the main
requirement** — "people will say mowgli and not know the subtitle, but there is
one main one that is played, or spell mowgli slightly wrong". `/card`, `/price`,
`/set`, `/open`, `/new`, `/meta`, `/events`, `/calendar`, `/help` and `/reports`
(v2 additions below; what changed on 2026-09-29 is in its own section).
Setup (the steps only Zaven can do) is `discord/README.md`.
Guarded by `node scripts/test_discord_bot.mjs` (~3,100 checks) and
`python scripts/test_discord_reports.py`.

- **LIVE since 2026-09-28** (PR #149, site v493) at
  `https://packs-ink-discord.packs-ink-app.workers.dev` (`/` is a health check,
  `/invite` a server install). Discord app **packs.ink**, application id
  `1553932826980782282`; install link
  `https://discord.com/oauth2/authorize?client_id=1553932826980782282`. User and
  Guild install are both on; Guild Install brings the bot with View Channels,
  Send Messages and Embed Links, which `/reports` needs to post.
- **A SEPARATE Worker, `packs-ink-discord`, on workers.dev.** Deploying it
  cannot touch packs.ink, and it adds no route to the site's zone.
  `.github/workflows/discord_bot.yml` deploys it **on a daily schedule (21:45
  UTC)** — the one scheduled deploy in the repo, and deliberately: the card
  index lives inside the Worker and has to follow the catalog. A Workers deploy
  costs nothing; the push policy is about the SITE. Until the `DISCORD_*`
  secrets exist the job builds, tests and stops, green.
- **Slash commands, not @mentions.** Reading ordinary messages needs a 24/7
  gateway connection — a server — which this deliberately is not. Discord
  interactions over HTTP are all a Worker can answer.
- **The card index is built by running the SITE's catalog code.**
  `discord/tools/sitecode.mjs` parses Index.html's app script with acorn, takes
  the transitive closure of the declarations a function needs, and runs it in a
  Node vm; `build_index.mjs` feeds `transformSupabaseData` live rows, so every
  catalog rule (Holofoil mislabel, connecting foils, C2 ghosts, regional
  exclusives, variant clones, `printingBadge`) applies with no copy of it.
  `card-index.json` is NOT committed; `check_index.mjs` refuses a build that
  came out small. Popularity (the resolver's prior) is recency-weighted tournament top-cut appearances
  (half-life 120 days) grouped by `cardFamilyKey`; collector words (a chase
  rarity, a grade) switch the tiebreak to graded sale volume.
- **⚠ `discord/src/site.generated.js` is Index.html code copied VERBATIM**
  (`computeSeriesDeltas`, `priceStanding`, `tcgUrl`, `amazonForSealed`, the
  calendar derivation, the postal-code walk, `gradedSlotBucket`, `rawSaleMatch`
  and their closure). The guard fails the moment a copied statement stops
  matching Index.html, so **changing any of those functions on the site turns
  the Discord guard red until you run `node discord/tools/extract_site.mjs`**.
  That is the point: the bot must never say a different "1W" or "Cheapest in 12
  months" than the site. The deploy workflow regenerates it from the commit it
  ships, too.
- **Every database read is DEFERRED.** Discord gives an interaction 3 seconds;
  the Worker answers "thinking…" (type 5, or 6 for a button) at once and PATCHes
  `@original` from `waitUntil`. Autocomplete and `/help` are local and answer
  directly. **`allowed_mentions: {parse: []}` on every payload** — a reply can
  echo what somebody typed, and that could be `@everyone`.
- **Keys are `c|<card_id>|<N|C|H|F>` and `s|<pid>`** — pipes, because card ids
  carry colons (`extras:647652`, `<base>::variant::text-error`). A button's
  custom_id is `r|<range>|<view>|<grade|->|<key>`, key LAST; the grade token is
  how a graded reply's buttons remember the slab. All fit Discord's 100 chars
  (the guard checks every card in the fixture).
- **Charts are drawn by the Worker** (`src/chart.js` rasteriser, glyphs baked
  from Nunito Sans by `tools/bake_font.py`, `src/png.js` with its own fixed-
  Huffman deflate, ~5 ms per 800×340 chart). The image URL carries `?d=<price
  date>`: Discord caches by URL, so a new day needs a new URL.
- **Card art is TCGplayer's JPEG** (`<pid>_in_1000x1000.jpg`) **or art baked for
  the Worker — never Lorcast's AVIF.** Discord shows no AVIF, and it REJECTS a
  whole reply whose image is a `data:` URI or a relative path, so the reply
  never arrives. Until 2026-09-28 every printing TCGplayer hasn't listed (all of
  Hyperia City before release, regional promos: 84 printings) came back with no
  picture. `tools/bake_art.mjs` (sharp) converts them to WebP at deploy time
  into `discord/public/art/` (gitignored), which wrangler's `[assets]` serves at
  `/art/<id>.webp?v=<hash>` WITHOUT running the Worker; `cardImage()` in
  embeds.js is the one accessor, and `check_index.mjs` refuses an index that
  points at a missing file or an image Discord can't show. The `?v=` hash busts
  Discord's image cache when Lorcast re-renders a card.
- **`/card` shows the SITE's card tile** (2026-09-28, Zaven: *"if someone calls a
  card, id like it to basically spit out this image from our site"*), drawn once a
  day at deploy time because the Worker has no canvas. `tools/bake_tiles.mjs`
  runs the site's own `drawCardTileCanvas` (via sitecode.mjs, like the catalog
  transform) on `@napi-rs/canvas`, for every priced finish (~5,800, ~275 MB of
  WebP at 450px), in the velvet palette read out of styles.css, with Low / Market
  and the 1D / 1W / 1M changes from the site's `computeSeriesDeltas` as of the
  index's price date. Files go to `public/tile/` (gitignored, served as static
  assets); the index marks each printing's drawn finishes in `tl`, and
  `src/tile.js` is the one naming rule both sides use.
  - **⚠ Not on a graded reply or a raw-eBay promo** (the tile carries TCGplayer's
    raw price, which those replies call secondary), not for a named variant with
    no SKU, and not in the chart view. Anything without a tile shows the plain
    picture it always did, so **nothing about tiles can fail a build**: the whole
    step is try/caught, and `check_index.mjs` only fails on a tile the index
    names that is missing from disk.
  - **The tile URL carries `?d=<price date>`** — Discord caches by URL, and the
    footer date changes daily, so every tile is re-uploaded each day (wrangler
    skips unchanged files, so a second deploy the same day uploads nothing).
  - **⚠ The tile is UPLOADED with the reply, not linked** (2026-09-29). Linked,
    Discord dropped it from the FIRST edit of a deferred `/card` reply — the
    stored message had no image at all, even after a reload — and showed it on
    every later edit of the same message (a button, a foil switch), which is
    how it read as "no picture until you mess with it". TCGplayer and Supabase
    pictures in the same first edit were fine, so it is our workers.dev assets
    in particular; the cause on Discord's side was not pinned down, and the
    upload sidesteps it. `withUploads` (interactions.js) reads any embed
    picture under `<origin>/tile/` or `/art/` through the **`ASSETS` binding**
    (wrangler.toml) and sends it as `files[n]` with `attachment://` in the embed.
    Every plain edit carries `attachments: []`, or switching to the chart would
    leave the tile hanging loose under the embed. A refused upload (any
    status) is re-sent once with the link, then the plain-text fallback as
    before; a file the asset store can't produce stays a link.
  - **⚠ Charts are uploaded too** (same day, Zaven: *"now when I click over to
    price graph, that wont load unless I click through all the options"*).
    `withUploads` draws them in-process with `chartResponse` — the very route
    Discord would have fetched, so the picture is identical — and a chart whose
    database read fails keeps its link. A live tail showed Discord downloads a
    linked chart THREE times (~2 s after the edit, three different IPs, GET
    with a Discordbot UA, never HEAD), each a fresh Supabase read and redraw
    at 27–35 ms of CPU, not the ~5 ms the render alone costs. TCGplayer
    thumbnails and the instant `/set` / `/open` replies stay links.
  - History is fetched per product for 45 days, then a year for the few whose
    1M reference (or latest price) sits further back (`needsLonger`), so the
    numbers match the site's card page. The art is cached between runs in
    `.tile-art-cache/` (actions/cache, keyed by month so a re-rendered card is
    picked up within a month); a cold cache costs ~8 minutes.
  - `tools/tile_rules.mjs` holds the pure rules (which finishes, how much
    history) so the offline guard can test them without the native canvas.
  - **The bot also deploys when an ETL run finishes** (`workflow_run`), so new
    cards and the day's prices reach it the same evening rather than after the
    late-running 21:45 schedule.
- **Every TCGplayer link is the affiliate link** (`buyUrl()`: `tcgUrl` for a
  listed printing, `tcgSetSearchUrl` — a TCGplayer search for the name — for one
  that isn't). Card titles, the Buy/Find button and /meta's card list all go
  through it, and every message carrying one ends its footer with
  "Links may earn packs.ink a commission". The guard fails a reply with a
  non-affiliate TCGplayer link or without that line.
- **On a promo TCGplayer cannot price, eBay leads** — the site's raw-sales
  rule (see "Raw eBay sales"): Last sold + Avg of last N come first, TCGplayer
  Low / Mkt second, and the chart draws each eBay sale as a DOT over the Market
  line with Low left off (`/chart/p/...?r=<card>&rb=<bucket>`), or the sales
  alone (`/chart/r/...`) for a card with no TCGplayer product. The split bucket
  goes through `gradedSlotBucket` / `rawSaleMatch`, copied from the site, so a
  Challenge card's Top Prize and Prize Wall sales never share a chart.
- **`/reports`** stores (server, channel, cadence) in
  `discord_report_subscriptions` (**migration 173, APPLIED 2026-09-28**) through the service
  key; `scripts/discord_reports.py` posts the report through the bot token,
  daily and on Mondays for weekly. The movers data, the standing maths and the
  freshness rules come from `discord_digest.py`; the LAYOUT is the report's
  own (see "The channel report's layout" below). It drops a mover whose
  "today" is not today (`drop_stale`). A 403/404 is written to `last_error`, which
  `/reports status` shows.
  - **⚠ It runs when an ETL run FINISHES** (`workflow_run` on "ETL", which
    cron-job.org dispatches on time), with the 21:20 / 23:20 UTC schedule kept
    only as a fallback. GitHub has started this repo's evening schedules 2-3
    hours late — the 21:15 digest ran at 23:35-23:56 UTC every day that week —
    so on the schedule alone the report landed near midnight, and the old
    "newest prices must be dated today" rule skipped the whole day whenever a
    run crossed it. Found 2026-09-28, the first day a report was due, when none
    had arrived by 22:45 UTC.
  - **A day's report may post until noon UTC the next day** (`LATE_GRACE_HOURS`),
    never later, and `last_posted_on` holds the PRICE date a channel got — so the
    many runs a day are safe: nothing posts twice, and no day-old report is sent
    the next evening. The embed title carries its date, so a post after midnight
    is still clearly that day's.
- **Secrets live in GitHub**: `DISCORD_APPLICATION_ID`, `DISCORD_PUBLIC_KEY`,
  `DISCORD_BOT_TOKEN` (all set 2026-09-28). The deploy syncs the first two into
  the Worker, plus, for `/reports`, the repo's own `SUPABASE_SERVICE_KEY`, reused
  so nobody copies a service key by hand (Zaven, 2026-09-28; a
  `DISCORD_BOT_SUPABASE_KEY` secret overrides it). **The bot token is NOT in the
  Worker** — it stays in GitHub, used only to register commands and by
  `discord_reports.yml` — and is never logged or pasted anywhere else.
- **`node discord/tools/simulate.mjs` runs the real Worker in `wrangler dev`**
  with a throwaway Ed25519 key pair, signs requests the way Discord does, and
  captures the follow-ups into `discord/.wrangler/sim/`. That is how every reply
  shape was checked before any Discord app existed.

### v2 (2026-09-28): /trade, /set, /open, /meta, boards you browse

- **The free plan's 10 ms of CPU is the binding constraint, and v1 was over it
  on two paths**: a cold first lookup (~11 ms) and Price check (since retired)
  on a long chat message (~15–17 ms) — over the limit the reply simply never
  arrives. The
  resolver now precomputes the popularity priors and each character's versions,
  skips an edit distance when the two tokens' LETTER SETS differ by more than
  2 per allowed edit (exact: one edit changes the set by at most two symbols —
  property-tested in the guard), and `findInText` skips a message window whose
  best possible coverage is under the 0.9 a clean match needs. The isolate is
  warmed at startup. Lookup ~0.98 → ~0.12 ms, long message ~15 → ~4 ms, cold
  lookup ~11 → ~4 ms. **Proven answer-identical**: 22,612 answers over the
  live index (every card name, typos, rarity/foil/grade phrasings, autocomplete
  prefixes, 810 chat messages, 40 decklists) diffed before and after, 0
  changes. Re-run that kind of harness before touching the resolver's speed.
- **A reply Discord refuses (400) is re-sent as plain text** (`plainFallback`);
  a button's failed update goes to the clicker as a private follow-up.
- **⚠ Every component in a message needs a DIFFERENT custom_id** — Discord
  refuses the message otherwise. The boards highlight the current state on
  several controls at once, so each control carries a letter:
  `e|<k|r>|…` (events), `cl|<k|r>|…` (calendar),
  and a second card menu is `o|card|1` beside the first's `o|card`.
  `checkMessage` in the guard asserts uniqueness on every reply.
- **Box EV and play shares are computed in the daily index build** with the
  site's own code: `processData` + `calcEV` (the EV tool's defaults — nothing
  excluded, Low and NM Market), and `playDecks` (the recency-weighted count of top-cut decks, so a card's `pl`
  reads as "in 38% of decks"). An unreleased set shows no box EV — its prices
  are pre-sale.
- **`/open` is the site's `simPack` with `getPull`** (copied by
  `extract_site.mjs`), over pools built from the index; named variants are not
  a pack slot. Averaged over 200 simulated boxes it reproduces the site's pull
  rates (e.g. 6.12 Legendaries / 2.52 Epics / 0.32 Enchanteds per Attack of the
  Vine! box against 6 / 2.5 / 0.333). A pack's pictures are up to four embeds
  sharing one `url`, which Discord draws as one image grid.
- **`/new` is the site's reveal reel** (`revealRotation`: `added_at` within 96
  hours, capped at `REVEAL_MAX_CARDS` 36, Extras and reprints left out), **run
  when someone asks, not at build time** (2026-09-28). Reveals land all day
  (prestaged art through the afternoon, Lorcast's load in the evening) and the
  index is built once, so a reel frozen in the index ran up to a day behind the
  site's. The build stores the reel's INPUTS in `index.reveals` — every card
  inside the window, uncapped, `{id, t, n, s, no, f?}`, where `f` is when the
  card's NAME was first seen (a card leaves the site's reel once its name is
  older than the window) — plus `index.catalogAt`. The Worker runs the site's
  `revealRotation` over those plus any card inserted since `catalogAt - 2h`
  (`freshRevealRows`: one read of `cards` with `sets(name)`, put through the
  transform's rules — display names, promo rarity, suppressed rows, pid
  overrides, companion and Extras-only products), so /new is DEFERRED.
  **⚠ The reprint check is a second read, and if it fails nothing just added is
  shown** (fail closed); if the first read fails the reply comes from the index.
  `revealInputs` (set.js) is the one derivation; the build warns if its entries
  stop reproducing the site's reel, and the guard proves they give the site's
  reel at the build moment and at every later moment. A just-added card is
  listed but kept out of the menus until the next build. Headings are DAYS back
  from the moment of asking ("Added in the last 24 hours", "Added 1–2 days
  ago"): reveals trickle in one or two at a time, so a heading per load was a
  heading per card. Newest first, a picture grid of up to four, and two menus
  past 25 cards. **⚠ A name links to TCGplayer only when that
  printing has its own listing** (`f[1] && !f[6]`): a card of a set still being
  revealed has none, and a ~250-character search link per line fit 13 of 36.
  **⚠ `newRank` reads `RANK` at CALL time** — `RANK` is declared further down
  set.js, and a module-level copy of it is a TDZ error at import.
- **`/events` asks the RPC once PER KIND.** It returns the soonest series first,
  capped, so in a busy metro "everything" was sixty weekly nights and the Set
  Championship three weeks out never made the list. Prereleases sort nearest
  first (they share a weekend); weekly play is one line per store.
- **`/set`'s chase list is its own embed's description, not a field**: every
  name is a ~220-character affiliate link and a field's 1,024 clipped the list
  mid-link.
- **Commands are registered BEFORE the deploy** (`register_commands.mjs --ids
  src/command-ids.json`) so their ids are bundled and /help shows them as
  clickable `</name:id>` mentions; the interactions endpoint is set AFTER
  (`--endpoint-only`). A failed registration still deploys the day's index,
  then a last step turns the run red. `build_index.mjs` leaves `{}` for local runs.
- **No `-#` subtext inside embeds** — it isn't reliably drawn there; secondary
  lines are italics. Plain message content (the fallback) keeps it.
- **The channel report has its own layout** (see the next section); the
  digest's embed (`build_embed`, shared with the site's never-configured
  webhook) is untouched.

### 2026-09-29: four commands retired, /meta by ink pair, send now, card text

Zaven: *"lets kill trade, deck, price check, movers"*. `/trade`, `/deck`,
`/movers` and the **Price check** message menu are gone, with `trade.js`,
`deck.js`, the movers board, the deck modal and `tcgplayer_names` in the index.
Registration is a bulk PUT, so the next deploy removes them from Discord; a
client still showing one gets "Unknown command." (guarded). The resolver's
`findInText` stays: it is tested, and cheap.

- **`/meta` leads with the ink pairs of every top-8 deck** (Zaven: *"what decks
  are meta"*). One read of `tournament_results_v` (`place_rank <= 8`) since the
  newest booster set already ON SHELVES (`metaSet`: `main` and `date <= today`,
  so an announced set's empty window is never used), Core only, grouped by ink
  pair in ink order. `deck_name` is empty on most tournament decks, so the pair
  is the only exact archetype. Under three events since the set it widens to
  the last 45 days and says so. Each line: the marks, a ten-cell bar **scaled
  to the leading pair** (an absolute bar gave every pair two or three cells, and
  two pairs both at "25%" came out a cell apart on rounding), the share, decks,
  top 4s and wins. Measured on the day: 224 decks from 31 Core events since
  Attack of the Vine!, Amber/Emerald 25% and 11 wins.
- **"Latest big events" is chosen, not just the newest three** (*"decide recent
  tournaments better"*): the three with the most players in the last three
  weeks that recorded at least four decks, shown newest first; under three, it
  reaches back 45 days. A winner-only record (a single row) is a stub and
  skipped. Infinity events can appear and say so. The breakdown, the most
  played cards and the events come to ~4,300 of the 6,000 characters.
- **`/reports send`** (server managers) posts the latest daily or weekly report
  in the channel, now. `discord_reports.py` keeps both every day it runs with
  `--post`, **whether or not any channel subscribes** (`store_latest`), in
  `discord_report_latest` (**migration 175, APPLIED 2026-09-30**), built once a day per
  cadence. Its pictures go to the public `discord-reports` bucket under
  `<cadence>/<price date>/`, because Discord caches an image by URL; yesterday's
  are deleted once today's are kept. If a picture fails to store, the kept
  report is the plain one rather than a broken image. The Worker reads the row
  and `withUploads` uploads those pictures with the reply (`REPORT_PICTURE`),
  like every other picture. **A refusal (not a manager, not switched on) is
  answered privately and at once**, before any read; only the report itself,
  or "no report yet", is public. Storing can never cost a subscriber their
  post: it is wrapped, and it runs before the subscriber loop.
- **`/card` shows the card's rules text and stats** (*"the text of the card
  under the name above the image"*). The index carries `x` (the NEWEST booster
  printing's wording), `st` (strength / willpower / lore / move) and `ik`
  (inkable). `rulesText`: one quoted line per ability, the printed ALL-CAPS
  ability name bold (three capitals at least, so "A character…" stays plain), a
  keyword the card has bold with its number and the ink it's paid in ("Shift 6
  ink"), reminder text italic, `{I}` / `{E}` / `{L}`… as words (Discord has no
  glyph for them), markdown escaped. Checked over all 3,195 catalog texts: no
  odd output, the longest 428 characters. An uninkable card says so.
- **Card pickers show the card's stats** (Zaven: *"a small sub line under each
  option saying the stats … amethyst 6c inkable 5/6 2lore and any keywords"*).
  `src/stats.js` builds them once for every surface: ink, cost, inkable, S/W
  (a Location's move + willpower, an action's type), lore, keywords with their
  numbers read off the card's own line ("Shift 6", "Resist +1").
  - **⚠ Discord's `/card` suggestions have NO sub-line** — one line of ≤100
    characters is all an autocomplete choice can show — so the stats go ON
    that line: `Demona - Scourge of the Wyvern Clan — 🟪 6c · inkable · 5/6 ·
    2 lore | Legendary · Non-foil · $39.14`. Too long, the set name goes
    first, then "inkable", the last keywords, "uninkable", the word
    "Location", then "willpower" → "wp", and last the stats trim behind a
    "…" (`fitParts`'s `trim` group) so **the finish and price are never cut**.
    Measured over all 6,252 printings: none over 100, none lose the price, 20
    trim with "…". The guard checks every fixture printing.
  - **Select menus DO have a sub-line** (`description`), so every card menu
    carries the stats in words there, before what it already said (rank,
    rarity, price): "Did you mean", `/meta`'s card list, `/set`'s chase list,
    `/new`, `/open`. In the versions menu only ANOTHER version gets them — the
    card's own printings share the stats already shown above.
- **Every event links to its page on packs.ink** (`eventPageUrl` →
  `/calendar?ce=<id>`), which links on to the organiser: `/events` uses
  `ev:<rph event id>` (the calendar fetches one the reader doesn't follow),
  `/calendar` the entry's own id (a curated uuid, `set:…`, `product:…`).
  Before, an RPH row linked straight to RPH and a curated one to its
  registration page or nowhere.

### 2026-09-30: what a reply LEADS with

A read of every reply from the user's seat (Zaven: *"think about how a user would use
it, what they would want"*). The replies were correct and answered the wrong question
first. Guarded by section 13 of `test_discord_bot.mjs`.

- **`/price` leaves the rules text and stats to `/card`.** The two commands were one
  reply with a different picture: eight lines of rules text sat above every chart and
  pushed the chart, the changes and the graded tiers below the fold. `/price` keeps the
  set line, the ink / cost / type line, the play line and the numbers.
- **The other finish is on the reply** ("Foil **$7.93**" under the non-foil's price, and
  the reverse), from the index's prices like the versions menu. "And the foil?" is the
  follow-up every price reply got, and it cost a menu pick.
- **A played base-rarity card prices its playset** (`playset $8.84`, 4 × NM Market) on the
  price line — competitive players buy four. Never on a chase card.
- **A grade asked for is the HEADLINE.** `/price elsa psa 10` led with the raw price and its
  1D/1W changes and put the PSA 10 sale fourth, in a grid of six tiers, with no date.
  Now: "**$3,000** last PSA 10 sale (Sep 12) · avg of last 5 $3,095", the count of sales,
  then "Raw: $951 NM Market · $855 Low" plain; the raw change line and standing are off
  (they judge the raw price, the same rule the eBay-led promos follow); that tier is not
  repeated as a field. Every tier field now carries its last-sale date, and counts read
  "1,056 sales".
- **A booster box says whether to open it**: "Box EV **$58.91** at NM Market — the cards
  inside are worth about **50%** of the box" (the daily build's `set.ev`, `/set`'s
  number), plus **Open a box** (`packId`, moved into embeds.js — set.js re-exports it) and
  **Set at a glance** (`setId` → `st|<si>`, an instant new message via `setReplyAt`). A
  pack reply offers Open a pack. Neither opener on a set not yet out, no EV on it either
  (pre-sale prices), and nothing of this on a trove or gift set.
- A no-match with nothing to suggest points at `/help`; help and the command
  descriptions now tell `/card` and `/price` apart.
- `simulate.mjs` no longer tries to fetch an `attachment://` chart at the end of a run.

### 2026-10-04: Low leads, /card trusts its tile, play share is per set

Zaven: *"lets use low, like we do on the site"*, and on /card: the price lines are
*"in the photo already"*. Guarded in `test_discord_bot.mjs`.

- **Low is the headline price everywhere in the bot**: `/price` (`**$1.49** Low · $2.29
  NM Market`), the change line (Low's deltas, Market's only when there is no Low), the
  other finish, the playset (4 × Low), the versions menu, `/meta`'s card list, `/set`
  (chase list, box, box EV, sealed lines), `/open` (pull values and the pack/box cost)
  and sealed replies. The chart draws Low as the gold line and Market as the second;
  on an eBay-led promo Low is still left off and Market takes the gold.
  - **The standing chip still judges `market_price`** — that is the site's own
    `priceStanding` rule, and a phantom Low must never read "Cheapest in 12 months".
  - **The channel reports switched too (same day)**: `discord_reports.py` ranks and
    quotes Low (`REPORT_PRICE_COL` / `REPORT_PCT_PREFIX` / `REPORT_DAILY_COL`), the
    stale check compares today's `low_price`, and the weekly picture strips draw the
    Low trend. **⚠ A section's price floor now holds at BOTH ends of the window**
    (`qualifies`), the home banners' rule: on Low, a $0.50 -> $6.00 card read "+1100%"
    and led the base section in the first preview. The standing notes and the shared
    digest (`discord_digest.PRICE_COL`) stay on Market.
- **`/card` with a drawn tile prints no prices** — no Low/Market line, no 1D/1W/1M, no
  other finish. The tile carries them. Without a tile (no TCGplayer listing, a graded
  ask, an eBay-led promo) the text lines are still there.
- **The 🏆 play line counts the CURRENT set only**: "In 14% of Attack of the Vine!
  top-cut decks · #39 most played". The index build stores `ps` per card (Core top-cut
  decks from events on or after the newest released booster set's LGS date, unweighted)
  and `index.playSet {n, since, decks}`. Under `PLAY_SET_MIN_DECKS` (8) decks there is
  no line at all, so the first week of a set says nothing rather than quoting the old
  meta. `/meta`'s card list ("Most played in <set>") reads the same counts.
  - **`pl` (recency-weighted, every format) stays the resolver's popularity prior** —
    it decides which Mowgli "mowgli" means, and it must not go empty on release day.

### 2026-10-04 (later): /card is the picture, and the picture is WIDE

Zaven: *"people mostly want to see the card nothing else for /card"*, and *"make the
card art tile much bigger"*.

- **The card view drops the ink / cost / type line, the stats line and the rules
  text** — all printed on the card. It keeps the set line and the 🏆 play line.
  `/price` keeps the ink line. `rulesText` stays (tested) but no reply uses it now.
- **⚠ Discord fits an embed image inside a ~400 x 300 box**, so the site's portrait
  tile (about 1:2) rendered ~150 px wide. `bake_tiles.mjs` `compactTile()` draws a
  portrait card for Discord as the art at ~248 of the 300 px (was ~190), with a
  two-row price table UNDER it: LOW / MKT, price, 1D / 1W / 1M — the site's own
  `fmt`, `fmtPct`, `posterPctColor` and `drawImageCover`. Name, rarity and date are
  left out of the picture: the embed already says them. A first cut put the prices
  BESIDE the art (4:3, art ~283 px); Zaven wanted them back under it. The canvas
  may be wider than the art (the box is height-bound below 4:3, so width is free).
  A Location's tile (already landscape art) keeps the site's `drawCardTileCanvas`.
  - Nothing tests the drawing in CI (no canvas there) — render one tile and LOOK,
    including a four-figure price and a `+15x` change.

### The channel report's layout (2026-09-28)

Zaven, on the first live report: *"foil prices aren't super important, base
cards and chase cards are relevant, foil can be its own section."* One list
ranked by percent was mostly $5 foils jumping 30% on one sale, and it called
Epics and promos "(foil)". Mocked up, then built. Guarded by
`python scripts/test_discord_reports.py`, which reads `TCG_AFFILIATE_BASE`,
`tcgUrl` and `SET_DISPLAY_NAMES` back out of Index.html.

- **Sections by kind of card** (`SECTIONS`): **Chase** (Enchanted / Epic /
  Iconic) and **Promos** rank by DOLLARS — a $2,839 Iconic up $145 is +5.4%
  and ranked 19th by percent; **Base cards** (non-foil) and **Foils**
  (base-rarity foils only) rank by percent. `bucket_of` never files a chase or
  promo card as a foil: it is one printing (the `printingBadge` rule).
- **Every section has a price floor AND a minimum dollar move** ($10/$2 for
  chase and promos, $5/$1 for base and foils): "raise the floor" (Zaven). A
  quiet day's base section can be one line, which is the honest answer.
- **The weekly adds the bigger trends**: the header's pulse (whole market,
  chase cards, sealed — week and month; hottest and coolest set; the rarity
  that moved most) from `market_index_daily`, a chart since the newest set came
  out, a picture strip of the top 4 chase and base movers, and **Worth a look**
  (fell this week AND at a multi-month low, pulled out of the other sections).
  **⚠ No pulse when the index is not current for the price date** — the ETL
  refreshes it with the prices, but optionally, and a stale index would report
  yesterday's market as today's. A set index narrower than 100 cards is a promo
  run, not a set, and stays out of hottest/coolest.
- **The pictures are drawn by `scripts/discord_report_art.py` (Pillow) and
  ATTACHED** (multipart, `attachment://<name>.png`). Fonts are committed under
  `scripts/fonts/` (SIL OFL), so CI never downloads them. Every drawing
  function returns None instead of raising, and a multipart post Discord
  refuses (400) is re-sent as text: a picture must never cost the post.
- **⚠ Every card link is ~160 characters** (the affiliate URL), and a message's
  embeds may hold 6,000 in total, so `fit_embeds` trims lines from the LAST
  sections (foils first) until it fits. The header is never trimmed and the
  disclosure footer moves to whatever embed ends up last.
- **Two short sections close the report** (2026-09-30): **New cards** (daily: names first added in the
  last day; weekly: the last seven; a new printing of an existing name is not a reveal) and, weekly
  only, **This week on the calendar** (confirmed `calendar_events` rows starting in the next seven
  days, plus the set and product dates parsed out of Index.html's `SET_RELEASE_DATES` /
  `PRODUCT_RELEASE_DATES`, which a curated row replaces). Both are `_keep`, so trimming for length
  takes price lines first, and every read is wrapped: a failure leaves the section out, never the
  report. Calendar links go to `packs.ink/calendar?ce=<id>`, the one non-affiliate link allowed.
- **Links go to TCGplayer through the affiliate link** (`tcg_url`, the site's
  `tcgUrl` exactly), never to packs.ink card pages (Zaven, 2026-09-28).
- `python scripts/discord_reports.py --preview <dir>` builds both reports from
  live data (read-only) and writes the JSON and pictures to `<dir>`.
