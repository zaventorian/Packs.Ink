# Deck import from a PICTURE of a deck (2026-09-08)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Paste or drop a deck poster into Decks » Import decklist and it reads the cards off
the image. Works on dreamborn / duels.ink / packs.ink posters and tournament
graphics, and on screenshots of them. `CardScanner.scanDeckImage(src)` in
`scanner.js`; `DeckImageImport` (above `deckToText`) is the review UI.

**It reuses the card scanner's shipped index wholesale, and that is the whole
trick.** `build_index.py` descriptors the FULL Lorcast card face, not an art crop —
so a poster cell is the same picture the reference vector was built from, merely
scaled. No glare, no perspective, no white balance. Matching is the easy half;
measured **83/83 across five real posters**, and counts 100/100 across six. Nothing is downloaded that the scanner
doesn't already fetch (index.json + color.bin + dhash.bin, ~2.1 MB, cached).

- **Finding the lattice is the actual work.** The pitch comes from autocorrelating
  a detail profile, and **autocorrelation peaks just as hard at 2x and 3x the true
  pitch** — without the integer sub-multiple candidates a 7-wide poster reads as 3
  columns of double-width cells and every crop is half of two different cards.
- **⚠ Candidate lattices are scored by ESTIMATED CARD YIELD** (soft count of
  confident cells x cell count), never by mean or median cosine. Empty trailing
  cells drag a median down, so the lattice finding MORE cards scores WORSE — that
  bug silently imported a 3-row poster as its middle row only, 8 of 17 cards, with
  every one of those 8 correct and confident. A wrong answer that looks right.
- **The yield gate is deliberately loose (30%), because the probe is UNREFINED.**
  Refining every candidate costs ~10x, so on small cards a correct lattice can sit
  under the confidence line on half its cells and still be right: the RoV-Teacup
  poster's real 8x3 grid probed at 0.4, scored 3x better than everything else, and
  a 0.5 gate threw it away. The per-cell pass refines afterwards and drops whatever
  is still not a card.
- **A slightly-off crop is the entire error mode.** All three misses in testing were
  misalignment, and a small offset/scale search recovered the right card every time
  (dHash hamming 11-18 -> 4-6). `refineCell` runs only on cells under 0.96 cosine.
- **Review before import is not optional**, same call as the camera scanner's
  permanent `SCANNER_QA_ONLY`. The grid shows the crop it actually matched next to
  the name it chose, so a version confusion (Mushu *Sneaky* vs *Stealthy Dragon*)
  is visible rather than inferred.
### Counts ARE read (2026-09-08) — and the chip is located from the MEAN

First cut shipped with every count defaulting to 4, because locating the chip
inside a single cell fails: the card's own dark border floods into it. **The fix is
to locate it ONCE from the mean of every cell's top-right corner.** Card art differs
per cell and averages away; the chip is in the same place on every card so it
survives. Measured **100/100 across six real posters, every one summing to exactly
60**, in Chromium against the shipped code.

- **Look for the DIGIT, not the chip.** The card's dark border survives the mean too,
  so thresholding for a dark chip finds one blob spanning border + chip. The digit is
  a small BRIGHT feature on a dark ground — a grey top-hat (`mean - greyOpen(mean,11)`)
  isolates it cleanly, and blobs touching the ROI edge are dropped as card edges.
- **⚠ Glyph templates are BAKED (`QTPL_B64`), never rendered at runtime.** Canvas font
  rendering depends on what the viewer has installed: on a headless Linux box "Arial",
  "Verdana" and "Helvetica" all collapse to one fallback face, which silently strips
  the shape diversity the classifier needs. ~3KB of 20x22 1-bit bitmaps, identical
  everywhere. Regenerate from Liberation Sans (Bold/Regular), DejaVu Sans Bold and
  FreeSans (Bold/Regular) if it ever needs extending.
- **The two "1" shapes both have to be in the set.** Liberation and DejaVu draw "1"
  with a full base bar; Arial and every poster generator draw a bare flag-and-stem.
  With only the barred shape in the templates, a real "1" read as 3, then as 4.
- **⚠ The normalisation box is 20x22, and that width is load-bearing.** At 14x22 a
  glyph wider than 0.64 clamped to full width — so a "4" (0.83) and a "1" (0.45) both
  filled the box and the one feature separating them was gone. Scale to the box
  HEIGHT and centre horizontally; never stretch to fill.
- **Merged glyphs are split, not rejected.** At low resolution "2x" bridges into one
  blob whose aspect fails the digit test, which took a whole cell to unreadable.
  `splitWide` cuts at the emptiest column near the middle and re-tightens each half.
- **Filter components by HEIGHT before counting them.** The digits are the tallest
  things in the zone; art bleeding into the crop is shorter. Bailing on a raw
  component count instead threw away a good "2" because Chernabog's art added a
  fourth blob.
- An unread badge still falls back to 4 and is marked (dotted underline) in the
  review grid; the **N / 60** total remains the checksum, since a Lorcana deck is
  exactly 60 cards.

### The pitch sweep, and the resolution floor

- **⚠ Autocorrelation proposes harmonics of the strongest periodicity, which is not
  always the card pitch.** A 1023px dreamborn poster's top peak was **2.58x** the true
  pitch, so no integer sub-multiple could ever land on it and the whole poster read
  as "no grid". `sweepPitches` walks pitches directly in 3.5% steps as a fallback,
  and runs only when the autocorrelation candidates yield nothing — so the common
  case keeps its speed.
