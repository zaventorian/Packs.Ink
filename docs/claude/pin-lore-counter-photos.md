# Pin + lore-counter photos (2026-08-24)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

45 pins and 25 lore counters render on their own Collection tab (Pins & Counters — see the next
section; until 2026-09-11 they were tiles at the foot of the Sealed tab), from the static
`LORCANA_PINS` / `LORCANA_LORE_COUNTERS` consts — there is no feed behind either. The photos are
cut out and served from our own storage.

**A pin can come in a RETAIL BOX**, not just an event kit / convention / prize wall — n:45 ships
inside the Costco Best Buddies Bundle (TCGplayer 719823; it began as a `SEALED_EXCLUSIVES` row),
which is also where 18/PD1 and 19/PD1 come from. Its photo is a cut from the announcement shot
rather than a studio one and is worth re-cutting from a better source, which is a re-upload
rather than a code edit — it sits at `pins/45.png` like every other entry. **TCGplayer's bundle
photo is NOT that source** (checked 2026-09-27): the pin sits behind the blister at ~80px there,
no sharper than the cut we have. `EXPECTED_PINS` in `upload_collectible_photos.py` tracks
the highest valid `n`, so it moves with the list (45 today, counters 26).

**⚠ Do NOT credit a photo source anywhere user-facing.** The Help credits paragraph and
`privacy.html`'s takedown line both named one until 2026-09-13, when Zaven asked for it gone
("PLEASE remove this from any mention on the site"). The takedown route in `privacy.html` is what
covers this and it stays. Internal notes about where a photo was *found* are fine — a credit
printed to users is not.

- **`collectibleArtUrl(folder, n)`** derives the URL from `n`:
  `card-art/collectibles/{pins|counters}/NN.png`. That makes **`n` the stable id twice over** —
  it keys the owned mark AND names the photo — so renumbering an entry both moves someone's
  collection and silently repoints its art. Take the next free `n`, never renumber.

### ⚠ Release order is the ARRAY's order, not `n` (2026-09-12)

**Both lists were a faithful copy of lorcanaplayer.com's two list pages — including that
source's own omissions.** Backfilling them is what split the two numbers, because a
late-discovered 2022 pin cannot be given a 2022 `n` without renumbering. So **`n` is only an
id; `collectible_seq` (the array index, stamped by `_collectibleRow`) is release order**, and a
backfill goes at its CHRONOLOGICAL position in the array with whatever `n` is free. The two
`SealedCollectionView` sorts read `collectible_seq` — sorting on `n` files the Steel pin after
the Oct 2026 entries. Every pre-existing entry had `n == index + 1`, so the swap reordered
nothing that had shipped.

What was missing, and why none of it was visible: the site agreed with its source exactly, and
the source is a fan site with gaps.

| Added | Evidence |
|---|---|
| **Steel Ink Symbol** pin (`n:42`, Wilds Unknown league) | Completes the six-ink run, one per season — Amber/Amethyst/Emerald/Ruby/Sapphire were all present. Pin & Pop dates it 2026-05-08, which is Wilds Unknown's own `SET_RELEASE_DATES` LGS date, and its Sapphire date (2026-02-13) matches our record to the day. |
| **Mickey - Brave Little Tailor (card-backed)** (`n:43`) and **Maleficent Logo (Purple) (card-backed)** (`n:44`) | Both 2022 pins shipped two ways — loose in a baggie, or on a printed cardboard backer. Collectors track the backer separately, so it is its own entry. The `n:1` / `n:2` sources now say "pin only" and name D23 Expo 2022 rather than a league season that did not exist for another year. |
| **Wilds Unknown** trove counter (`n:22`) | disneylorcana.com's own product page: "eight booster packs, storage box, lore counter, and six damage dice". Our trove run jumped Winterspell → Attack of the Vine!. |
| **Elsa**, China exclusive (`n:23`) | Simplified Chinese organized play, which ran its own season from Jan 2025 with its own promos and appears on no English-language list. |

- **Still open, deliberately not invented**: a second Chinese counter ("Purple", known only from a
  secondary-market "set of 2" listing), and the Wilds Unknown / Attack of the Vine! **Weekly Play**
  counters — lorcanaplayer says every Weekly Play season has had one but documents neither, and a
  guessed name would mint a permanent `n` and a permanent photo path for it.
