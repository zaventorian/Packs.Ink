# What runs by itself, and what still starts with a chat

Written 2026-09-30, after Zaven asked which manual workflows could be streamlined.
One row per workflow: what notices the change, what acts on it, and what is left
for a person. "Routine" means a scheduled Claude task on Zaven's desktop (it has
the browser, the residential IP and the database); "CI" means GitHub Actions.

## The map

| Workflow | Notices | Acts | Left for Zaven |
|---|---|---|---|
| Card and sealed prices | CI, three times a day | CI | nothing |
| New sealed product on TCGplayer | CI (daily loader) | CI | nothing |
| New single or promo on TCGplayer | CI catalog watch, tracking issue | **Intake routine** prepares the fix | say "push" |
| New set group on TCGplayer | CI catalog watch | Intake routine writes the set-row migration and applies it | nothing |
| Spoilers: official gallery, duels.ink renders | CI source watch | Intake routine runs the importers | check the art once |
| Pins and lore counters | CI source watch (lorcanaplayer) | Intake routine prepares the entry and the photo cut | approve the photo, say "push" |
| Calendar: Challenges, qualifiers | CI calendar watch + CCQ scan | Intake routine fills in venue, map point and link, and confirms every row that checks out | nothing (it reports what it confirmed and what it left) |
| Graded eBay sales | Routine, daily | Routine | rule on held outliers |
| Raw eBay sales (the promos TCGplayer can't price) | Routine, daily | Routine | rule on held outliers |
| PSA population | Routine, weekly (new 2026-09-30) | Routine | sign in to collectors.com when the session lapses |
| Elo ratings, store status | CI, weekly and hourly | CI | merges and one-off events |
| Tournament decklists (inkDecks) | nobody | chat | still a chat: needs Zaven's browser profile |
| News and articles | **Intake routine** drafts from the day's changes | Routine writes a draft | read, edit, publish |
| Discord daily and weekly report | CI | CI | nothing |
| Feedback inbox | site badge | chat | reply |
| Amazon stock and price check | nobody | a person, by hand | see below |
| Japan Core legality, brand art bundle | dated reviews in the catalog watch | chat | hand over the bundle link |

## The intake routine

`packs-ink-intake`, daily at 8:30 AM. It reads what CI already found overnight
(the "Catalog watch: open findings" issue, the source watch and the calendar
watch) and works the list.

It may do on its own, because each is already guarded and reversible:

- link a TCGplayer product to a card when the name and the printed number both match exactly one card;
- apply a set-row migration for a new TCGplayer group;
- run `import_duels_art.py --commit`, `import_official_set.py`, `link_calendar_events.py`;
- add venue, coordinates and registration link to a calendar row;
- confirm a calendar row that checks out (Zaven, 2026-10-03: *"if it looks legit, add it. I cannot manually approve these. If the listing changes, we can remove it."*). Checks out = the Ravensburger Play listing (or the organiser's page) is live and upcoming, names a qualifier or Challenge, and the date matches. Left unconfirmed, and named in the report: a side event at a CCQ (`SIDE`, `paralelo`, a prize-pack tournament on the same day as the main event), a duplicate of a row already on the calendar, a listing that is gone or cancelled. An event the official Challenge page lists that the calendar lacks is ADDED confirmed;
- write a news draft.

It prepares, and stops, for anything that changes the site's code or publishes
something: a new promo row, a new pin or counter. That
work lands as commits on a local `intake/<date>` branch with the guards run, and
the report says what is waiting. Nothing is pushed or deployed until Zaven says
"push".

## News

There is no article page on the site yet. Drafts are plain Markdown in
`drafts/news/<date>-<slug>.md`: a headline, a two-sentence summary (what a home
tile or a Discord post would carry), the body, and a "Sources and what is not
confirmed" footer. A draft only states what a source says; anything heard
second-hand is marked.

Where a published article would go is undecided. The three candidates, cheapest
first: the home News box (a tile that opens the article), the Discord bot
(`/news`, and a line in the daily report), a `/news` page with one address per
article (the only one search engines can find).

## Amazon

The stock and price check was built as a checklist for a signed-in admin at the
top of `/gear` (migration 137) and has never been run. Each listing is opened by
hand and marked In / Out / Over; "Over" means more than 20% above the MSRP typed
in for that product. Hidden listings leave the home row and `/gear`.

It is not a routine because reading Amazon's pages with a program or an agent is
what Amazon's Conditions of Use prohibit, and the Associates account is what is
at risk. The licensed way to know stock and price is the Creators API, which
opens at 10 qualifying sales in 30 days.