- Resolution floor is about **150px per card**. A screenshot that also contains
  browser tabs, a video call or a desktop around the poster is the case that still
  fails: the surrounding chrome pollutes the row/column profiles and no lattice wins.
  **Cropping to just the cards fixes it** — verified on the Zoom screen-share that
  fails whole (cosines ≤0.79) and reads at 0.89–0.98 once cropped. Raising the
  detail-map target was tried and reverted: it did not rescue that image and doubled
  the failure time to 14s.
- Applies through the existing `parseDeckText`, with names resolved via
  `card_id -> catalog row -> "Product Name"` (the same id join `resolveGroup` uses),
  so set/printing disambiguation stays in one place.

Guarded by `node scripts/test_deck_image.mjs` (the lattice maths, no canvas needed).

### ⚠ dHash in scanner.js was bit-reversed — fixed 2026-09-08

`descriptors.py` packs dhash64 **MSB-first** (`out = (out << 1) | b`) and `dhash.bin`
is written from that, so the first bit is uint64 bit 63. `scanner.js` packed
**LSB-first**, reversing the whole 64-bit run — so every hamming distance landed at
**~32/64, i.e. random**, and the dHash tiebreaker in `searchCrop` contributed noise
rather than signal for as long as it has shipped. Verified in Chromium against the
shipped index: bit-reversing the query hash took correct matches from 30-47 down to
3-14, and fixed a real misread on the spot (Develop Your Brain, which had been
reading as Prince John).

**The fix is CONFIRMED, and it does NOT move the camera scanner — measured 2026-09-20.**
Replayed the shipped `dhash64` in Chromium against the shipped `dhash.bin` over 80 cards:

| query image | dHash hamming to the truth card | colour top-1 |
|---|---|---|
| clean Lorcast art (`data/img/*.avif`) | median **9.5**, 79/80 ≤ 16 (reversed packing: **38**) | **70/80** |
| the stored camera crop of the same card | median **33** — no signal | **0/40** |

So the bit order is right (9.5 vs 38 settles it), and the 98.2% figure is **not** in
doubt from this change after all — the earlier worry here is retired.

**⚠ But the whole VISUAL path is inert on camera photos.** Colour goes 87.5% → 0% top-1
and dHash lands *further* from the truth card than two random reference cards are from
each other (median 33 vs a 21 random-pair baseline). A camera scan's identity is carried
**entirely by OCR**; `searchCrop`'s `lambda * (ham/64)` re-rank is operating on noise
there, and always was. Not a framing bug — insetting the crop 2–16% to drop the
background margin was tried and changes nothing (top-1 stays 0–2/80 at every inset).
The same machinery is exactly right for the DECK IMAGE importer, whose poster cells are
the clean renders the index was built from — which is where the 9/8 fix pays off and why
that importer measures 83/83.

**Ablated it to be sure, same day**: replaying the 400-read baseline through `identify()`
with `colourRanked: []` instead of the recorded ranking scores **card_id 217/265 (vs 213)
and name+version 316/400 (vs 319)** — colour is load-bearing on 3 rows and actively hurts
on 4. So it is net NOTHING on camera reads, not a win to rip out and not a loss to keep;
the opportunity there is the per-frame CPU, not accuracy. (Split by `identify()` source it
is more interesting than the total: colour HELPS the `fusion` path 73→70 and HURTS the
`name` path 228→232, so the leverage is in the fusion-vs-name routing, not in the signal.)
Reproduce with `scripts/scanner/replay_common.mjs` — run `scoreRows` twice, once passing
each row's `colour` and once passing `[]`.

### The matcher has a regression guard — `node scripts/test_scanner_matcher.mjs` (2026-09-20)

Replays **400 real recorded OCR reads** (`scripts/scanner/replay_baseline.json`, frozen out
of `scan_samples`) through the REAL `scanner.js` `identify()`. Offline — no network, no
photos, ~30s. Nothing guarded the matcher before this; every scanner edit was unverified.

- **It pins the per-row PASS SET, not just the totals.** A change that fixes three cards and
  breaks three others leaves every count identical, and that swap is exactly what is worth
  catching. The test names each row that went from right to wrong, with its OCR read.
- **It pins the DENOMINATORS too** — a row that stops producing any answer would otherwise
  shrink the total and make the accuracy *ratio* look better.
- Newly-correct rows are REPORTED, never failed; they are the reason to re-freeze.
- **⚠ Re-freezing (`node scripts/scanner/freeze_replay_baseline.mjs`) re-baselines whatever
  the matcher does TODAY**, so running it to silence a red test blesses the regression. Read
  the named rows first. `python scripts/scanner/pull_replay_corpus.py` (needs `.env`) refreshes
  the rows themselves from the table.
- `replay_lines.mjs` stays the interactive A/B tool (diffs two builds, prints every changed
  verdict); both share `scripts/scanner/replay_common.mjs` so they can't disagree about what
  "correct" means.
- Measured the day it landed, working tree vs v16b (`7fe3540`, the build the 98.2% came from):
  **card_id-exact 189 → 213 of 265, name+version 297 → 319 of 400, 38 verdicts changed, 0
  regressions.** So v17–v20 only moved forward. The baseline is pinned at those numbers.
  ⚠ That corpus is review-weighted (rows a tester had to look at), so **80% here is not
  comparable to the 98.2% precision figure** — different denominators, don't quote them together.
