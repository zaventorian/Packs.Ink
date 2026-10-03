# Sealed enhancements (2026-06-05 — modal + Δ% + Screener)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Three parallel additions made sealed feel like graded:

**1. `SealedDetailModal`** (`Index.html` ~line 9636) — clicking any sealed tile (in `SealedCollectionView`) opens a popup with:
- Image + name + set + product-type meta
- Current Low + NM Market side-by-side
- Owned-qty `+/-` controls when signed in (calls `updateSealedQty(pid, n)`)
- Optional `CostDateInputs` row when qty > 0 + trackCosts is on
- 6-window Δ% grid (LOW row × MKT row × 1D/1W/1M/3M/6M/1Y) from `computeSealedDeltas`
- Inline `LineChart` of `prices_daily` history (lazy-loaded via `fetchCardHistory(pid, "Normal")`)
- TCGPlayer affiliate buy link
- Reuses `.card-detail-overlay` + `.card-detail-close` patterns + ESC handler from CardDetailModal
- Also opened from the Screener row click when the row is a sealed synth row (see #3)

**2. Sealed-tile Δ% toggle** in `SealedCollectionView`:
- New `Show Δ%` toolbar checkbox (`packsink:sealedColl:showDeltas`)
- When on, fetches 365 days of `prices_daily` for the user's owned sealed pids via `fetchCollectionPriceHistory(ownedSealedPids, since)` (one batched call)
- Renders a 4-cell `1D / 1W / 1M / 1Y` grid beneath the price line on each OWNED tile
- Compute via `computeSealedDeltas(history)` → Map of pid → row
- Scoped to owned pids only (~typically <20 SKUs); for unowned products users get full history via the modal

**Tiles also show Low + Market simultaneously** when both exist (was previously priceMode-gated). The priceMode toggle still drives the total-value sort + header totals, but the tile surface always renders both numbers so users don't have to flip the toggle to compare.

**3. Screener Sealed mode** — third toggle button alongside Raw/Graded:
- `showSealed` state (`packsink:screener:showSealed`), mutually exclusive with `showGraded` (mutex useEffect on both)
- Fetches 365 days of `prices_daily` for ALL sealed pids on first toggle-on, cached in `sealedHistory` state
- `sealedSynth` memo builds rows shaped like `price_movers` rows (synthetic `card_id: "sealed::<pid>"`, image_small/normal from `image_url`, `display_type` from `deriveSealedDisplayType`, every `pct_*` + `mkt_pct_*` window from `computeSealedDeltas`, plus `_sealedProduct` ref for modal open)
- Filter chain in sealed mode is parallel to raw/graded but uses sealed-specific predicates:
  - Name substring search (no `matchesCardFilter` — sealed has no card catalog)
  - Set dropdown (uses `setNameById`)
  - Product-type chips (`filterSealedTypes`, persisted in `packsink:screener:filterSealedTypes`) backed by `SEALED_DISPLAY_TYPE_ORDER` — Booster Boxes, Booster Packs, Sleeved Booster Packs, Booster Pack Art Bundles, Illumineer's Troves, Prerelease Packs, Starter Decks, Gift Sets, Bundles, Quests, Sealed, Collector's Edition, Cases & Displays
  - `collFilter` (All/Owned/Missing) chips check `sealedCollection[pid] > 0` for sealed
  - Universal price + Δ% bounds + Crashing/Discount/Premium presets work uncapped
- UI hides Raw-only chips when sealed: ink dropdown, rarity icon chips, foil/non-foil chips
- Column header shows "Type" instead of "Rarity" in sealed mode; row's printing sub-line shows `display_type`
- Row click → `SealedDetailModal` via the same `openModal()` helper (detects `_sealedProduct` ref OR `"sealed::"` card_id prefix)
- `PriceDatabase` props extended: `sealedPrices`, `sealedCollection`, `sealedMeta`, `updateSealedQty`, `updateSealedMeta`

**Shared helper** `computeSealedDeltas(history)` (`Index.html` ~line 1796) — mirrors `computeGradedDeltas` shape. Takes `prices_daily` rows for sealed pids and returns rows with `low_today`, `market_today`, and per-window `pct_*` (Low-driven) + `mkt_pct_*` (Market-driven). Sealed has no foil duality so printing is always `"Normal"`. Uses the same `low_price_smoothed ?? low_price` coalesce as the catalog (migration 55).
