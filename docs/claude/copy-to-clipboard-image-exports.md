# Copy-to-clipboard image exports

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Three "copy this as an image" features. **The two card exports are now drawn on a `<canvas>`; only the mover banner tile still uses html2canvas.** Read this before touching any of them.

### Why card exports moved off html2canvas (2026-05-28)
html2canvas *screenshots the live DOM*, so its output depends on `styles.css` being the right version in the browser. The PWA service worker serves CSS cache-first, so a **stale cached stylesheet** rendered the off-screen poster with missing rules → wrong width, ungridded stats, card art at full natural size. Every CSS fix was invisible until the SW updated. **Fix: draw the card exports by hand on a canvas.** This ships inside Index.html (network-first → always fresh) and paints with explicit geometry + theme colors read live via `getComputedStyle`, so a stale `styles.css` can't break it — and it's instant (no DOM clone, no CDN fetch). The shared canvas drawing engine lives near `buildCardPosterBlob`: helpers `posterPalette()`, `posterPctColor()`, `roundRectPath()`, `drawImageCover()` (object-fit:cover), `wrapPosterText()`, `drawPosterLegend()`, `drawPosterChart()`, `loadPosterImage()`.

### Surfaces
- **Card poster** (`CardDetailModal` → Price History tab "Copy image" button, `.card-detail-copy-btn`) → `copyCardPosterImage(opts)` → `buildCardPosterBlob(opts)`. **Canvas-drawn, landscape:** top 2/3 = card art (left) + price-change stat cards (right, one per printing/variant via `statRows`); bottom 1/3 = price chart (`drawPosterChart`, reflects live range/Low/Market/Foil toggles) + inline legend; footer = logo + "packs.ink · date".
- **Card banner tile** (`CardDetailModal` image column, `CardTilePreview`) → `drawCardTileCanvas(canvas, opts)`. **Canvas-drawn, compact portrait** (the front-page mover-tile look): art → name → "Rarity · Foil" → Low/Mkt → 1D/1W/1M Δ% grid → footer. **The on-screen preview IS the canvas**, so the preview and the copied image are pixel-identical. Camera button `.card-tile-cam` copies the already-drawn canvas (`canvas.toBlob`). Replaces the plain modal image once price history loads (`tileRow` = Normal-preferred printing); falls back to a plain `<img>` for cards with no history.
- **Mover banner tile** (`MoverTile`, front-page banners): camera button `.mt-export-btn` → `copyMoverTileImage(tileEl)` → `captureMoverTileBlob` (**still html2canvas**). Captures the tile + a normally-hidden footer (`.mt-export-footer`, `display:none` live, flipped to flex in the `onclone`).

### In-modal "Price changes" panel (not an image — the live DOM panel)
`.card-detail-screener` renders below the card info, always visible. `ScreenerStatsRow` shows a banner-tile-style delta grid (6 windows × LOW/MKT) per printing, computed client-side from price history via `computeSeriesDeltas(rows, "low_price"|"market_price")` (windows in `CARD_DELTA_WINDOWS`). Each row has a **"Buy on TCGplayer"** affiliate link (`.cd-stat-buy`, via `tcgUrl(productId, printing)` — correct per-printing SKU). A **"Show all variants"** button (`variantRows`, fetched on expand) adds a row for every other (card_id, printing) sharing the Product Name. Catalog reached via `CatalogContext` (provided at the App root, value = `raw`). The same `statRows` array feeds the canvas card poster.

### html2canvas-1.4.1 gotchas (apply to the mover tile + ANY future html2canvas export)
1. **Clipboard write must be SYNCHRONOUS within the user gesture.** Capture fn returns `Promise<Blob>`; the click handler calls `navigator.clipboard.write([new ClipboardItem({"image/png": blobPromise})])` *immediately* (handler NOT async). The canvas exports keep this same sync-clipboard pattern.
2. **`ignoreElements` to avoid cloning the whole document.** Else html2canvas decodes every `<img>` in the clone — the Cards grid is ~41k nodes / ~3k imgs. (The old card-poster "20s hang" was actually the cold ~200KB html2canvas CDN fetch inside the click, not the render; capture itself is <1s WITH ignoreElements.)
3. **Off-screen capture needs explicit `width`/`height`/`windowWidth`/`windowHeight`** or it reflows tall-and-narrow.
4. **No flex `gap` / `justify-content:space-between` / empty styled marker spans** — use inline-block+margins, text-align, text glyphs (`●`/`━`/`┅`).
5. **Image URLs absolute + CORS-safe** — `window.location.origin + "/Logos/..."`; Lorcast art via `/img-proxy/` + `crossOrigin="anonymous"`, awaited before capture.

`flashToast()` (module-level) is the transient bottom-center toast all three flows use. Footer/brand text uses `--accent` (gold) so it reads in both themes.