- **`noArt: true`** means "real photo still wanted". Until 2026-09-12 an entry with no uploaded
  photo rendered a broken `<img>`, because `collectibleArtUrl` always returns a URL — so the
  glyph stand-ins were only ever reachable in theory. Now `image_url` goes null and `collectiblePh`
  draws `COLLECTIBLE_GLYPHS` at **all six** CollectiblesView render sites (both boards, the tray,
  the add drawer, the checklist row, the drag ghost), sized per context in styles.css because every
  sizing rule there is `img`-scoped. The aspect probe skips photoless pins, and they are excluded
  from `aspectsReady` — a pin that can never report an aspect must not hold the
  first-arrangement gate open.
- **All five landed 2026-09-13 — every catalogued pin and counter now has a photo, and `noArt`
  currently marks nothing.** Keep the flag and `COLLECTIBLE_GLYPHS`: the next entry will need them.
  - `n:43` / `n:44`, the card-backed 2022 pins, were **gallery shots on the `n:1` / `n:2` product
    pages** of the site the list was scraped from, not products of their own — which is exactly why
    a scrape of the LIST pages missed them. Take `-Pin-1`, not `-Pin-2` (the card still sealed in
    its baggie) and not `-Pin-Back` (the reverse of the pin, not a backer card). **Read a product
    page's GALLERY, not just its main image.**
  - `n:42` (Steel), `n:22` (Wilds Unknown trove) and `n:23` (Elsa) came from Zaven, after a walk of
    both product sitemaps found none of them. That walk is still worth knowing:
    `product-sitemap.xml` is a partial view — the real ones are `product-sitemap1.xml` +
    `product-sitemap2.xml`, listed in `sitemap_index.xml` — and a single-file fetch makes a product
    that exists look absent.
- **⚠ The Wilds Unknown TROVE counter is the Woody-and-Buzz one**, confirmed against the product
  coverage, so the Merida dial photographed beside it is a different counter and is NOT `n:22`.
  Getting that pair the wrong way round would put the wrong art on a tile permanently.
- **The two missing Weekly Play counters landed 2026-09-13: `n:24` Merida (Wilds Unknown) and
  `n:25` Winnie the Pooh - Hunny Archmage (Attack of the Vine!, first event).** That closes the gap
  this file used to describe as "lorcanaplayer says every Weekly Play season has had one but
  documents neither" — it documents the Trove dials on its list page and the Weekly Play ones only
  as separate `/product/` pages, and it has neither of these.
  - **⚠ Both are named for their ART, not their set, and that is load-bearing.** `n:22` is already
    "Wilds Unknown" and `n:21` "Attack of the Vine!" — the Trove dials — so a set name here would
    give one season two identically-named counters and leave the source line as the only thing
    telling them apart.
  - **⚠ "Hunny Archmage" (Attack of the Vine! 40/207) is NOT "Hunny Wizard"** (Rise of the Floodborn
    59/204, which is the pin at `LORCANA_PINS` n:8). Two different Pooh-as-wizard cards two sets
    apart; the counter art was checked against Lorcast to pick the right one.
- Adding an entry still means uploading its photo in the same commit, or flagging it `noArt`.
- **⚠ `EXPECTED_PINS` / `EXPECTED_COUNTERS` in `upload_collectible_photos.py` are the highest
  valid `n`, not a photo count**, and they bound the "unexpected number" warning — so they track
  the list length (**45 / 26** as of 2026-09-30), even where an entry has no photo to upload.
