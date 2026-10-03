# Amazon Associates (approved 2026-09-10, tag `packsink-20`)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Amazon **complements** TCGplayer here rather than competing with it, and the split is
clean enough to state as a rule: **TCGplayer owns singles, Amazon owns everything
TCGplayer barely stocks** — sealed gift sets, the Ravensburger jigsaw puzzles, and above
all **accessories**, a category the site had never monetised at all. So an Amazon link is
ADDED beside a TCGplayer one, never in place of it.

### ⚠ LINK-ONLY TODAY — because we have no API keys, NOT because prices are banned

An earlier version of this section said prices could never be shown and images could
never be used. **That was wrong**, and the correction matters because it changes what is
worth building later. The actual terms:

- Every Amazon price, image or product fact displayed on a site must be **Program Content
  fetched from Amazon's own API**. PA-API 5 was retired **2026-05-15**; the **Creators
  API** replaced it.
- **Non-image content, prices included, may be cached for up to 24 HOURS**, and must be
  refreshed by a fresh API call immediately after.
- An **image may not be stored or cached at all**, but a **link** to one may be held for
  up to 24 hours — i.e. you hot-link Amazon's CDN. Never our storage, never `/img-proxy`.
- A displayed price must carry its **"as of" timestamp** and a buy link to the detail page.
- **Scraping is prohibited outright** by Amazon's Conditions of Use ("data mining, robots,
  or similar data gathering and extraction tools"). There is no non-API shortcut, and a
  scraper would risk the affiliate account itself for data the API hands over free once we
  qualify. Do not build one; do not buy a third-party Amazon scraping API either — the
  Operating Agreement is about where the *displayed* content came from, not who fetched it.

So the reason no AMAZON price or photo appears on the site is simply that **we hold no
Creators API keys**. `scripts/test_amazon_links.mjs` asserts the static catalog holds
nothing but ASINs, keys and TCGplayer ids — that guard is against somebody hand-copying a
price or image off a listing, which is the unlicensed use that actually costs accounts. It
is not a vow of poverty about prices in general.

**⚠ The photos and prices you DO see on Amazon-linked tiles are TCGplayer's (2026-09-10).**
Zaven asked for pictures and prices "even if we have to source them ourselves". Sourcing
*Amazon's* ourselves — scraping, or copying them off listings — is exactly the prohibited
path above, so the answer was to source OUR OWN: TCGplayer's catalog photo of the same
product (the images the Sealed pages already show; the host is already in `img-src`) and
TCGplayer's market price from our daily ETL, **labelled as TCGplayer's on every surface**.
The rule governs Amazon's content, not TCGplayer's photo of the same box, so this is not a
loophole. What a tile can never say is *Amazon's* price or stock: it shows "TCGplayer
market $X" beside a "Buy/Find on Amazon" button, never "$X on Amazon".

**⚠ Sources are secondary.** Every amazon.com / webservices.amazon.com /
affiliate-program.amazon.com domain is egress-blocked from the agent sandbox, so the
clauses above were assembled from search results quoting the licence, not read from the
primary document. Confirm the exact wording in Associates Central before building against
it.

### Two different sale thresholds — don't conflate them

| Bar | What it gates | Reported figure |
|---|---|---|
| **Account probation** | Keeping the Associates account at all | **3 qualifying sales in 180 days** from approval (so by ~2027-03-09) |
| **Creators API access** | Prices, photos, any Program Content | **10 qualifying sales in 30 days** |

The first is why **Gear exists now and is not a "later"** — a $12 pack of sleeves is an
impulse buy, a $120 booster box is a considered purchase, and only sales stop the clock.
The second is the gate on ever showing a price.

### When the keys do land — the design that stays compliant

Not built, deliberately: there is nothing to test against without keys. But the shape is
constrained enough to write down, because the obvious implementation is the
non-compliant one.

