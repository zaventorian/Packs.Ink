# Cardmarket / Europe prices — feasibility research (2026-09-13)

Question: can we pull Cardmarket data so the site can show European prices?

**Short answer: the data is obtainable and our database is already built for it. The
blocker is a licence, not an API.** Cardmarket's GTC require their *prior written
agreement* to present cards and their prices, and that clause is about DISPLAY — so it
binds us however we obtain the numbers. Getting that agreement is step one; everything
else is downstream of it.

> **⚠ Sources are secondary.** Every `cardmarket.com` domain — `www`, `help`, `news`,
> `api`, `apiv2` — is egress-blocked from the agent sandbox (verified: `curl` returns
> `000`, WebFetch returns `EGRESS_BLOCKED`). So is `lorcast.com`. Everything below was
> assembled from search results quoting those pages, not read from the primary document.
> **Confirm the GTC wording and the download page before building against this.** Same
> posture as the Amazon Associates notes in CLAUDE.md, and for the same reason.

---

## 1. The official API is closed

**Cardmarket is not accepting applications for API access.** This is a standing status on
their own API help page, not a temporary pause tied to a migration. Two further facts:

- Access is gated behind **commercial-seller status** (company name, business licence,
  commercial registration number, ID document) even when applications are open.
- API 1.0/1.1 are **dead**; everyone was required to move to 2.0 at `apiv2.cardmarket.com`
  by **2026-05-01**, which has passed. So every pre-2.0 wrapper on GitHub is stale.

Even with a token, the API's own terms say it "may only be used for managing your own
contents", and credentials may not be shared with any third party. An API key is therefore
**not** the route to a public price display, and chasing one is the wrong thing to chase.

## 2. The actual gate: display requires written agreement

From Cardmarket's General Terms and Conditions:

> The presentation of the trading cards and their respective prices require our prior
> written agreement.

…alongside: "the use of the API and the transfer and use of data for any other purpose is
prohibited."

This is the whole decision. It is a restriction on **presenting** their prices, so it is
not routed around by picking a different pipe — a scraper, a reseller API, or the public
file download all land in the same place if the output is EUR prices rendered on packs.ink.

**This is the Amazon shape exactly**, and CLAUDE.md already records how that went: the
licence governs the displayed content, prices may be shown only under the terms of the
programme that supplies them, and buying a third-party scraping API does not launder the
obligation. Treat this identically.

**Recommended first action: ask.** A short, specific written request to Cardmarket
describing what we would render (a secondary EUR column beside the existing TCGplayer USD
figures, attributed to Cardmarket, linking back to them) is cheap, is the only thing that
unblocks the feature properly, and costs nothing but an email if refused. We are a traffic
source pointing buyers at their marketplace, which is the argument worth leading with.

## 3. If permission lands: the data source is already public

**Cardmarket publishes a Price Guide and a Product Catalogue as downloadable files, for
every game, and access was widened from API users to all users.**

| File | Contents | Updated |
|---|---|---|
| **Price Guide** | per-product prices, keyed by `idProduct` | once daily |
| **Product Catalogue** | `idProduct` → name / expansion / number | when a release is added |

- Lorcana is covered: `cardmarket.com/en/Lorcana/Data/Price-Guide` (and the sibling
  `/Data/Product-List`). The Data pages exist per game.
- Price fields reported by consumers of these files: **trend price**, **lowest listing**,
  and **1 / 7 / 30-day sale averages**, with **foil variants priced separately** — i.e.
  Cardmarket keeps a distinct price guide row per print variant, which matches how our
  `printing` column already works.
- **Trend price is the number worth showing.** It weights actual sales and filters
  outliers, so it is the EUR analogue of `market_price` — *not* of `low_price`. This
  matters: CLAUDE.md's own standing rule is that `low_price` is a published aggregate one
  listing can move, and `priceStanding` reads `market_price` for exactly that reason. Any
  EUR standing/judgement must read trend, never the lowest listing.

