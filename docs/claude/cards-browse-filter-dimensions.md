# Cards browse filter dimensions

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Drawer + toolbar quick-filter chips (icon-only on toolbar):
- Ink (6 colors + Inkable/Uninkable hexes)
- Cost (1-9+ hex buttons)
- Rarity (9 icon-only buttons using `RARITY_ICONS`)
- Legality (Core / Infinity — mutually exclusive toggle)
- ✓ Owned (filters to groups where any printing has `collection[card_id:printing] > 0`)

Drawer-only: **Price** (see below), Strength / Willpower / Lore (numeric buckets), Type, Set, Keywords, Classifications, Artist.

### Set tiles, quest cards, Coconut chip (2026-10-03, Zaven)

- **The drawer's Set filter is four sections of tiles, four across**: Sets (booster, newest first), Promo sets (C1-C3 included; Extras and any set `SET_ORDER` doesn't know close the section), Format Coconut, Illumineer's Quests. `groupSetsForFilter` returns `{mainline, promo, coconut, quest}`; `SetFilterTile` draws the art: the wordmark for a booster set, the Challenge badge for C1-C3, the printed stamp for a promo set that has one, the BOX photo for a quest (`QUEST_BOX_PIDS`, TCGplayer ids), the drawn coconut, else the Promo mark. `SET_TILE_LABELS` holds short names; the full name stays in `title` / `aria-label`.
- **Cost / Strength / Willpower / Lore / Rarity are one line each** (`.drawer-chiprow`, a grid of `--n` equal cells). Willpower and Lore use Strength's 10 columns so the three stat rows line up.
- **⚠ Quest cards are hidden from the Cards grid unless the search asks for them** (`questsAsked`): a quest set picked, the Quest rarity, or "quest" / "deep trouble" / "palace heist" / "hunny rescue" typed. A name search answered ONLY by quest cards still shows them, so a search never dead-ends. They answer to their quest's name through `cardVersionTerms`. `deep trouble` and `palace heist` are deliberately NOT `SET_NICKNAMES`: the boxes' foil promos sit in Extras under those labels and a set filter would hide them. `hunny rescue` IS, or "hunny" parses as the Hunny classification.
- **The toolbar's Coconut chip** toggles `cardTypes` Coconut (the leaders), beside the legality chips. Not in the deck editor, which has its own leader button.
- **Drawer picks show as removable pills under the toolbar** (`drawerPills`); the quick chips already show their own state and are left out.
- **✓ Owned is hidden signed out** (`isAuthed !== false`): `collection` is `{}`, never null, so the old test showed a chip that filtered to nothing.

### Price ($) filters (added 2026-08-14)

Four fields on the filter object — `priceMin`, `priceMax` (inclusive $ bounds, null = open end), `priceBasis` (`any` | `low` | `market`), `unpricedOnly` (bool). They live in `emptyFilter()`, so every `matchesCardFilter` caller gets them, and `serializeFilter`/`deserializeFilter` carry them for free (they're plain scalars, not Sets).

- **A card matches a max via its CHEAPEST printing and a min via its DEAREST.** `_cardPriceRange(row, basis)` returns `{min,max}` across normal+foil, so "Under $1" keeps a card whose non-foil is $0.40 even when its foil is $30, and "$100+" keeps the same card via the foil. This is the pre-existing typed-search semantic ("under $5" / "over $20"); the chips just reuse it. Don't "fix" it into an all-printings test — the tile shows both prices and users are shopping for the cheap side.
- **`priceBasis`** picks which number a printing contributes: `low` = TCGCSV's published Low Price, `market` = NM Market, `any` = `Low ?? Market` (the widest net, and the historical behaviour — callers that pass no basis get it). It applies to the TYPED price too: the parsed-price branch in `matchesCardFilter` reads `f.priceBasis`, so a `$5` in the search box respects the drawer's pick instead of silently comparing a different number.
- **`unpricedOnly`** is the inverse lens — cards with no price at all on the chosen basis (regional exclusives, unlisted variants, freshly spoiled cards). It wins over any bound in the matcher, and the drawer also clears/disables the bounds so the two can't disagree.
- **`PRICE_BANDS`** (Under $1 / $1–$5 / $5–$20 / $20–$50 / $50–$100 / $100+) is the single source of truth for the preset buckets. The drawer renders it as chips; the Collection set-detail toolbar renders the same list as a `<select class="setdet-price-band">`. Add a band once, both surfaces get it.
- **Collection per-set view** keeps its own `priceBand` state (a PRICE_BANDS key, not persisted — same lifetime as its ink/rarity chips) and folds it into the non-allMode `chipFilter`. Because it narrows `visibleGroups`, the completion meters, the Owned/Missing value stats and the **"Shop N missing cards" bulk-buy link all follow it** — "what am I still missing under $1" is the workflow this exists for. `searchOrFilterLabel` takes the band as its 6th arg so the shop link says which band. The Collection **All Cards** view uses the full drawer instead, so it deliberately has no select.
- **URL-backed on the Cards tab**: `pmin`, `pmax`, `pbasis`, `unpriced` in `CARD_URL_KEYS` — a price search is shareable/refreshable like the rest.
- `countActiveFilters` counts a bound ONCE whether one or both ends are set; `priceBasis` alone never counts (it's a modifier on a bound, not a filter).

**Ink filter chips render as bare ink shields**, no chip wrapper (no dark circular fill, no per-ink colored border). The shared `.chip.ink-icon-chip` rule (styles.css) hard-overrides `background: transparent !important; border: none !important; border-radius: 0 !important; box-shadow: none !important` so the visual matches the deck-row inkable shields. Active state retains full color; inactive uses `filter: grayscale(0.6) opacity(0.55)`; hover removes the grayscale. The 30×30 hit area is preserved for tap ergonomics. 4 call sites still pass `style={{background: INK_COLORS[ink].bg, borderColor: INK_COLORS[ink].border}}` inline JSX — keeping them lets us rip the inline props in a future cleanup without re-touching the CSS, but the `!important` overrides keep the bare-shield look regardless.