- **A daily refresh fits.** The 24h ceiling lines up with the existing ETL cadence
  (20:30 UTC), so an `etl.yml` job calling the Creators API once a day is the natural
  home — the same shape as `etl_tcgcsv_daily.py`.
- **⚠ But `ETL → Supabase → localStorage` is exactly what breaks it.** The catalog cache
  has a 24h TTL *with background refresh*, aux caches run 12h, and the offline mirrors
  have **no ceiling at all** — a client that goes offline serves saved data indefinitely.
  An Amazon price written through the normal path would therefore outlive its 24h licence
  on any offline or long-idle client, silently. So:
  - Amazon prices must **never** enter `readCache`/`writeCache`, `offlineMirrorWrite`, or
    any `packsink:*` aux cache.
  - Store the fetch timestamp beside the price and **hide the price client-side once it is
    over 24h old**, rather than trusting the refresh to have happened.
  - Images are **hot-linked from Amazon's CDN**, never proxied — which also means the
    `img-src` list in `_headers` needs their image host added, and the SW's image-caching
    branch must be taught to skip it (it currently caches every `destination === "image"`,
    which would be storing the image).
- Each price needs its as-of stamp and a buy link rendered with it.

### How a link is resolved

`amazonForSealed(product, setName)` → `{url, exact}`, three passes, cheapest first:

