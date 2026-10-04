# Packs.Ink Discord bot

Card lookups, prices, charts, the meta, events and the Lorcana calendar, in
Discord. A Cloudflare Worker that answers Discord's HTTP interactions — no
server to keep running, and a **separate Worker from the site** (`packs-ink-discord`
on workers.dev), so deploying it can never touch packs.ink.

## What it does

| | |
|---|---|
| `/card mowgli` | The site's card tile (the art, Low / Market and the 1D / 1W / 1M changes, drawn by the site's own code — the reply doesn't repeat those prices in text), with the card's rules text and stats as printed, graded sales, its ink / cost / type, and how much it's played in the current set's tournament top cuts. |
| `/price mowgli` | The number: price, changes, the other finish, a playset's cost on a played card, and a price chart (1M / 3M / 1Y / All buttons) — the rules text stays on `/card`. |
| `/price elsa psa 10` | Graded: that grade's last sale (with its date) and average of the last 5 lead, the raw price follows, every other grade is a field, and the chart is the PSA 10 sales. |
| `/price azurite sea box` | Sealed product: price, changes, chart, TCGplayer + Amazon links. A booster box adds the set's box EV ("worth about 50% of the box"), an **Open a box** button and **Set at a glance**. |
| `/set azurite` | A set at a glance: release dates, booster box price vs box EV (the site's own EV maths) with an open-or-hold verdict, chase cards, sealed prices. |
| `/new` | The newest cards: everything added to packs.ink in the last four days (the site's reveal reel), grouped by day, with a picture grid and a menu to open any of them. Cards added since the bot's daily rebuild are included. |
| `/open` | Open a simulated booster pack — or `box: True`, a whole box — with the site's pull rates and real prices. |
| `/meta` | What's winning: every top-8 deck since the newest set came out, by ink pair (share, top 4s, wins); the most-played cards; and the top four of the three biggest events of the last three weeks, with links to their decks. |
| `/events 60614` | Near a postal code or town: Set Championships, prereleases (nearest first, seats and fees), and weekly play one line per store, each linking to its page on packs.ink. Buttons change the kind and the radius. |
| `/calendar` | Set releases, Challenges and qualifiers by month, each linking to its page on packs.ink (which links on to the organiser); buttons and a menu narrow the kind and the region. |
| `/help` | What it does, with clickable commands and "Try it" buttons. |
| `/reports daily` | (Server managers) the daily movers report, posted into a channel; `weekly` on Mondays. |
| `/reports send` | (Server managers) post the latest daily or weekly report here, now. |

**Names are forgiving by design.** `mowgli`, `mogli`, `moglie`, `how much is
mowgli` all find Mowgli; with no subtitle you get **the version people actually
play** (recency-weighted appearances in tournament top-cut decks), and every
reply has a menu of the card's other printings and the character's other
versions. Collector words (`enchanted`, `epic`, `psa 10`) switch the tiebreak to
what gets traded instead. Rarity, foil, set, ink and collector-number words
filter (`elsa enchanted`, `moana foil`, `elsa #42`, `mickey brave little tailor
promo`); a sealed word (`box`, `trove`, `gift set`) finds product.

It cannot be @mentioned in chat: reading ordinary messages needs a 24/7 gateway
connection (a server), which this deliberately isn't. Slash commands cover the
same ground.

## Setting it up (once)

1. **Create the application** at <https://discord.com/developers/applications>
   → New Application → "Packs.Ink".
   - General Information: copy the **Application ID** and the **Public Key**.
   - Bot → Reset Token → copy the **token**. It is a password for the bot
     account: paste it only into GitHub's secret box, never into a chat.
   - Installation: tick **Guild Install** and **User Install** (User Install lets
     people use it in any server or DM without the bot joining).
2. **GitHub → Settings → Secrets and variables → Actions → New repository secret**:
   - `DISCORD_APPLICATION_ID`, `DISCORD_PUBLIC_KEY`, `DISCORD_BOT_TOKEN`
   - Nothing extra for `/reports`: the workflow hands the bot the repo's
     existing `SUPABASE_SERVICE_KEY` (a `DISCORD_BOT_SUPABASE_KEY` secret, if
     you ever add one, overrides it). It does need
     `supabase/173_discord_reports.sql` applied, and
     `supabase/175_discord_report_latest.sql` for `/reports send`.
   - `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` already exist for the site.
3. **Cloudflare**: the account needs a workers.dev subdomain (Workers & Pages →
   the subdomain shown on the overview). The first deploy fails and says so if
   there isn't one.
4. **Actions → Discord bot → Run workflow**, with **set_endpoint** ticked. It
   builds the card index, deploys, copies the secrets into the Worker, registers
   the commands, points Discord's Interactions Endpoint URL at the Worker, and
   proves the endpoint refuses an unsigned request.
5. **Add it**: open `https://packs-ink-discord.<subdomain>.workers.dev/invite`,
   or share the Installation tab's install link.

After that it redeploys itself every day after the price ETL (the card index
has to follow the catalog), and `Discord reports` posts the subscribed reports.
The reports run whenever an ETL run finishes, not only on GitHub's schedule,
which has been starting this repo's evening jobs 2-3 hours late. A day's report
can go out until noon UTC the next day, and never twice to one channel.

## How it works

```
discord/
  src/index.js          Worker entry: /interactions, /chart/..., /invite, /
  src/verify.js         Ed25519 request signatures (+ 5-minute replay window)
  src/interactions.js   commands, buttons, menus, autocomplete — deferred + PATCH
  src/resolver.js       plain-English fuzzy card/sealed/set lookup
  src/text.js           normalisation + bounded edit distance
  src/set.js            /set (overview, box EV), /open (simulated packs) and /new (reveals)
  src/data.js           the Supabase reads (prices, graded, the meta, events, calendar, new cards)
  src/db.js             PostgREST over fetch
  src/embeds.js         Discord message payloads (pure)
  src/charts.js         the /chart routes Discord's image proxy fetches
  src/chart.js          a tiny rasteriser + baked Nunito Sans glyphs
  src/png.js            PNG with a fast fixed-Huffman deflate
  src/site.generated.js the site's own helpers, copied verbatim (see below)
  src/card-index.json   built daily, not committed
  src/command-ids.json  {command: id} from registration, for clickable /help (not committed)
  tools/build_index.mjs builds the index by running the SITE's catalog transform
  tools/bake_art.mjs    card art Discord can show, for printings TCGplayer hasn't listed
  public/art/           that art, served as the Worker's static assets (not committed)
  tools/bake_tiles.mjs  the site's card tile, drawn for every priced finish (+ tile_rules.mjs)
  public/tile/          those tiles, served the same way (not committed)
  src/tile.js           the tile file name + URL, shared by the build and the Worker
  tools/extract_site.mjs regenerates site.generated.js from Index.html
  tools/bake_font.py    regenerates font.generated.js
  tools/commands.js     the slash commands; register_commands.mjs publishes them
  tools/simulate.mjs    runs the real Worker locally against signed fake requests
```

- **The site's rules, not a copy of them.** `build_index.mjs` parses Index.html
  with acorn and runs the site's own `transformSupabaseData` (Holofoil mislabels,
  connecting foils, C2 ghost rows, regional exclusives, variant clones…) in a
  Node sandbox, so the bot names and prices a printing exactly as the site does.
  `site.generated.js` is the same idea for runtime code (price changes, "Cheapest
  in 12 months", affiliate links, the calendar, the postal-code walk): copied
  verbatim, and `scripts/test_discord_bot.mjs` fails when a copied statement no
  longer matches Index.html. Re-run `npm run site` after changing one.
- **Discord gives an interaction 3 seconds**, so everything that reads the
  database answers "thinking…" at once and edits the reply when the data is in.
- **The card index is parsed at startup**, which Cloudflare budgets separately
  from each request's CPU; a lookup itself is well under a millisecond.
- **Charts are drawn by the Worker** (no canvas in a Worker): ~5 ms for an
  800×340 PNG. The URL carries the price date, so Discord re-fetches it when the
  day's prices change and an old message keeps the chart it was sent with.
- **Card art is TCGplayer's photo, or art baked for the Worker.** Discord shows
  no AVIF (Lorcast's only format) and rejects a whole reply whose image is a
  `data:` URI or a relative path, so a card TCGplayer hasn't listed yet (a new
  set before release, a regional promo) used to arrive with no picture.
  `bake_art.mjs` converts those to WebP at deploy time (sharp) into
  `public/art/`, which wrangler serves at `/art/<id>.webp` without running the
  Worker. `check_index.mjs` refuses an index that points at a missing file or an
  image Discord can't show. `build_index.mjs --no-art` skips the download.
- **`/card` shows the site's own card tile.** `bake_tiles.mjs` runs the site's
  `drawCardTileCanvas` (pulled out of Index.html like the rest) on a Node canvas
  (`@napi-rs/canvas`), for every priced finish, in the default dark theme read
  out of styles.css, with prices and changes from the site's own
  `computeSeriesDeltas` as of the index's price date. ~5,800 tiles, ~275 MB,
  written to `public/tile/` and served without running the Worker; the URL
  carries `?d=<price date>` so Discord fetches the new day's tile. A graded
  reply, a raw-eBay promo and a finish with no tile keep the plain picture.
  Nothing about the tiles can fail a build — a card with none just shows its
  picture. The art they are drawn from is cached in `.tile-art-cache/`
  (actions/cache in CI). `--no-tiles` skips them; `--no-art` does too.
- **Every picture the bot makes is UPLOADED with the reply, not linked**: the
  tile, baked art and the price charts. Linked, Discord dropped them from some
  edits (the first `/card` reply, the Price chart button) and only showed them
  after a later edit. `withUploads` in `interactions.js` reads files through
  the `ASSETS` binding and draws charts with `chartResponse`; anything it can't
  produce keeps its link, and a refused upload is re-sent with the plain link.
  `node tools/simulate.mjs` prints `uploaded:` for each file it catches.
- **Every TCGplayer link is the affiliate link** (`tcgUrl` / `tcgSetSearchUrl`,
  copied from the site): the product page when TCGplayer lists the printing, a
  TCGplayer search for the name when it doesn't. Every message carrying one
  says "Links may earn packs.ink a commission" in its footer, and the guard
  fails a reply that doesn't.
- **Nothing it says can ping anyone** (`allowed_mentions: {parse: []}` on every
  message), because a reply can echo what somebody typed.
- **Sized for the free Workers plan's 10 ms of CPU per request.** The resolver
  precomputes what it can at startup and is warmed there (startup has its own,
  larger allowance); a lookup is ~0.1–0.6 ms.
- **A reply Discord refuses is re-sent as plain text**, so nobody is left on
  "thinking…". A button's failed update goes to the clicker privately.
- **Box EV and the /meta play shares are computed in the daily index build**
  with the site's own code (`processData`/`calcEV`), so those need no database
  read.
- **/meta's ink-pair breakdown is one read** of `tournament_results_v`: every
  top-8 deck since the newest set already on shelves (`metaSet`), Core only,
  grouped by ink pair — `deck_name` is empty on most tournament decks, and the
  inks are exact. Under three events since the set it widens to the last 45
  days and says so. "Latest big events" are the three biggest of the last three
  weeks that recorded at least four decks (a winner-only record is a stub).
- **A card's rules text comes from the index** (`x`, the newest booster
  printing's wording, with `st` strength / willpower / lore / move and `ik`
  inkable): ability names bold, keywords bold with their number, reminder text
  italic, the `{I}` / `{E}` symbols as words.
- **/reports send posts a stored report.** `scripts/discord_reports.py` keeps
  the day's daily and weekly report in `discord_report_latest` (migration 175)
  with its pictures in the public `discord-reports` bucket under a dated path;
  the Worker reads the row and uploads the pictures with its reply. A refusal
  (not a manager, not switched on) is private and immediate.
- **/new runs the site's reveal reel when someone asks.** The daily build
  stores the reel's inputs (every card inside the window, and when each card's
  name was first seen); the Worker runs the site's `revealRotation` over them
  plus any card added since the build, read from `cards` and put through the
  site's catalog rules. Reveals land all day and the index is built once, so a
  reel frozen at build time ran up to a day behind the site. A reprint is left
  out, as on the site; if that can't be checked, nothing just added is shown.
  A card links to TCGplayer only when its printing has a listing of its own: a
  card still being revealed has none, and a search link on every line left room
  for 13 of 36 reveals.
- **Boards are browsed, not re-typed**: /events and /calendar carry
  their state in each control's custom_id and redraw in place. Every control
  in a message has a DIFFERENT custom_id — Discord refuses a message with two
  the same, and the guard checks every reply for it.
- **Commands are registered before each deploy**, so their ids can be bundled
  (src/command-ids.json) and /help can show them as clickable mentions; the
  interactions endpoint is set after the deploy (Discord pings it first).

## Working on it

```bash
cd discord && npm ci
node tools/build_index.mjs          # live index (public read-only key)
node tools/simulate.mjs             # the real Worker, locally, end to end
node ../scripts/test_discord_bot.mjs
```

`simulate.mjs` starts `wrangler dev` with a throwaway key pair, signs requests
the way Discord does, and captures the replies the Worker would send to Discord
(saved under `.wrangler/sim/`). Nothing reaches Discord.
