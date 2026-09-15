# Social feed on the home page — feasibility + design draft (2026-09-15)

Question: can the home page carry a semi-live feed of Lorcana posts from X —
popular community posts, or specific creators?

**Short answer: the feed is buildable and the home page already has the exact panel
shape for it. The blocker is that X has no free tier any more, and "semi-live" is the
expensive word in the sentence.** Since the Basic and Pro tiers were retired (2026-06-01
and 2026-09-01) every new developer is on pay-per-use at **$0.005 per post read**. What
that costs us is set almost entirely by polling cadence, and by one billing question I
could not answer from here — see §2.

The recommendation is to **ship the panel against a curated table first** (§5), because
the curated version and the polled version are the same table, the same renderer and the
same panel. Curation is not a stopgap that gets thrown away; it is the substrate the
poller would write into if we later decide the meter is worth it.

> **⚠ Sources are secondary.** `public.api.bsky.app` is egress-blocked from the agent
> sandbox (verified: the proxy answers 403 to CONNECT), and so is the Supabase MCP
> server, so the Bluesky population in §4 is **unverified** and no live DB probe backs
> any of this. X's pricing and policy below were assembled from search results quoting
> those pages, not read from developer.x.com. **Confirm the meter and the display
> requirements in the X developer portal before building against §3.** Same posture as
> the Amazon Associates and Cardmarket notes.

---

## 1. What "semi-live" has to mean here

Worth stating before pricing it, because it decides everything downstream: this site
updates **once a day**. Prices land at 20:30 UTC, the ETL retries twice, the Discord
digest goes out at 21:15, and the whole client cache architecture is built around a 24h
TTL with a freshness probe. There is no push infrastructure, no websocket, and nothing
on the site refreshes faster than a `visibilitychange` re-probe.

So a feed that updates every 15 minutes would be **the fastest-moving thing on the
site by two orders of magnitude**, sitting next to a price chart that moves daily. That
is worth wanting — but it is a new operational posture, not a new panel.

## 2. The meter, and the one unanswered question

Pay-per-use, no free tier, capped at 3M post reads/month:

| what | price |
|---|---|
| post read | **$0.005** |
| user profile | $0.010 |
| post (write) | $0.015 |
| full-archive search | Enterprise only, $42,000+/mo |

**Naive polling** — 15 tracked creators, 10 recent posts each per sweep, no `since_id`:

| cadence | reads/day | $/day | **$/month** |
|---|---|---|---|
| every 15 min | 14,400 | $72 | **$2,160** |
| hourly | 3,600 | $18 | **$540** |
| every 6h | 600 | $3 | **$90** |
| daily | 150 | $0.75 | **$22.50** |

**With `since_id`** you pay for genuinely new posts instead of re-reading the same ten
every sweep. 15 creators averaging 3 posts/day between them is 45 reads/day — about
**$6.75/month at any cadence**, because a quiet creator returns nothing.

> **⚠ THE WHOLE DECISION HANGS ON WHETHER AN EMPTY RESPONSE IS BILLED.** If a call
> returning zero posts is free, `since_id` polling is ~$7/month and this is an easy yes.
> If there is a per-call floor, 15 creators polled every 15 minutes is 1,440 calls/day
> whether or not anyone tweeted, and the cadence is back to driving the bill. **Answer
> this in the developer portal's usage dashboard before writing a poller** — send one
> sweep, look at what it charged, then send the same sweep again with `since_id` set to
> the newest id and look again. It is a ten-minute experiment and it is worth more than
> any amount of reasoning from the price list.

Two further cost notes:

- **"Popular in the community" is the expensive half, not the creator list.** A creator
  timeline is bounded — fifteen accounts, a few posts a day. A search for what is
  *popular* is unbounded by construction: recent search returns whatever matched, and
  the interesting queries (`lorcana`, `#Lorcana`, card names) are exactly the high-volume
  ones. If we do this at all it needs a hard `max_results` and a daily spend ceiling, and
  it should be the second phase, never the first.
- The site's revenue is a 3.5% affiliate commission and `CLAUDE.md` opens with a rule
  about rationing Netlify build minutes. A $540/month line item is not in that world; a
  $7 one is.

## 3. What is free, and what it cannot do