1. **A token rule** (`AMAZON_SEALED_RULES`) — for one-of-a-kind products (gift sets, the
   collector's editions) and for starter decks, which come **two per set** and so cannot be
   addressed by set alone. First match wins, so the specific rule goes above the general one.
2. **Set × display type** (`AMAZON_ASIN_BY_SET`) — the reliable bulk of it, since
   `deriveSealedDisplayType` already classifies every row. A new set is one line.
3. **A tagged search** on the product's own name. A search URL commissions exactly like a
   product URL, so coverage is 100% from day one and each curated ASIN merely upgrades a
   product from "the right shelf" to "the right box".

- **⚠ Rules match on TOKENS, never on a whole name.** The names are TCGplayer's, the ASINs
  are Amazon's, and the two houses punctuate differently ("Disney Lorcana: Azurite Sea -
  Collector's Gift Set" vs "Azurite Sea Stitch Collector's Gift Set"). An exact-key map
  would look correct and match nothing.
- **`exact` decides the LABEL, and that matters.** A curated ASIN says "Amazon"; a search
  says "**Find on** Amazon", because a search cannot promise the product page it lands on.
- **⚠ A set name typo'd against `MAINLINE_SETS` can never match** — that set silently
  serves a search link forever while looking curated. The guard test cross-checks every key.
- **⚠ A case or display never takes a rule's ASIN.** Rules match tokens, so "Fabled
  Collection Starter Set **Case**" matched the single set's listing. `amazonForSealed` skips
  the rules when `deriveSealedDisplayType` says `Cases` / `Other Displays / Cases`.
- **The rules were checked against the LIVE catalog (2026-09-10) and three were wrong.** The
  unscoped `["collection starter"]` sent Attack of the Vine!'s Rapunzel Edition to the Fabled
  listing (now `["fabled", "collection starter"]`); `["azurite", "stitch"]` never fired,
  because TCGplayer calls it plain "Stitch Collector's Gift Set" (now `["stitch", "gift
  set"]`); `["d100"]` never fired against "Disney100 Collector's Edition". The check that
  found them resolves every `sealed_prices_latest` row and prints any two rows landing on one
  ASIN — re-run that whenever a rule is added, because a wrong rule looks exactly like a
  right one.

### Where it is wired

- **Sealed detail modal** — a secondary outlined button beside TCGplayer's filled one.
- **EV tool's box-price row** — a small link under the price. This is the one moment on the
  site where somebody has just been told cracking is +EV, so a box link answers the question
  actually on screen. **No price beside it** — that column is a TCGplayer number.
- **Puzzle tiles** — the tile's link now goes to Amazon. Its old `buy_url` was
  ravensburger.us's whole-**category** landing page: not the product, and not monetised, so
  Amazon wins on UX and revenue at once. The Ravensburger link stays in the modal for the two
  Disney-Store exclusives. **Pins and lore counters are NOT sold** (`buy_url` null by design)
  and stay linkless — a checklist is what a collector wants there.
- **Gear** (`LORCANA_GEAR`) — a catalogue of sleeves / portfolios / deck boxes / grading
  supplies, rendered on `/gear`. It **used to have a right-rail home panel too** (`GearPanel`,
  its `.home-gear-*` CSS, and a `home: true` flag choosing which sections it showed); all of
  that is **DELETED 2026-09-12** at Zaven's request. Once the "Lorcana on Amazon" row shipped
  the panel was the page's second Amazon prompt, reaching a place the row's own title already
  reaches. `normalizeHomeLayout` drops a key it doesn't recognise, so a browser holding `gear`
  in its stored layout repairs itself on the next load — no migration, no stamp. Don't re-add
  a `home:` flag to `LORCANA_GEAR`; nothing reads it, and the guard test now fails if one
  reappears rather than passing vacuously.
- **Sealed product has an Amazon twin; a CARD never does (2026-09-13).** Every "buy on
  TCGplayer" control gained an Amazon link beside it on 2026-09-10, and the per-CARD half was
  **removed** three days later at Zaven's request: Amazon does not carry Lorcana singles, so a
  search for one lands on a page of booster boxes or on somebody's third-party lot. It earned
  nothing and it made the site look like it did not know what it sells.
  `amazonCardSearchUrl` and `AMAZON_CARD_RARITY_WORDS` are gone with their six call sites —
  the card popup's Price-changes rows, Graded collection tiles, Playset Cost rows, Trade
  Compare printings, the movers-tile corner, and the Screener's card rows — and the three
  card-only CSS rules (`.playset-amzn-btn`, `.cd-stat-buy--amazon`, `.trade-pr-link--amzn`).
  Two affiliate notes narrowed to TCGplayer-only with them (`.cd-affiliate-note` and the
  graded view's `.sealed-coll-affiliate`), so the Associate string is no longer claimed on a
  surface that no longer links to Amazon.
  **⚠ Nothing errors if a card link comes back** — it just quietly resumes sending readers to
  the wrong shop — so `test_amazon_links.mjs` asserts both that the helper does not exist and
  that no card surface renders an Amazon link. That is the part that makes it stop.
- **What KEEPS its Amazon twin**, every one of them sealed or product: the Sealed detail
  modal, Sealed collection tiles, the Screener's SEALED rows (`isSealedRow`-gated), the Price
  Graphing single-product preview (sealed only), both EV box prices (`.ev-box-amzn`,
  `.home-ev-amzn`), the home "Lorcana on Amazon" shelf and `/gear`. `.td-amzn-link`,
  `.gc-card-buy--amazon` and `.mt-amzn-link` are still live for exactly those — don't sweep
  them as orphans.
  **Deliberately NOT twinned:** a *price* that merely happens to be a TCGplayer link (Cards
  list rows, set-detail rows, deck tile price chips, pack-sim results) — doubling every
  price chip would bury the prices — and TCGplayer's mass-entry "shop missing" buttons,
  which Amazon has no equivalent for.

### `/gear` — the directory page

A real SPA view (`GearView`, `VIEW_PATHS.gear`), listing every Amazon link we hold: boxes,
troves, single packs, starter decks, gift sets, puzzles, then the accessories. ~59 links.

- **⚠ It is BUILT from the resolver's own maps (`amazonDirectory()`), never hand-listed.**
  A second list of ASINs would drift from the first, and the guard test's "no ASIN used
  twice" check would NOT catch it — a duplicate across two lists that are meant to agree
  is not a duplicate, it is a fork. The test instead asserts **every curated ASIN appears
  on the page** and **the page invents none**, in both directions.
- `AMAZON_SEALED_RULES` entries carry `group` (`gift` | `deck`) and `label` purely so the
  directory can name them — a page has no `sealed_products` row to hand the resolver.
  A rule missing either is silently dropped from the page, so the test names that cause
  directly rather than letting it surface as a missing ASIN.
- **Sets run newest-first** (`MAINLINE_SETS` reversed): somebody shopping wants the current
  set, not The First Chapter.
- **Product cards with photos (2026-09-10).** A sealed row's photo, TCGplayer price and
  TCGplayer twin come from `amazonSealedMatches()`, joined by Amazon URL; an accessory's
  come from its `tcg` field — the TCGplayer product id of the pictured item (on a search
  row, one representative of the line). **Ids, never URLs**: `tcgProductImg(id)` builds the
  image at render, so the catalog still holds nothing a hand-copied listing image could hide
  in. No `tcg` means TCGplayer doesn't carry it, and the card shows its section glyph (`box`,
  `sleeve`, `binder`, `deckbox`, `slab`, `toploader`, `mat`, `storage`, `puzzle` in
  `UI_ICON_PATHS`). The glyph is drawn UNDER the `<img>` and `hideBrokenImg` hides a failed
  image by style, so a product TCGplayer has no photo for yet degrades to the glyph.
- The note above the grid says whose photos and prices they are, with the ETL date.
- **Two section notes printed raw backslash-u escape codes** (for the curly quotes, the
  non-breaking spaces and the inch marks) until 2026-09-10 — the source held
  double-backslashed escapes inside plain JS strings. Real characters now.
- Needs **no worker or dev_server route** — both already SPA-fallback unknown paths, so
  `VIEW_PATHS` + `VIEW_TITLES` + a line in `sitemap.xml` is the whole routing change.

### Product photos cut out of their white sweep (2026-09-12)

TCGplayer shoots sealed product on a white sweep and serves JPEG, so every photo arrives as
a product **in a white box** — which on the velvet/aurora/black themes is a bright rectangle
in the middle of a dark page, and is what Zaven objected to about the Amazon row. There is no
transparent source to switch to: the CDN serves `.jpg` only (a `.png` variant 403s).

**`cutProductWhiteBg` removes it in the browser**, and `ProductPhoto` is the one accessor that
renders a product photo — used by the home Amazon row, `/gear`'s cards and the admin checklist.
Same algorithm as `scripts/cut_collectible_bg.py`, which does this to the pin and lore-counter
photos before upload, and for the same two reasons it works there: the background is found by
**flood fill from the BORDER** (never "white → transparent", which punches through every white
logo and highlight inside the product), and the subject is **eroded one pixel** first, because
a JPEG of a dark object on white carries a ring of genuinely half-white pixels that reads as a
bright fringe. Doing it client-side rather than in a script is what makes it maintenance-free:
a new set's boxes are cut the first time anyone looks at them, nothing to re-run, nothing to
upload. Measured on the live shelf: **50 of 52 loaded photos cut**, the other two a full-bleed
box shot that correctly declined.

- **⚠ It MUST be able to decline, and the two failures want OPPOSITE grounds.** All four
  corners are tested first, and the fill is thrown away if it removed almost nothing or almost
  everything. "Not on a white sweep" (a full-bleed shot — the Disney100 Collector's Edition
  fills its frame bar a corner sliver) needs **no** white behind it and looks framed if it gets
  one; "I couldn't read it" (taint, no canvas) **keeps** the white, since the photo probably
  does have a sweep.
- **⚠ `crossOrigin="anonymous"` is only safe on a URL we actually proxy.** A canvas can't read
  back a photo off the bare CDN (neither Lorcast's nor TCGplayer's sends ACAO), so these load
  through `proxyImg` → `/tcg-img-proxy/*`, where the worker sets `ACAO:*`. But asking a host
  that sends **no** ACAO for a CORS image fails the request outright and the photo goes blank —
  which is what it did to the Ravensburger puzzle shots (`ravensburger.cloud`, which `proxyImg`
  does not rewrite). So the flag rides on whether the proxy applied, and an un-proxied photo
  renders uncut.
- **The white ground is on `.prod-photo-wrap`, not on each enclosing well** — one class on the
  element that knows its own state, so a new surface only has to not paint a ground of its own.
  It is ON only for a photo we can inspect (proxied, i.e. TCGplayer, where the sweep is the
  rule): the ground only shows in the margin an `object-fit:contain` photo leaves around itself,
  and a guessed white frame around a full-bleed shot is the worse mistake.
- **`onLoad` alone is not enough.** An image already in the browser cache can finish decoding
  before React attaches the handler, in which case `onLoad` never fires — so the mount effect
  checks `img.complete` too. That silent half is how a returning visitor would have kept seeing
  white boxes.
- One cut per product per session however many tiles show it (`_productCuts`, src → Promise),
  encoded as **WebP with alpha** (PNG holds a photograph at ~5x the size; an older browser hands
  back a PNG blob, which works identically, only bigger) and capped at 420px.
- **The Sealed Movers row and the Sealed collection went the same way on 2026-09-12** — see
  below. `ProductPhoto` is the one accessor for a product photo everywhere now.

### Every sealed photo goes through `ProductPhoto` (2026-09-12)

Zaven, on the Sealed Movers row: *"The images all have white background — can we source or make
it so they don't have that? I guess same in sealed collection."* The row sat **directly above the
Amazon shelf showing the same booster boxes already cut out**, so the page disagreed with itself
one row apart. Three surfaces converted, all to the existing component: the Sealed Movers tile,
the Sealed collection tile, and the sealed branch of `SealedDetailModal` (what those tiles open,
and the biggest white slab of the three at 180px).

- **⚠ The SLOT has to carry its own size now.** `ProductPhoto`'s wrapper is `position:absolute;
  inset:0`, so a well that used to take its height from the `<img>` inside collapses to nothing.
  Each one declares it: the movers tile gets `aspect-ratio:5/7` on `.mt-img-wrap`, the collection
  tile a 56px `.sealed-card-photo`, the modal a fixed 180px square — the same 180x180 the text
  fallback beside it already used, rather than a height the photo's aspect ratio decides.
- **The ground moved to the slot and is the tile's own surface, never white.** `ProductPhoto`
  paints the studio white only while it still has a sweep to hide and drops it the moment the cut
  lands, so a decline keeps whichever answer is right for it.
- **Measured against the live catalog** (154 sealed collection tiles, 26 movers tiles): **131
  cut, 0 left on a white slab**, 13 declined and 9 skipped. Every decline was checked rather than
  trusted — the worst holds **16.9% near-white pixels** and most are under 7%, i.e. genuinely
  full-bleed shots (booster packs, sleeved packs, starter decks) where `CUT_NO_WHITE` is the
  correct branch and a painted ground would look like a frame.
- **The 9 skips are the Ravensburger PUZZLES**, whose photos are on `ravensburger.cloud` —
  un-proxied, so `photo.cors` is false, no canvas read is possible and they render exactly as
  before. Cutting them would mean a worker route for that host, which is a separate decision.
- **Deliberately NOT converted: the Screener's sealed-mode thumbnail.** It rides the shared
  `td-img` path every card row uses, so it needs that render branched on "is this a sealed synth
  row" rather than a component swap — a bigger change than the ask, on the least prominent of
  the four.

### The home shelf — "Lorcana on Amazon" (2026-09-10)

A movers row (`MoversBanner` + `renderTile` → `AmazonShelfTile`), keyed `amazon` in
`HOME_BANNER_KEYS`, default slot right after Promo Movers. Show/Hide is the fixed
`amazonShelf` entry in `HOME_PANELS`, same pattern as Your Graded Movers; ▲▼ place it.

- **`amazonShelfItems(sealedPrices, setNameById)` is pure and guarded.** It admits only
  products the resolver matched to a curated ASIN, plus the NEWEST mainline set's own boxes,
  troves and packs as a search ("Find on Amazon") — a search can't promise stock, so it is
  admitted only for what people shop before we have matched a listing. Cases, promo singles
  and `[Set of N]` bundles never appear. Round-robin across product types, newest set first
  within each, capped at 30.
- **Every photo and price on it is TCGplayer's**, and the subtitle says so, with the ETL
  date and the Associate disclosure. "Updated daily" needs no new pipeline:
  `sealed_prices_latest` refreshes every ETL run and the row re-derives from it.
- **Its anchors carry `draggable="false"`.** The row is drag-to-pan, and a native link or
  image drag would hijack the gesture.
- `MoversBanner` grew a `titleHint` prop: its title button had "Open Screener with this
  filter" hardcoded, which this row's title (→ `/gear`) is not.

### Out of stock, or scalped → hidden, by a MANUAL daily check (migration 137)

Until Creators API access, whether a shelf product is in stock — and whether it is being
scalped — is checked **by a person**, from an admin-only checklist at the top of `/gear`
(`AmazonStockCheck`, gated on `GradedAdminContext`). Marking one **Out** or **Over** writes
`amazon_stock_checks` and hides it from the home row and from `/gear` for visitors; admins
still see it dimmed and labelled with which, so it can be marked back in.

- **The price ceiling is MSRP + 20%** (`AMAZON_PRICE_CEILING`, 2026-09-12, Zaven: "manually
  confirm if the price is no more than 20% above msrp and hide if it is higher"). A featured
  link at 2x MSRP costs more than its commission is worth, because the person who clicked it
  stops trusting the row. Two things keep the judgement quick and licensed:
  - **We store the MANUFACTURER's price (`msrp`), never Amazon's.** The recorded verdict is a
    bare boolean (`price_over`), so the number on the listing is read and discarded. MSRP is
    entered once per listing and persists; the verdict is daily.
  - **The checklist prints MSRP and the computed ceiling beside each link**, so the daily pass
    is a glance rather than arithmetic — which is what makes a sweep of forty listings
    something a person actually does. Neither reaches a visitor: an overpriced listing simply
    isn't there.
  The multiplier lives in the client, so changing the policy moves one constant and re-reads
  every stored MSRP rather than invalidating a column of numbers.
- **`amazonListingHidden(rec)` is the ONE predicate** for "don't feature this link", so the
  home row, `/gear` and the checklist's own counts can never disagree. A listing nobody has
  checked is SHOWN — an empty table means "no rulings yet", not "hide the shop".
- **⚠ The flag decides which links we feature; it is never DISPLAYED.** No "in stock" badge,
  no price, no "fair price" badge. Amazon licenses stock and price only through its API;
  curating our own list is not Program Content, and MSRP is a manufacturer fact rather than
  Amazon's number — but both stay admin-only, because a green tick beside a buy button reads
  as a claim about the price on the other end of it.
- **⚠ Never automate it.** Reading Amazon pages on a schedule is the automated data
  gathering Amazon's Conditions of Use prohibit, and it trips their bot checks. A person
  opening forty listings is the design, not a stopgap to "improve".
- **Keys are `amazonListingKey(url)`**: the ASIN, or `s:` + the search terms. Never the
  tagged URL, or a tag change silently un-hides everything.
- **The checklist's links are untagged** (`amazonCheckUrl`), so an admin checking forty
  listings a day doesn't pollute the Associates click report.
- **Hidden before the cap** — `amazonShelfItems(…, hidden)` filters, then round-robins, so
  the next product takes a hidden one's slot. The checklist walks `amazonShelfPool`, every
  candidate, not just the 30 on screen.
- **Every failure reads as "nothing hidden"**, the pre-137 behaviour, and `amazonStockUnavailable`
  lets the checklist say "apply migration 137" instead of throwing — including **42703**, a
  database on the ORIGINAL 137 that has the table but not `msrp` / `price_over`, where the
  whole select 400s. Cached 10 min in module scope (`_amazonStock`), refetched after each save.
- **⚠ `saveAmazonCheck(keys, patch)` applies ONE patch to every key**, and must keep doing so:
  PostgREST rejects a bulk body whose objects carry different key sets (PGRST102), and an
  upsert only updates the columns the body names — which is exactly what lets a stock click
  leave a stored MSRP alone.
- **137 is idempotent and was EXTENDED in place** (2026-09-12) rather than followed by a 141:
  `create table if not exists` plus `add column if not exists`, so re-running it is the
  upgrade whether or not the original ever landed.
- Test it signed out: on localhost, `localStorage["packsink:gradedAdminPreview"] = "1"`
  renders the admin checklist (writes still need a real admin session).

### The home bar — removed (2026-09-10)

`HomeGearBar`, the bottom-left "Sleeves, binders & deck boxes" pill, is gone at Zaven's
request: component, CSS and render line together. Once the "Lorcana on Amazon" row and the
Gear panel both existed it was a third Amazon prompt on one page. The Gear PANEL followed it
out on 2026-09-12 for the same reason, so the home page's one Amazon surface is now the row,
whose title leads to `/gear`. Leftover `packsink:gearBarDismissed` / `packsink:home:gearCollapsed`
keys in someone's browser are harmless.

### The Amazon link is a BUTTON, and it never touches a price (2026-09-26)

Zaven: *"make it more clear it's a button to take you to amazon, and not the same price
as the $ above which also should imply it's a tcgplayer link."* The Amazon twin used to
be a muted "Amazon" text link sitting under or beside the box price — which read as a
caption ON that price, i.e. as though the $ were Amazon's.

- **`amazonPill(az, {cls, stop, label})`** (beside `AmazonBuyLink`) is the one
  accessor: a cart glyph, the word, a trailing ↗, a border, and an amber tint
  (`.amz-btn`, rgba(240,163,62)) that no price on the site uses. **It never carries
  a number.** Used on the home EV strip, the Analytics EV rows, Sealed collection
  tiles and the calendar's product links; `AmazonBuyLink` (sealed modal) gained the
  cart and the same amber; the icon-only twins (Screener sealed rows, movers-tile
  corner) take the amber so a cart is never mistaken for the TCGplayer link.
- **The price says whose it is.** The Analytics EV column header reads "Box ·
  TCGplayer", the price link carries a small ↗, and the sealed tile's chip reads
  "TCGplayer ↗" (was "TCG ↗").
- **⚠ On the home Recent set EV card the box price lives INSIDE TCGplayer's own
  button** (`.home-ev-tcg`: "$179.99 TCGplayer ↗"), and the Amazon pill sits
  beside it carrying no number. That is a stronger answer than the old separate
  column: the price is enclosed in a button that names its shop, so there is no
  neighbouring number for the Amazon pill to be read as a caption on. See
  "Recent set EV" under Home page surface.

### Disclosure

**"As an Amazon Associate I earn from qualifying purchases"** is a required string — verbatim,
not copy to polish. The FTC wants it **near the links**, not only in a footer, so every
Amazon-bearing surface carries its own:

| Surface | Where the statement is |
|---|---|
| Footer (every SPA view) | `.footer-disclosure` |
| `privacy.html` | affiliate bullet, third-party list, fineprint |
| Help / How-it-works | its affiliate paragraph, which also states we show no Amazon data |
| Sealed detail modal | `.sealed-detail-affiliate`, under the buy row |
| Sealed collection tiles | `.sealed-coll-affiliate`, foot of the view |
| EV tool (box-price column) | appended to the existing "Prices via TCGCSV" footer |
| `/gear` | `.gear-page-note`, above the list |
| Home "Lorcana on Amazon" row | the row's subtitle |

Every Amazon anchor is `rel="noopener nofollow sponsored"`.

### The ASINs are unverified by CI, deliberately

Every ASIN was read off a public listing; **nothing in CI can reach amazon.com**, and Amazon
bot-challenges anything that looks automated. `node scripts/verify_amazon_asins.mjs` (run it
from an ordinary machine) fetches each one and reports `OK` / `CHECK` / `BLOCKED` / `GONE`.
A wrong ASIN is not dangerous — it lands on some other real Ravensburger product — but it
costs the click, and nothing else in the codebase can tell. It is **not wired into CI**: a red
job everyone learns to ignore is worse than a script you run when you touch the catalog.

Guarded by `node scripts/test_amazon_links.mjs`.

### Third-party accessories, and why they are SEARCHES (2026-09-10)

The first cut of Gear was first-party Ravensburger only, on the reasoning that a fan
site naming a brand of sleeve it has not tested is making a claim. Zaven asked for the
third-party market too, which is right — the official line is four sleeve designs
against a category people genuinely shop. The rule that replaced it is narrower and
survives the same objection:

**⚠ STATE THE SPEC, NEVER RANK.** Sizes, counts, finishes and capacities are facts.
"Best", "recommended", or an ordering that implies one is a comparative claim about
products nobody here has tested. Where a spec is a **requirement** it may be stated as
one — PSA publishes the semi-rigid dimensions it wants, so repeating them is reporting.

**The fact that makes the whole category possible: a Lorcana card is 63×88mm, the same
as Magic and Pokémon.** There is no Lorcana-specific accessory constraint at all beyond
licensed art, so the entire mainstream standard-size (66×91mm) market fits. That is the
single most useful sentence on `/gear` and it leads the sleeves section.

- **⚠ A third-party entry carries `q` (a tagged search), never `asin` — and that is the
  RIGHT destination, not a fallback.** Two independent reasons, and the second is the
  one that would still hold with perfect information:
  1. Amazon is egress-blocked from **every** path available to an agent here — sandbox
     curl *and* the fetch tool (re-confirmed 2026-09-10). An ASIN written from that seat
     is unverifiable by construction, and a wrong one silently lands on somebody else's
     product.
  2. Sleeves, binders and toploaders are a **colour and size purchase**. A search for
     "Dragon Shield Matte 100" lands on all forty colours, which is the page a buyer
     wants; a single ASIN picks black for them. Searches commission identically.
  Upgrade any of them with `node scripts/verify_amazon_asins.mjs` from an ordinary
  machine — never from inside an agent session.
- **`gearUrl(it)` / `gearKey(it)` are the one accessor**, so no render site has to know
  which kind it is holding. An entry has exactly one of `asin` or `q`; **neither** is the
  dangerous case, because `amazonUrl(undefined)` returns null and the row renders as a
  dead `<a href>` that looks completely normal. The guard test asserts the xor.
- **`home: true` marks the sections the home panel shows; `/gear` renders all of them.**
  That split is what lets the catalogue grow (17 sections, 89 links) without the
  right-rail panel becoming a shop — the panel is a teaser whose title already links to
  `/gear`. The panel's disclosure line says "Official Ravensburger accessories", so
  **marking a third-party section `home` would silently make that copy false**; the test
  asserts every `home` section is all-ASIN.
- **The "searches" tag sits on the SECTION, not the row.** Every section is wholly one
  kind or the other, so a per-row tag on thirty rows is noise for a fact true of the
  whole block. Same honesty as `exact` choosing "Amazon" vs "Find on Amazon".
- **Grading supplies are the differentiated section**, because this site tracks graded
  collections — some of its readers are about to send cards away, and PSA publishes an
  exact packing list: a semi-rigid holder at **3 5/16″ × 4 7/8″** (Card Saver 1 is that
  size), clear penny sleeves (opaque backs delay a submission), and **explicitly not
  toploaders**, which graders cannot safely open. That is PSA's spec, not a preference.
- `amazonSearchUrl(query, dept)` gained the department argument here; it defaults to
  `toys-and-games` so every existing caller is unchanged.
