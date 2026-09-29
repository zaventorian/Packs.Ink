# Packs.Ink Discord bot

Card lookups, prices, charts, movers, events and the Lorcana calendar, in
Discord. A Cloudflare Worker that answers Discord's HTTP interactions — no
server to keep running, and a **separate Worker from the site** (`packs-ink-discord`
on workers.dev), so deploying it can never touch packs.ink.

## What it does

| | |
|---|---|
| `/card mowgli` | The site's card tile (the art, NM Market / Low and the 1D / 1W / 1M changes, drawn by the site's own code), with graded sales, its ink / cost / type, and how much it's played in recent tournament top cuts. |
| `/price mowgli` | The same, as a price chart (1M / 3M / 1Y / All buttons), card art as a thumbnail. |
| `/price elsa psa 10` | Graded: every grade's last sale and average of the last 5, and a chart of the PSA 10 sales. |
| `/price azurite sea box` | Sealed product: price, changes, chart, TCGplayer + Amazon links. |
| `/trade` | Is a trade fair? Both sides priced (each card at the version named — `enchanted elsa` is the Enchanted), sealed and cash too, a verdict in words, and a button that opens it in the site's Trade Compare. Type both sides inline (`give:` / `get:`) or leave them empty for a box. |
| `/deck` | Opens a box: paste a decklist, get what it costs to build (each card at its cheapest printing, NM Market and Low) and one TCGplayer cart for the whole list. |
| `/set azurite` | A set at a glance: release dates, booster box price vs box EV (the site's own EV maths) with an open-or-hold verdict, chase cards, sealed prices. |
| `/new` | The newest cards: everything added to packs.ink in the last four days (the site's reveal reel), grouped by day, with a picture grid and a menu to open any of them. Cards added since the bot's daily rebuild are included. |
| `/open` | Open a simulated booster pack — or `box: True`, a whole box — with the site's pull rates and real prices. |
| `/movers` | A board of the biggest gains or drops: buttons switch 1D–1Y, gains/drops and NM Market/Low; a menu switches rarity group, or sealed product. |
| `/meta` | The most-played cards in recent tournament top cuts, and the top four of the latest events with links to their decks. |
| `/events 60614` | Near a postal code or town: Set Championships, prereleases (nearest first, seats and fees), and weekly play one line per store. Buttons change the kind and the radius. |
| `/calendar` | Set releases, Challenges and qualifiers by month; buttons and a menu narrow the kind and the region. |
| `/help` | What it does, with clickable commands and "Try it" buttons. |
| **Apps → Price check** | Right-click any message: a trade post (`H: … W: …`) is priced as a trade, a decklist as a deck, anything else card by card. |
| `/reports daily` | (Server managers) the daily movers report, posted into a channel. |

**Names are forgiving by design.** `mowgli`, `mogli`, `moglie`, `how much is
mowgli` all find Mowgli; with no subtitle you get **the version people actually
play** (recency-weighted appearances in tournament top-cut decks), and every
reply has a menu of the card's other printings and the character's other
versions. Collector words (`enchanted`, `epic`, `psa 10`) switch the tiebreak to
what gets traded instead. Rarity, foil, set, ink and collector-number words
filter (`elsa enchanted`, `moana foil`, `elsa #42`, `mickey brave little tailor
promo`); a sealed word (`box`, `trove`, `gift set`) finds product.

It cannot be @mentioned in chat: reading ordinary messages needs a 24/7 gateway
connection (a server), which this deliberately isn't. Slash commands and the
Price check menu cover the same ground.

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
     `supabase/173_discord_reports.sql` applied.
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
  src/trade.js          /trade and trade posts: parse, price, verdict, site link
  src/set.js            /set (overview, box EV), /open (simulated packs) and /new (reveals)
  src/data.js           the Supabase reads (prices, graded, movers, events, calendar, tournaments)
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
- **Movers drop stale rows.** `price_movers` repeats a SKU's last change after
  its listing disappears; a mover only counts when `prices_daily` holds the same
  price for it on the newest date. `scripts/discord_reports.py` does the same.
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
- **A tile or baked picture is UPLOADED with the reply, not linked.** Linked,
  Discord dropped it from the first edit of a deferred `/card` reply and only
  showed it after a later edit (a button press). `withUploads` in
  `interactions.js` reads the file through the `ASSETS` binding and sends it as
  an attachment; a refused upload is re-sent with the plain link. Charts stay
  links. `node tools/simulate.mjs` prints `uploaded:` for each file it catches.
- **Every TCGplayer link is the affiliate link** (`tcgUrl` / `tcgSetSearchUrl`,
  copied from the site): the product page when TCGplayer lists the printing, a
  TCGplayer search for the name when it doesn't. Every message carrying one
  says "Links may earn packs.ink a commission" in its footer, and the guard
  fails a reply that doesn't.
- **Nothing it says can ping anyone** (`allowed_mentions: {parse: []}` on every
  message), because a reply can echo what somebody typed.
- **Sized for the free Workers plan's 10 ms of CPU per request.** The resolver
  precomputes what it can at startup and is warmed there (startup has its own,
  larger allowance); a lookup is ~0.1–0.6 ms, a trade ~2 ms, a long chat
  message ~4 ms. Anything that searches or resolves many names is capped.
- **A reply Discord refuses is re-sent as plain text**, so nobody is left on
  "thinking…". A button's failed update goes to the clicker privately.
- **Box EV, sealed movers and the /meta play shares are computed in the daily
  index build** with the site's own code (`processData`/`calcEV`,
  `computeSealedDeltas`), so those replies need no database read.
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
- **Boards are browsed, not re-typed**: /movers, /events and /calendar carry
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
