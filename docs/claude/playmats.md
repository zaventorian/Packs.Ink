# Playmats — a Collection tab of its own (2026-09-27)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

From the beta: *"I have all the prize wall and set champion mats and would love to log them."*
Zaven's spec: TCGplayer listings, price history, and sections — retail, Set Championship, DLC,
events. `/collection?c=playmats` → `PlaymatsView` (just above the Graded collection in
Index.html). Guarded by `python scripts/test_playmats.py` (offline, over a frozen copy of the
group in `scripts/fixtures/`).

**Sections** (`SECTIONS` in the loader = `PLAYMAT_SECTIONS` keys in Index.html, same order —
the test pins both, plus the newest migration's CHECK): **Retail** · **Disney Exclusives**
(`disney`: the Disney-location mats plus the D23 2026 Hunny Wizard, by Zaven's ruling) ·
**Ravensburger Store** (`ravensburger`: online-store exclusives) · **Set Championship**
(Champion / Participant) · **Disney Lorcana Challenge**, split into **Top Prize** and **Prize
Wall** sub-grids (`tiers` on the section; `PLAYMAT_DLC_TIERS` = the loader's `DLC_TIERS`) ·
**Events** (conventions, and Mother Knows Best — the Season 3 CCQ Top 8 prize, though TCGplayer
lists it as a Challenge mat) · Other. Adding a section value needs a migration: 171 widened the
CHECK for disney / ravensburger.

- **⚠ TCGplayer never says Top Prize or Prize Wall.** Every Challenge mat's tier is a ruling in
  the overrides file (Zaven, 2026-09-27: Cinderella, Simba and Mulan are Prize Wall; the rest Top
  Prize). A new Challenge mat arrives with none — the loader reports it and the tab lists it in a
  trailing "Not sorted yet" group rather than dropping it.
- **A shop section doesn't repeat itself on the tile**: `shop` on the section hides the source
  every mat there shares, so only the D23 mat names its source in Disney Exclusives. A tier the
  section groups by is hidden on the tile the same way; the detail modal still carries both.

- **TCGplayer files every Lorcana mat in a DIFFERENT category** — Playmats (35), group
  "Ravensburger Playmats" (23280) — not Lorcana (71), which is why no mat ever reached
  `sealed_products` or `prices_daily`. `tcgcsv_common.EXTRA_PRICE_GROUPS` makes the daily ETL
  fetch the group too; a failure there is a WARNING and never costs the day's card prices.
- **Its own table, `playmats` (migration 170), deliberately NOT `sealed_products`.** Every sealed
  surface reads sealed_products, and so does the market index's `sealed` scope (130 admits every
  product_type but Promo Single) — a mat filed there would silently join the sealed benchmark,
  the Sealed tab, the sealed Screener and Sealed Movers. `playmat_prices_latest` is a plain
  `security_invoker` VIEW (the newest priced row per mat, ~60 lookups on
  `prices_daily_tcgcsv_raw_idx`), so there is no refresh step for anything to forget.
- **`scripts/load_playmats.py`** (daily, in etl.yml's sealed job, `continue-on-error`) classifies
  the group off TCGplayer's own copy: `(Champion)` / `(Participant)` → Set Championship, with the
  set and year read from the description (it copes with TCGplayer's `Archazia�s` mojibake and its
  `Reign of Jafarl` typo); `(Disney Lorcana Challenge)` → DLC; `YYYY Convention Playmat` → event;
  "exclusively available on the Ravensburger Online Store" / "at Disney locations" → that shop's
  section; a retail mat's set from its street date (within 45 days after a set's release). What
  the rules cannot know lives in **`scripts/playmat_overrides.json`, every entry with a `why`** —
  the Challenge tiers, the D23 2026 mat, several exclusives, a replacement photo, TCGplayer's
  pre-order "Stitch - Miguel Rivera" (a Miguel Rivera mat). `--dry-run` prints the whole placement.
- **Ownership = `sealed_collection_items` under `PLAYMAT_PID_BASE` (980000000) + the TCGplayer
  id** — the pins' band trick. `isOwnTabPid` keeps mats out of the Sealed tab's COUNTS. ⚠ The REAL
  id stays the price, history and TCGplayer-link key; only the stepper uses the band, and
  `SealedDetailModal` carries both (`own_pid`, `is_playmat`).
- **A mat's VALUE counts as sealed** (Zaven, 2026-09-27: *"add playmats value to collection value
  as part of sealed"*). Every surface that turns the sealed collection into money keys it through
  **`sealedPricePid(pid)`** (band id → TCGplayer id) and takes today's mat prices from
  **`useOwnedPlaymatPrices`** (one cached `fetchPlaymats`, only when a mat is owned): the home
  Collection panel's Sealed line and headline, the Sealed tab's Est. value (with **"incl. $X in
  playmats"** under it — the units and SKU counts still exclude them), and the Sealed portfolio
  chart. The Playmats tab's value carries an asterisk and a one-line note saying where it is
  counted. ⚠ Miss `sealedPricePid` on a new money surface and an owned mat silently adds $0 again;
  the test pins all three at source. Measured: one box + three mats read $2,016.99 on all three.
- **⚠ Both sealed value charts go through `fetchSealedValueHistory`, not the plain history
  fetch.** The rollup counts an item only from its first IN-WINDOW price, and a mat's first price
  inside a short window is the day after the hole — so the 3M chart drew owned mats arriving from
  nothing, **"+324% past 3M"** on a collection that hadn't moved. Each owned mat is seeded with its
  newest price from BEFORE the window, re-dated to the window's first day (what forward-fill would
  have carried): the same collection now reads +52%, the mats' real move across the hole. Mats
  only — every other sealed product has daily prices.
- **Sharing rides the SEALED visibility axis**, like Pins & Counters.
- **One grid per section, the set named on each tile.** A heading per set left a column of single
  tiles (most sets have one Championship mat and two retail ones). Newest set first; the regular
  retail pair before the exclusives; Champion before Participant. Rows STRETCH so the steppers
  line up.
- **Photos are 16:9 with `object-fit:cover`.** TCGplayer ships some mats as a 16:9 shot and some
  as a 400x400 with the mat in a white band across the middle; cover crops that band to the mat
  in both cases, where contain drew the square ones at half the tile's width.
- **Two of TCGplayer's photos are the BOX, not the mat** (Ursula's Return Tinker Bell 543891 and
  Rapunzel - Gifted Artist 543892: a tall tube, which the wide tile crops to a sliver that reads as
  "no image" — reported by Zaven 2026-09-27; the other 61 are real mat shots, checked on a contact
  sheet of all 63). An `image` override points at our own photo under **`Logos/playmats/`** (the
  loader writes it to `image_url`; `playmatPhoto(r, px)` prefers any non-http `image_url` over the
  TCGplayer CDN). Ravensburger's product shot, cropped to the mat's 16:9 frame, the white outside
  its rounded corners cut to transparency, saved as WebP. **⚠ It is passed `noCut`**: it's already
  just the mat, and `cutProductWhiteBg`'s flood fill would eat the light Rapunzel art. The test
  checks every override photo exists on disk — a missing one renders the glyph with no error.
- **`PLAYMAT_CACHE_KEY` is v3**: the section split and the photos landed after browsers had
  cached rows, and a replayed row files a mat under its old section for up to 12h.
- **Amazon only on a plain retail mat** (a search — "Find on Amazon"). A prize or an exclusive is
  not on a shelf, and a search for one lands on resellers' lots.
- **⚠ The history has a HOLE: 2026-05-12 .. 2026-09-25**, because TCGCSV's archive went offline
  (see the TCGCSV notes). `scripts/backfill_playmat_prices.py` filled 2024-02-08..2026-05-11 from
  the local cache (21,570 rows) and `--live` loaded the 2026-09-26 publish. Four things keep the
  hole from lying (the fourth is the value-chart seed above), all opt-in so no other product
  changes:
  - `computeSealedDeltas(history, {maxLagDays})` — a window whose stand-in snapshot sits more than
    max(14, window/2) days before its cut reads "—" instead of comparing across the hole. Only
    the mat modal passes it; sealed keeps the documented fall-back-to-the-day-before.
  - `LineChart` series `breakGapMs` breaks the line at the hole, and the modal names it in a
    caption ("Gap in our price record: …").
  - A tile whose newest price is more than a week behind the newest mat's says **"Price as of
    <date>"** — never "last listed", which would overclaim: it may well have been listed inside
    the hole.
- **The price-standing chip is hidden whenever TODAY has no NM Market price** (the sealed modal,
  every product). `priceStanding` judges the newest row that HAS one, which on a thin product is
  months old — it said "Near its 12-month high" about a price nobody could see, beside a Low that
  said otherwise.
- **⚠ Until this ships, the ETL (which runs from `main`) does not fetch the mats**, so every day
  before the deploy extends the hole. `python scripts/backfill_playmat_prices.py --live` loads the
  current publish by hand, and **refuses until that day's CARD prices are loaded**: the ETL's
  idempotency probe asks "is there any tcgcsv/raw row for today, written after the publish
  window?", so a mat row written first would make it skip the whole day's card prices.
- Mats TCGplayer doesn't list (demo and youth mats, older one-offs) are out of scope; adding one
  would mean a static entry, the `SEALED_EXCLUSIVES` shape.