**`https://publish.x.com/oembed?url=<post url>` is still unauthenticated and free.** It
returns the post's author, author URL and an HTML blockquote containing the post text. It
is rate-limited and undocumented as a product, but it works.

What it cannot do is **discover anything**. oEmbed resolves a URL you already hold; it
will not tell you what is popular, and it will not tell you a creator posted. That is the
exact division of labour this design leans on: **discovery is the expensive part and the
part a human is genuinely good at; hydration is the free part.**

### ⚠ Do NOT load `widgets.js`

The official embed path is a blockquote plus X's `widgets.js`, which renders the post in
an iframe. Four reasons that is the wrong call here, and they compound:

1. **CSP.** The policy is enforced (2026-09-05) and would need `script-src` and
   `frame-src` opened to `platform.x.com` — an origin that can then run arbitrary
   script in the page, on the home page, for every visitor.
2. **Privacy.** `privacy.html` names every third party the browser talks to, and the
   site has already spent effort going the *other* way: the deck-poster QR code was
   moved off `api.qrserver.com` to a vendored local renderer specifically because the
   remote call leaked share tokens. Putting X's tracking widget on the home page is a
   much larger version of the thing that was just removed.
3. **Theming.** The embed renders in X's own light or dark. There are seven themes here,
   four of which hold a gradient in `--bg`. It will look wrong in most of them.
4. **Weight.** One iframe per post, on the page with the movers banners on it.

So: store the text, render **our own tile**, link out. Same decision, same reasoning as
the QR code.

### ⚠ Two obligations that come with storing post content

- **Deletion compliance within 24 hours.** X's developer policy requires that content
  stored offline be kept current with X — if a post is deleted or edited there, our copy
  must be deleted or updated "as soon as reasonably possible", and within 24h of a
  request. **This is a cron, not a promise.** It is the same shape as
  `cleanup_scan_samples.py`, which exists because privacy.html makes a 12-month deletion
  claim and something has to make it true. A daily re-hydrate that drops rows whose
  oEmbed lookup now 404s satisfies it and costs nothing.
- **Display requirements.** X publishes rules on how its content may be presented. I
  could not read them from here. **Confirm before shipping post bodies.** The
  conservative fallback, if the requirements turn out to be restrictive, is §5's
  degraded mode: attribution, our own one-line note, and a link — no post body. That
  version is a citation, and it is also, usefully, the better-designed tile (see §6).

## 4. Bluesky is the free alternative, and its population is unverified

`https://public.api.bsky.app/xrpc/…` needs no authentication, no key and no payment;
`app.bsky.feed.getAuthorFeed` is public, and unauthenticated callers get roughly
3,000 requests per 5 minutes. A genuinely-live Bluesky feed costs **$0** and could poll
every ten minutes without anyone noticing.

**But I could not check whether the Lorcana community is actually there** — the host is
egress-blocked from this sandbox. That is the entire question for this option, and it is
a five-minute check from a normal browser: search Bluesky for `lorcana` and see whether
the accounts worth following have posted this month. My prior is that X is still where
this community lives and Bluesky would be a feed of tumbleweed, which is worse than no
feed — but it is a prior, not a finding.

Worth knowing rather than acting on: **the data model in §5 is platform-agnostic** (it
stores a `platform` column), so adding Bluesky later is a source, not a rewrite.

## 5. The design

### The panel

A new `HOME_PANELS` entry, `{key:"social", label:"Community feed", col:"left"}`, sitting
under the news feed. It is the `NewsFeed` shape almost exactly — a capped scrolling list
of tiles with the existing edge-fade affordance — and it should reuse
`.home-news-feed`'s scroll/edge machinery rather than growing a second copy of it.

Panel checklist, per the house rules:

- `panelDest.social` → `null` at first (there is no section page to open), like `news`.
  If a `/community` page ever exists, this is the one line that changes.
- **A one-shot stamped migration** (`packsink:homeLayoutSocial`) to place it for browsers
  that already hold a layout — `normalizeHomeLayout` APPENDS an unknown key, which would
  bury a new feed at the foot of a column. Stamped, never coerced, per the standing rule.
- Guarded by a `scripts/test_social_feed.mjs` that extracts the real helpers out of
  Index.html, in the house pattern.

### The table

`social_posts`, curated, one row per post, shaped on `calendar_events`:

| column | why |
|---|---|
| `platform` | `x` today; the reason Bluesky is additive rather than a rewrite |
| `post_id`, `post_url` | the stable key and the link out |
| `author_handle`, `author_name`, `author_avatar_url` | denormalised, see below |
| `body` | the post text, hydrated from oEmbed; nullable for the degraded mode |
| `posted_at` | the post's own time, which is what the feed sorts on |
| `note` | **our** one line about why it is here — the whole point, see §6 |
| `card_id` / `set_name` | optional link into the catalog, see §6 |
| `confirmed` | default **false** |
| `hydrated_at`, `dead` | the deletion-compliance bookkeeping from §3 |

- **`confirmed` default false is the load-bearing one**, and it is the
  `scan_ccq_candidates.py` contract exactly: a script may PROPOSE a row, only a person
  may publish one. Nothing that reaches a visitor's home page should have been chosen by
  a heuristic. **Never let a script flip `confirmed`.**
- **Author fields are denormalised for the same reason `scout_notes` denormalises its
  event label**: the feed has to render from our own row, not from a live call to X on
  every page load. A page that costs half a cent to render is not a page.
- RLS: anon reads `confirmed = true and not dead`; writes are `is_graded_admin()`.
  ⚠ And the SELECT policy must be scoped `to authenticated` if it calls
  `is_graded_admin()` at all — migration 134 revoked EXECUTE on that function from anon,
  so an unscoped policy **raises 42501 rather than returning false**, which is precisely
  how the curated calendar was invisible to every signed-out visitor for a day.

### Getting posts in

Three routes, in the order they should be built:

1. **Paste a URL into an admin box.** A `CalendarAdminModal`-shaped editor: paste the
   post URL, the server hydrates it via oEmbed, you add the `note` and the card link,
   save. This is the whole v1 and it is maybe a day's work.
2. **A proposer script** (`scripts/propose_social_posts.py`), daily, writing
   `confirmed = false` rows for an admin to rule on — the `catalog_watch.json` shape,
   with the same "red means something new" posture. This is where an X API budget would
   first be spent, and where the §2 experiment pays off.
3. **A hydrate-and-reap cron**, daily, in `etl.yml`'s selfheal job beside
   `cleanup_old_trades()`: re-hydrate every live row, mark `dead` whatever now 404s.
   **This one is not optional** — it is what makes §3's deletion obligation true.

## 6. ⚠ The part that decides whether this is worth building

A mirror of popular Lorcana tweets is a commodity, and `discord_digest.py` already has
the argument written down for the restock feeds: *they own "this is in stock at $6.00";
what none of them can say is whether $6.00 is a good price.* The same test applies here
and it is harsher, because anyone who wants Lorcana posts **already has X open**. Showing
them the same posts, slower, is not a reason to come here.

What makes this ours is the `note` and the `card_id`. A tile that says a creator is
talking about the Epic Heihei, **with Heihei's own price chart one tap away**, is a thing
X cannot render and the restock accounts cannot write. That is the same move the digest
makes, and it is why the curated version is not the poor relation of the polled one — a
poller can tell you a post is popular, but it cannot tell you why you should care.

Concretely, the tile should be:

- the creator, with attribution (their avatar hot-linked, which needs `pbs.twimg.com` in
  `img-src` — or dropped, which needs nothing);
- **our** one-line note, in the site's voice;
- the card or set it is about, as a real link into the catalog;
- a link out to the post.

The post body is the only part with display obligations attached, and it is the least
valuable part of the tile. If §3's display-requirements check comes back awkward,
**cutting the body costs this feature almost nothing** — which is a good property for a
v1 to have.

## 7. What to decide

1. **Run the §2 billing experiment.** Is an empty `since_id` response free? Ten minutes,
   and it is the difference between a $7/month feature and a $540/month one.
2. **Read X's display requirements.** Decides whether tiles carry post bodies.
3. **Check Bluesky for a pulse** (§4). Five minutes in a browser. If the community is
   there, a genuinely live free feed is on the table.
4. **Confirm the panel is wanted at all**, given §6 — a curated 6-tile community panel
   that updates a few times a week is a different product from a live firehose, and it
   is the one this site is shaped to do well.

Nothing in §5 needs any of the four answered to start: the table, the panel, the admin
editor and the reaper are the same whichever way they go.