One daily file fetch fits our ETL cadence with no new infrastructure. **⚠ Both files are
behind the egress block, so someone on an ordinary machine has to pull one and inspect the
real columns before any of the above is treated as settled.**

## 4. What our database already does right

**The schema was built source-agnostic and has been waiting for this.** `prices_daily`:

```sql
primary key (tcgplayer_product_id, date, printing, source, grade)
source text not null,   -- "tcgcsv", "tcg_price_lookup"
```

`source` is **in the primary key**, so `source='cardmarket'` rows coexist with `tcgcsv`
rows for the same product, date and printing with no collision and no migration.

And critically — **every single consumer already filters on source**, verified across the
repo:

- All price views and matviews: `card_prices_latest`, `price_movers` (incl. 120/124),
  `rarity_avg_daily`, `sealed_prices_latest`, `market_index_daily` (128/130), the stale-price
  fallback — every one carries `where source = 'tcgcsv' and grade = 'raw'`.
- Both client-side direct reads of `prices_daily` — `fetchCardHistory` and
  `fetchCollectionPriceHistory` — send `source: "eq.tcgcsv"`.

So **writing Cardmarket rows into `prices_daily` is additive and cannot corrupt an existing
surface.** That is unusually clean, and it is the single strongest argument that this
feature is worth doing if the licence allows.

CLAUDE.md notes "no `prices_daily` row has ever had `source != 'tcgcsv'`" — true, and this
would be the first, which is exactly what the column is for.

## 5. The two real engineering problems

### 5a. ⚠ Currency — `prices_daily` has no currency column

Every numeric column is implicitly USD, and nothing says so. A `low_price` of `12.50`
meaning **€**12.50 sitting in the same column as one meaning **$**12.50 is a silent,
compounding error — the exact failure shape this codebase keeps writing guards against.

`source` does disambiguate it in principle, but relying on that means *every future reader*
must remember. Two options, and the first is strongly preferred:

1. **Add a `currency text not null default 'USD'` column.** Explicit, self-documenting,
   and it makes a mistake visible instead of plausible.
2. Convention only (`source='cardmarket'` ⇒ EUR). Cheaper now, a trap later.

Related: do **not** convert EUR→USD for storage. Store what Cardmarket published. A
converted figure is neither the real EU price nor a stable historical record, and the FX
rate would silently rewrite history on every refresh.

### 5b. ⚠ There is no ID crosswalk — this is the bulk of the work

Lorcast, our metadata source, carries **`tcgplayer_id` and no Cardmarket id**
(`load_lorcast.py:133` maps `c.get("tcgplayer_id")` and nothing else). Cardmarket keys on
its own `idProduct`. Nothing joins them today.

So a matcher has to be built: Cardmarket Product Catalogue → our `cards` rows, on
**expansion + collector number + name**, with the same care `terapeak_match.py` already
takes. The hazards are the ones this catalog is already full of:

- 13 mainline sets plus ~8 promo sets, and **Cardmarket's set names will not match ours** —
  we already keep `SET_DISPLAY_NAMES`, `TCGCSV_GROUP_SET_ALIASES` and
  `COLLECTOR_NUMBER_OVERRIDES` for precisely this class of mismatch against TCGplayer.
  Expect a third alias map.
- Enchanted / Epic / Iconic and the promo sets are where the money is and where naming is
  least consistent.
- **Printing vocabulary differs.** Ours is `Normal` / `Foil` / `Cold Foil` / `Holofoil`;
  Cardmarket's variant axis is its own. This needs the `gradedSlotBucket` treatment — a
  deliberate mapping that keeps *unknown* distinct from *non-foil*, rather than a guess.
- **European exclusives / language printings.** Cardmarket is a EU market and lists
  non-English printings. Note the site currently treats these as *noise to exclude*:
  `scripts/fix_foreign_european.sql` and `terapeak_load.is_foreign_lang()` deliberately
  quarantine German/French/Italian graded sales. A EUR price feature has to decide whether
  a German-language printing is the same product or a different one — that is a product
  decision, not a matching detail, and it should be made before the matcher is written.