- **`scripts/cut_collectible_bg.py`** removes the white studio background. Two things make it
  work: the background is found by **flood fill from the border**, not by "white → transparent"
  (which punches straight through Baymax, every logo pin and every ink symbol's highlight); and
  the alpha is **eroded one pixel** before feathering, because a JPEG of a dark object on white
  has an edge ring of genuinely half-white pixels that reads as a bright fringe on a dark theme.
- **The near-white threshold is a LADDER, not a constant, and the escalation is measured.** The
  Winterspell counter is Stitch in *snow* photographed on white, and the loose setting leaked
  through the subject and ate a hole in the drift. The leak signal is **raggedness** — the cut's
  perimeter over that of an equal-area circle. Across all 62 real photos every clean cut measured
  ≤ 1.65 and that one leak measured **4.40**, so the 1.8 cutoff sits in empty space. Enclosed-hole
  detection alone does NOT catch it: the fill usually stays connected to the outside and eats a
  bay rather than an island. Exactly one image escalates today.
- **⚠ A source the ladder cannot see AT ALL comes back uncut, not wrong — and only the `CHECK`
  flag says so.** The 2023 card-backed pin shots are that case: their studio surface measures
  **159–220** on the darkest channel with saturation to **36**, and the loosest rung is
  `(226, 22)`, so no rung ever classified it as background. The cut returned the photograph
  untouched — 0 transparent pixels, studio grey still in all four corners — and on the contact
  sheet at thumbnail size that grey rectangle reads as the card. Believe `opaque 100.0%` over
  your eyes. `--white-min` (with `--sat-max`, default 40) **prepends** a looser rung for one run;
  it is an override rather than a fifth rung because the four were measured over all 62 shipped
  photos and re-measuring needs sources we no longer have. It is safe because a prepended rung is
  walked and leak-gated like any other: if it leaks, the standard ladder takes over.
- **`scripts/cut_hex_collectible.py` is the OTHER cutter, for a photo with no plain background at
  all** — a counter shot on set art, on a mat, or grabbed out of a carousel. `cut_collectible_bg.py`
  has no answer there: its whole design is "near-white AND connected to the frame edge", and there
  is no background colour to fill. So this one does not look for background; it knows a lore counter
  is a **regular hexagon**, fits one to the subject, and masks to it.
  - **⚠ Fit against the subject mask's CONVEX HULL, not the raw mask.** GrabCut's silhouette has
    bites out of it wherever the dial's own art goes dark at the rim, and fitting to the bitten
    shape drags the hexagon inward and twists it to cover the damage. Measured on the Elsa dial:
    **IoU 0.76 with two corners sliced off, against 0.94 on the hull.**
  - **⚠ Its failure mode is not a hole or a fringe** — the mask is a clean polygon by construction —
    **it is a hexagon in the wrong PLACE**, which crops the dial and keeps a wedge of background,
    and at thumbnail size that reads as a real photo. Hence `--debug` overlays, an IoU floor, and a
    fill check. **⚠ Measure fill against the POLYGON's own bbox, never the frame's**: a hexagon is
    always 0.6495 of its own bbox but can occupy any fraction of the photo it was cropped from —
    getting that wrong fires the warning on every correct cut.
  - Two counters in one frame is fine: the subject mask keeps only the component touching the
    centre, so crop roughly around each and run it twice.
  - **⚠ A DROP SHADOW is the fit's other blind spot, and widening the aspect search does not fix
    it** (tried, on the Attack of the Vine promo — it changed the answer by 0.03). GrabCut takes
    the shadow for part of the dial, the hull inherits it, and the best-covering hexagon of that
    shape sits low and tall: it crops the dial's top and lets a wedge of background in at both
    bottom corners, **scoring IoU 0.95 while doing it**. The score cannot see this; `--debug` can.
  - **`--hex` and `--poly` are the escape hatches, and `--poly` is the one that usually works.** A
    dial photographed off-square is a hexagon in PERSPECTIVE — the AotV promo is 1.19x wider than
    tall AND taller than a regular hexagon of that width, so no scaled regular hexagon fits it at
    all and `--hex` only trades one error for another. Six hand-placed vertices, read off a
    coordinate grid over the crop, take about two minutes and are exact.
  - **Verify a cut by measuring, not by looking**: distance-transform the alpha and count pixels
    near the background colour within ~3px of the edge. The art's own foliage will read as
    "background-coloured" deep inside the shape and means nothing.
- **A card-backed pin is a RECTANGLE, so ~89% opaque is the right answer, not a failed cut.** The
  transparent tenth is the 2% pad ring plus the rounded corners. Check it by measuring — corner
  alpha, and whether any near-white opaque pixel still touches the frame edge — rather than by
  eye.
- Output is 400px, palette-quantized (FASTOCTREE is the one Pillow quantizer that keeps alpha) —
  ~40 KB each, 2.4 MB for all 62, against ~15 MB unquantized at 600px.
- **`--contact` writes a split light/dark sheet. Look at it.** Background removal fails per-image
  and quietly, and the first pass shipped a shredded counter that I did not catch at thumbnail
  size.
- **lorcanaplayer.com 403s both curl and a headless browser**, and waiting out the challenge does
  not work. Use a fetch tool for the page text; pull the image bytes from the Jetpack mirror at
  `i0.wp.com/lorcanaplayer.com/wp-content/uploads/...`, which serves the same files. The Weekly
  Play counters are not in the counters page's HTML at all — the product sitemaps enumerate them
  and each `/product/` page carries its photo path. **Read `product-sitemap1.xml` AND
  `product-sitemap2.xml`** (they are what `sitemap_index.xml` lists); bare `product-sitemap.xml`
  answers with a partial view and makes a product that exists look absent. And a product page's
  GALLERY is worth reading, not just its main image — two of our missing pins were only ever
  gallery shots on another pin's page.