Budget the mapping as the real cost. A wrong match is a wrong price on a card page, which
is worse than no EUR price at all — so the matcher should refuse ambiguity and report it,
the way `link_calendar_events.py` and `reconcile_catalog.py` already do, rather than guess.

## 6. Third-party APIs — do not buy one

Search turns up a crowd of services selling "Cardmarket prices as JSON": Apify actors
(several, explicitly Lorcana trend scrapers), `cardmarket-api.com`, `cardmarketapi.com`,
`tcg-cardmarket-api.com`, `lorcana-prices.com`, `parse.bot`. None states a licensing
arrangement with Cardmarket, and most describe scraping in their own marketing.

**These are the "buy a third-party Amazon scraping API" trap CLAUDE.md already warns
against.** Paying an intermediary does not transfer a right they do not hold, and the
obligation that matters is on *our* display. Skip them.

**JustTCG** is the one that looks like a real commercial product (free key, published
plans, rate limits, support, covers Lorcana). Even so, its Cardmarket-EUR provenance is not
stated publicly — so the question to put to them is narrow and specific: *are you licensed
to redistribute Cardmarket price data, and may a customer display it?* A "yes" in writing
would be worth as much as a direct agreement. Anything vaguer is not.

## 7. Alternative worth considering: CardTrader

If Cardmarket says no, the user-facing need — *European prices* — does not die with them.
**CardTrader** is a large EU marketplace with a developer API and EUR pricing. It is a
different (smaller) market than Cardmarket, so it is not a drop-in substitute for "the EU
price" people quote to each other, but it is a legitimate, licensable EU source and worth a
look before concluding the feature is impossible. Not researched in depth here — flag it
as the fallback branch.

---

## Recommended order

1. **Ask Cardmarket for written permission.** Nothing else is worth building first, and a
   refusal changes the whole plan. Cheap, and it is the actual gate.
2. **Pull the Lorcana Price Guide + Product Catalogue by hand** (needs a normal machine —
   egress-blocked here) and confirm the real columns, the variant axis, and how many of our
   ~2,500 card names match cleanly. That number decides whether 5b is a week or a month.
3. **In parallel, ask JustTCG the narrow licensing question** — it is a one-email hedge.
4. Only then: `currency` column, matcher + alias map, a `cardmarket` ETL job beside
   `etl_tcgcsv_daily.py`, and a EUR column behind a toggle.

**Nothing here should be built before step 1 comes back.** The engineering is
straightforward and the schema is ready; the licence is the only thing that decides whether
any of it can ship.

## Open questions

- Does the freely-downloadable Price Guide carry its own terms distinct from the API terms,
  or does the GTC display clause govern it too? (Likely the latter — it is a display rule —
  but the download page should be read directly.)
- Which Cardmarket price field do we show? Trend is the honest one (§3); showing "from
  €X" off the lowest listing would repeat the `low_price` mistake the site already documents.
- Is a German-language printing the same product as its English counterpart, for our
  purposes? (§5b — product decision.)
- Does Cardmarket cover sealed product for Lorcana the way it covers singles?

## Sources

- [Cardmarket API help page](https://help.cardmarket.com/en/cardmarket-api) — applications not being accepted
- [Cardmarket General Terms and Conditions](https://www.cardmarket.com/en/Policies/GeneralTermsAndConditions) — the display clause
- [Cardmarket RESTful API 2.0 documentation](https://api.cardmarket.com/ws/documentation/API_2.0:Main_Page)
- [Price Guide / Product Catalogue download announcement](https://news.cardmarket.com/en/Magic/were-making-the-price-guide-and-product-catalogue-available-for-download)
- [Cardmarket Lorcana Price Guide](https://www.cardmarket.com/en/Lorcana/Data/Price-Guide)
- [Cardmarket Partner Apps and Services](https://help.cardmarket.com/en/api-partnerships)
- [JustTCG API docs](https://justtcg.com/docs)
