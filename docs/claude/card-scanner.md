# Card scanner — PUBLIC BETA 2026-08-04

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Camera → identify → review → save. **Identification is 100% on-device**: `scanner.js` (the matcher) + OpenCV in `scanner-worker.js` (detect, rectify, and the ORB version check) + PP-OCRv3 ONNX in `scanner-ocr-worker.js`, matched against index files the browser downloads once. (`scanner-cv.js` was a dead main-thread copy of the worker's job and is gone, 2026-09-27.) No frame is ever sent anywhere to be read — say this plainly in any user-facing copy, it's the feature's best property and it's true.

Accuracy work (round-by-round history, replay harness, the miss taxonomy) lives in the **`project-scanner-spec` memory** — read its NEW-SESSION HANDOFF before touching the matcher. This section is only the shipping/consent surface.

### Gating

- **`canScan = true`** in App — everyone gets the 📷 button, **and since 2026-09-27 a signed-out visitor can actually SCAN** (see "Scanning signed out" below); an account is asked for only to save. It was `isGradedAdmin || isScannerTester`; the client-side `is_scanner_tester()` probe is GONE (it fired on every sign-in to answer a question no longer asked).
- **`scanner_testers` + `is_scanner_tester()` still gate the WRITE path in the repo's own migrations — and that is the open question of the 2026-09-04 audit.** Migration 98 requires `is_scanner_tester() OR is_graded_admin()` on `scan_samples` INSERT/UPDATE and on the `scan-samples` storage INSERT (the READ policy is 91's owner-or-graded-admin and never mentions testers). No later migration drops that clause, so either every non-allowlisted user's uploads have been failing silently since the public beta (`uploadSample` swallows every error) or the live policy was changed outside the repo. **`supabase/132_scan_samples_public_beta.sql` — APPLIED 2026-09-05 by Zaven** — drops the tester clause and adds a per-user rolling-24h storage-object cap (3000 = 1000 rows × 3 objects), so public uploads work from that day whichever way the history went. Whether `scanner_testers` / `is_scanner_tester()` still have any referrer is a question for §1 of `supabase/diagnostics/public_release_live_checks.sql`; don't drop them without running it.
- **`SCANNER_QA_ONLY` stays `true` — PERMANENTLY, as of 2026-08-23.** Zaven's call: *"I don't want auto-add to collection; let the user confirm the list after running a session."* Review-before-save is the shipping UX, so the ≥95% precision bar gates nothing any more; flipping this to false restores the Stack-scan / Single auto-add flow and needs a new product decision, not a metric.
  - **The bar was measured anyway that day, the honest way** (photo-verify a random sample of UNREVIEWED shown-✓ rows — labelled rows cannot tell you, per round 11): 170 v16 samples judged against official art in two disjoint seeded rounds → **167 correct = 98.2%, one-sided 95% lower bound 95.7%. It clears.** Retired pre-v16 builds: 83.3% (25/30); the gap is real (Fisher exact p=0.009), so v16's matcher work is what moved it. All 3 v16 misses were name/art collisions between distinct cards (Minnie *Curious Adventurer* vs *Drum Major*; *Genie - Hard to Grasp* read as *Gene - Niceland Resident*; one red-panda song read as another) — exactly the class review catches. Method, if it ever needs re-running: pull `scan_samples` where `reviewed=false AND corrected=false AND debug->>conf='high'`, seeded-sample per build, compose side-by-side sheets of the stored scan crop vs the claimed card's `image_normal`, judge each pair, then Wilson-interval the result.

### Scanning signed out (2026-09-27)

The 2026-09-26 audit's headline: 13 consents ever, **0 cards saved** through the scanner
since the beta, and a consent screen whose only button was "Sign in to scan". A guest
can scan now; an account is asked for only to SAVE. Guarded by
`node scripts/test_scanner_guest.mjs`, which pins every point below at source (every
way this breaks is silent) and checks the three copy places agree.

- **Nothing is uploaded while signed out — no photo, no label, no session telemetry.**
  That is a different promise from the upload notice, so it is a different notice
  (`guestPanel`) accepted under its own key (`SCAN_GUEST_OK_KEY`). Signing in still
  shows the upload notice; a guest's acceptance never carries into an account.
- **⚠ The upload gate is the SNAP's flag (`job.guest`), never `user`.** The native
  app signs in without leaving the page, so a guest's snap still queued when the
  account arrives would otherwise upload under it. Rows carry `guest: true` too, and
  `labelSample` bails on it. Session telemetry belongs to whoever STARTED the camera
  (`sessionUser`), not whoever is signed in when it stops.
- **⚠ The account's consent effect sets `consentOk` EITHER way** (`setConsentOk(local)`,
  not `if(local) setConsentOk(true)`), or the camera keeps running on the guest's
  acceptance until the account's record comes back.
- **Saving:** "Sign in to add N" (`qaSignInToSave`) **awaits** the IDB write of the list
  under `scanSession:guest` (the persist effect's 600ms debounce would lose it on the
  way out), leaves a resume flag (`SCAN_RESUME_KEY`, 30 min), then signs in. App reopens
  the scanner once `user` arrives (that effect sits BELOW `user`'s declaration — above
  it, its deps array is a TDZ ReferenceError); the scanner consumes the flag and lands
  on the review screen; the restore moves the guest list into the account (written
  under the account BEFORE the guest copy is deleted).
- **A returning guest reaches the review screen before the upload notice**
  (`reviewOnly`): saving opens no camera and uploads nothing. "← Camera" shows the
  notice.
- **A dead camera no longer takes the list with it.** The error screen (blocked /
  no camera / camera error) offers "Review N scans" whenever there are rows, and the
  review screen renders over the dead stage. Before this, a phone with the camera
  blocked could never reach its own scanned list.
- **`/scan` is a real route** (`PATH_TO_VIEW`, `LANDED_ON_SCAN`): it rewrites the address
  to `/` and opens the scanner, so the Scan tab is an `<a href="/scan">` like every other
  nav target, and `manifest.json` carries a **"Scan a card" app shortcut** (long-press the
  installed icon).
  - **⚠ A `/scan` landing opens the modal BEFORE the deferred `scanner.js` has run**, so
    the mount effect waits for `window.CardScanner` (up to 20s) instead of reading it once.
    Read once, anyone who had already accepted the notice got "Scanner unavailable" on
    exactly the link this route exists for.

### Which PRINTING: the ORB version check (2026-09-26)

The name read settles WHICH CHARACTER well and WHICH PRINTING badly, and colour carries
no signal on a camera photo (41% right version on 860 field crops). After the name read,
`verifyIdentity` asks the detector worker to match ORB keypoints of the snap against each
candidate printing's own catalog art and count RANSAC homography inliers — **97–98% right
version** on human-reviewed crops, and it works on a bad rectify because a homography does
not care where the card sits in the crop. `scanner-worker.js` only MEASURES; the pure
functions in Index.html's "ORB version verification" block DECIDE. Guarded by
`node scripts/test_scanner_verify.mjs`.

- **Confident = the winner has ≥ 20 inliers AND ≥ 1.6× the best non-twin**
  (`SCAN_ORB`). Candidates: the pick, identify's alternates, then the character's other
  printings (`scannerFamilyOf`, case-folded like the version chips), capped at 8.
- **ART TWINS (an Epic and its base, a reprint across sets) are a TIE with the winner**,
  not the runner-up it must beat (thumbnail NCC > 0.97). A tie goes to the **registered
  collector-number read**: the homography warps the full-resolution photo onto the
  winner's canonical frame, the number line then sits at a known spot (y .952–.992,
  x .015–.34), and rec (no detector) reads it at three vertical offsets. `scanCnPick`
  matches that ONLY against the tied cards' own numbers — every offset that reads must
  agree, an exact number whose set clearly disagrees abstains, and a one-glyph miss is
  accepted only when every other tied card is two edits further. Unread, the row keeps
  its ≈ and stays within the tied group.
- **A confident ORB result may change the VERSION of the character the name read found,
  but when a DECISIVE name read and the art disagree about the CHARACTER the row shows
  both (≈) rather than siding with either.**
- **The old look (second OCR pass) runs only when ORB was not confident** (`orbDecided`).
  Its name re-read could only flip ORB's version back to a text guess.
- **⚠ A NOT-confident ORB winner does not replace the read's pick** — measured, not assumed:
  on the 60 field rows where ORB ran but fell short of the margin, its winner was right 32
  times and the read's pick 34. The row keeps the read's pick and shows ≈ with the rest.
- **The family fill is ranked by the version text the read found** (`scanFamilyByText`),
  because a third of the index sits in a family bigger than the 8-candidate cap (Mickey
  Mouse 61, Minnie 36) and index order let the right printing of a popular character go
  unchecked.
  - **Measured and NOT shipped: sending a non-decisive read's OTHER-character candidates to
    the art check.** On all 275 field crops it changed exactly one answer, and
    made it worse: a glare-washed *Winifred - Exasperated Elephant* that the read called
    *Swordplay* at low confidence (honestly unsure, no ✓) came back as *Starkey - Devious
    Pirate* with 26 inliers and a ✓. It also cost ~0.35s on the uncertain scans it touched.
    **⚠ When the right card is not among the candidates, ORB still finds 20+ inliers on some
    other card's art** — Winifred was never checked. Widening the candidates across
    characters buys spurious matches, not answers; a future change there needs a higher
    inlier bar for a character switch than for a version switch.
- **⚠ References go to the shared detector worker ONE PER MESSAGE** (`verify-ref`). The
  live loop waits on every detect reply, and one message carrying a cold family's eight
  ORB extractions froze the live badge for all of them.
- The snap path's primary read **dets the name at max-side 544** (`NAME_DET_SIDE`; 162 vs
  343ms desktop and MORE accurate — char 92.7% vs 89.3%) and **skips the subtitle band**
  (2–3× the name read's cost, and ORB answers the question it existed for).
- **`window.__scanBench(canvas, opts)`** runs exactly this pipeline on a canvas —
  `{rect:true}` skips capture, `{band:true, verify:false}` is the pre-ORB path. The field
  set lives in `scripts/scanner/data/field_eval/` (gitignored; README inside), served by the
  dev server. It is defined INSIDE the scanner modal, so open the scanner first (`/scan`
  does it); the Browser pane cannot fetch other localhost ports, so serve the crops from the
  same dev server the page is on.
  **⚠ Persist a long bench's results as it goes** (localStorage): the scanner reloads its
  tab whenever a new service worker takes control, so opening the site in another tab
  after an `sw.js` edit wipes an in-memory run.
- **Measured 2026-09-27 on the 275 human-reviewed field crops** (`{rect:true}`): exact card
  **82.9%**, right name+version **87.6%**, a ✓ on **74.2%** of rows at 97.5% name+version
  precision by label — and **every ✓ that disagreed with its label was a MISLABEL on
  inspection** (the printed `N/204 · EN · set` line settles it), so judge a ✓ by eye, never by
  the label. Against the pre-ORB path on the first 110 rows: ✓ shown 49.1% → 76.4%,
  name+version 84.5% → 87.3%, median 7.3s → 2.8s (desktop).
- **Perfect framing is worth ~4 points, not a rewrite.** The same frames warped by their
  SIFT-registered true quads (`truerect/`) score exact 86.1% / name+version 92.3% / ✓ 79.2%
  on 274 rows, against 83.2% / 88.0% / 74.1% on the field crops. Some field frames never held
  the whole card (a close-up of the text box), which no detector can frame — so asking people
  to fit the whole card in view may be worth as much as detector work. A thinner-edge
  detector variant raised correct framing 19% → 37% but put the quad INSIDE the card 25% of
  the time, cutting the name off: measured and not shipped.

### The index follows the catalog; its assets survive deploys (2026-09-26)

- **The catalog supplement.** `scanner/text.json` + `index.json` are built by hand and ship
  with a deploy, so a card Lorcast indexed after the last build could not be scanned until
  somebody rebuilt AND redeployed. When the scanner opens, the page hands it every catalog
  card its index lacks (`scannerExtraRows` → `CardScanner.addCards`); name matching and the
  review rows work the day a card reaches the catalog. Colour stays build-only (it carries
  no signal on camera photos anyway). The review paths resolve ids through ONE lookup,
  `scannerMetaMap()`. Guarded by `node scripts/test_scanner_extra.mjs`.
- **One image rule for both index builders** (`scanner_scope.card_image`: normal, then large,
  then small); `test_scanner_scope.py` pins text ⊆ index. Unreleased cards carry `d` (release
  date) in text.json and lose `UNRELEASED_PENALTY` on a one-line name read until release day
  (`test_scanner_unreleased.mjs`).
- **`packsink-scan-v1`** (`SCAN_CACHE` in sw.js) keeps the scanner's ~37 MB — PP-OCR models,
  onnxruntime wasm, OpenCV, the indexes — ACROSS deploys, like `packsink-img-v1`. Before it,
  every deploy made every returning scanner user download all of it again. Served cache-first
  by exact URL; a new `?v=` evicts the old entry for that path.
  - **⚠ A persistent cache turns a forgotten version bump into stale bytes FOREVER.**
    `node scripts/test_scanner_asset_cache.mjs` fails when a cached file's bytes change while
    its version stays put, and `--update` refuses to record it. Hashing folds CRLF→LF, so a
    Windows checkout and CI agree.
  - The scanner's JS (`scanner.js`, both workers) is NOT in it — those stay network-first
    with the app shell, so code always updates.
  - **⚠ But bump a worker's `?v=` whenever its bytes change** (`SCAN_WORKER_URL`,
    `OCR_WORKER_URL`, the `scanner.js` tag, all in Index.html): network-first in the SW does
    not stop an HTTP cache in between from answering for the exact URL. The OCR worker
    changed on 2026-09-26 while `OCR_WORKER_URL` still said `?v=299`; caught at the bump.
- **OpenCV is vendored** (`vendor/opencv/opencv.js`, byte-identical to the jsDelivr build
  prod loaded; jsDelivr is the worker's fallback only). Apache-2.0 notice in
  `vendor/LICENSES.md`.

### Version chips in the review row (2026-09-12)

A scan answers "which CARD is this", never "which PRINTING of it", so the review row
carries one control per question. The **Non-Foil / Foil** segment is the FINISH (one
card_id, two SKUs); the segment beside it is the **VERSION** — different card_ids that
share a Product Name: the base card, its Enchanted/Epic/Iconic, and its promos. Tapping
one is exactly the pick the editor's search already made, sourced from a card that is
already on screen.

From the beta's most-reported friction (Aaron P, 2026-09-11): the Epic *Heihei - Created
by the Vine* read as the Rare, and the fix was to go and search by name for a card that
was on the screen — *"basically right card but extra steps for the variant"*. Same
report: a set's league promos "aren't an option whenever you click the pencil".

- **623 of the shipped index's 2,479 names carry more than one version** — 541 pairs, 66
  threes, 16 with four or more, topping out at *Mickey Mouse - True Friend* (7). **593 of
  those families have genuinely different art**, so the matcher CAN separate them; it just
  lands on a sibling often enough to matter. The other 30 are byte-identical art
  (`art_key` collisions) where no matcher work will ever help and a button is the only
  possible answer.
- **⚠ The chip row is the RARITY axis and nothing else.** Two booster printings of one
  card both label "Common" — true, and an answer to nothing — so `scanVariantChipsOk`
  refuses a family whose labels collide and leaves it to the editor. That is **205 of
  623**: reprints and multi-promo runs, where a one-word chip would be a coin flip dressed
  as a choice. `SCAN_VARIANT_MAX` (4) caps the rest; 616 of 623 families are 4 or fewer.
- **The editor carries everything the chips refuse.** "This card's versions" lists every
  printing with its ART and its set, above the search box, uncapped — a picture cannot
  lie the way a word can. It is also the direct answer to the league-promo half of the
  report.
- **⚠ The family key is CASE-FOLDED** (`scanVariantFamilyKey`), because Lorcast's own
  spelling is not stable across sets: "HeiHei" vs "Heihei", "Down In New Orleans" vs "Down
  in New Orleans". Nine families and **19 printings** hang on that one `toLowerCase()`,
  four of them base/promo pairs — exactly the promos this exists to offer.
- **⚠ Tapping the version already selected is a NO-OP**, matching the foil segment. It
  would otherwise stamp `reviewed: true` on a row nobody judged, and unreviewed shown-✓
  rows are the only honest precision sample there is (round 11).
- **⚠ `.scanner-qa-rowinfo` clips, it does not scroll.** A chip pushed past the right edge
  is simply gone with nothing on screen to say it existed — which is what a 4-version card
  plus a foil pair did at 360px. The segment wraps inside its own border, and "Super Rare"
  renders as **SR** on the chip only (the site's own smart search already takes `sr` as a
  rarity token); the full name stays in the tooltip and in the editor.
- Ordering is rarity first, then release rank — so a reprint falls in behind the printing
  it reprints rather than wherever the alphabet puts its set.
- A pick writes the same truth label as a search pick, so a switched row still reads as a
  scanner miss in the flywheel, which it is.

Guarded by `node scripts/test_scan_variants.mjs`, which replays the real helpers over the
shipped `scanner/index.json` and so re-measures every count above.

### The review editor's search IS the site's smart search (2026-09-12)

The pencil's search box matched the whole typed phrase against `Product Name` and nothing
else, so **`heihei epic` answered "No card matches"** (Zaven, from the beta). That box is
reached precisely BECAUSE the scanner picked the wrong card, and a sibling printing is the
commonest miss — so the one query most worth typing was the one that returned nothing, and
it failed silently: an empty list reads exactly like a card that isn't in the catalog.

- **It routes through `parseSearchQuery` + `matchesCardFilter` now**, per the
  single-canonical-matcher rule — it was the file's ONLY remaining `nameMatches` bypass.
  So the name splits off the dimension (`heihei epic` → name `heihei` + rarity `Epic`) and
  ink, set, cost and the rest come free: the tester is holding the card and can read any of
  them off it.
- **The AND-first/OR-fallback two-pass is inlined rather than calling `smartCardFilter`**,
  because it needs a scan cap. `matchesCardFilter` builds a body-text haystack per row, so
  a one-letter query would run that over the whole catalog on every keystroke — on the one
  screen where the camera and both scanner workers are already running. **`QA_EDIT_SCAN_CAP`
  (60) candidates for 12 rendered rows** is the ratio the name-only scan already used.
  Measured over the shipped index: ~21ms a query on a desktop, against ~13ms before.
- **The query is `React.useDeferredValue`d**, so a keystroke paints immediately and the list
  lands a frame later — the same treatment the Cards browser gives its filter. The empty
  state quotes the DEFERRED query, or the message and the list could disagree mid-keystroke.
- **Ranking is on the residual NAME, not the raw input.** With `heihei epic` the rarity word
  is a filter; sorting by the whole phrase means no card can ever prefix-match it and the
  order collapses to name length.
- **⚠ A bare `154` / `154/204` is still a COLLECTOR-NUMBER lookup and must stay ahead of the
  parser**, which would read a lone number as name text. The tester is holding the card and
  that line is the fastest thing to read off it.
- **It returns EVERY printing with that number, oldest set first** (2026-09-25), capped at 40
  rather than the name search's 12. Fourteen printings share #154, and stopping at 12 in
  catalog order left two of them unreachable by number. `/204` narrows only on a row whose
  `Number` carries its own total; most catalog rows carry a bare number, and dropping those
  would empty the list, so they stay in. Each row shows its `#N`, and Enter picks the top one.

Guarded by `node scripts/test_scanner_edit_search.mjs`, which rewrites only the memo's hook
wrapper and replays the real body over the shipped index.

### ⚠ `parseSearchQuery`'s exclusion prefixes match a WHOLE token — fixed 2026-09-12

Found by routing the scanner through the parser: `EXCL_PREFIXES` (`non ` / `no ` / `not ` /
`without ` / `exclude `) were located with a bare `indexOf`, so they fired **inside a word**.
`bru`**`no `**`madrigal` parsed as name `bru` with the **Madrigal classification EXCLUDED** —
a search for Bruno that could not return a Bruno — and `last can`**`non `** ate whatever
followed it. `rhino` and `bad-anon` the same. Measured over the shipped card list: **43
corrupted queries of 9,952, now 0.**

This was site-wide, not a scanner bug — every Bruno card and both Cannon items were
unsearchable by name on the **Cards tab** too. It only surfaced here because the old scanner
box didn't use the parser at all, and because the failure looks like a normal empty result.
The sibling `-rush` minus-exclusion was always anchored (`(^|\s)`); only this loop wasn't.
Both directions are pinned in the test — over-tightening kills the real exclusion syntax
just as silently.

### Consent + the upload opt-out (migration 114)

- **`scanner_consents(user_id pk, version, accepted_at, uploads_enabled, updated_at)`** — owner-only RLS on select/insert/update, no admin read branch. One row per user, updated in place: we need the CURRENT preference on every scan, not an audit trail.
- **`SCAN_BETA_VERSION`** (next to `SCANNER_BUILD`) is the accepted-notice version. **Bump ONLY when the substance changes** — what's uploaded, why, retention, who sees it. It re-prompts everyone; re-prompting for typo fixes trains users to click through the one screen that has to be read.
- **The gate blocks the camera, not just the view.** The `// mount: index + camera + worker` effect early-returns on `!consentOk`, so `getUserMedia` cannot fire before acceptance. Verified: no `<video>` in the DOM pre-accept. Don't "simplify" this into a render-only overlay. Its deps are `[consentOk, camAttempt]` since 2026-09-25: `camAttempt` is bumped by the error screen's **Try again**, which re-runs the whole mount. The early return still comes first, so a retry can never reach the camera before consent either.
- **The opt-out reads `uploadsOnRef`, never the state.** `uploadSample`, `labelSample`, and the end-of-session telemetry insert all run from queue tails and deferred looks holding pre-toggle closures. All three bail when off — including the photoless session row, deliberately: "I turned that off" has to mean all of it.
- Reachable twice: the first-run notice, and a checkbox in the review screen (`.scanner-qa-privacy`).

### The overlay is a DIALOG, and Back closes it (2026-09-25)

A full-screen takeover with the camera on has to leave the way people expect. Before this,
Esc did nothing, Tab walked the page hidden behind it, and on a phone Back went to the page
UNDER the scanner while the scanner stayed open with the camera still running.

- **Every render branch's root is `role="dialog" aria-modal="true"` on one `scanRootRef`**,
  and `useModalFocus` keeps focus inside. Once consent is given, focus lands on the close
  button.
- **Esc steps out ONE layer: the card editor, then the review screen, then the scanner.** A
  search box with text in it gets the first Esc to itself (it clears the text); the next one
  leaves. It reads a ref, so the listener is added once and never sees stale state.
- **Opening pushes a history entry** (`openScan` in App); Back pops it and closes, which also
  stops the camera. **`closeScan(navigatingAway)`** is the one close path. With × it calls
  `history.back()` to take its own entry off. When the caller is about to push a page of its
  own (open a deck, a card, the admin review), it only strips the marker with `replaceState`,
  because a `back()` would race that push.
- **The camera error screen has Try again** (see the consent gate above). "Camera in use"
  (`NotReadableError`) now says so: close the video call or camera app, then retry.
- **A detector worker that fails says so** rather than reading "Loading detector…" forever:
  live detection is off, the shutter still identifies.

### Retention — a promise with a cron behind it

`scripts/cleanup_scan_samples.py`, wired into etl.yml's **selfheal** job with `if: always()`. The beta notice and privacy.html both promise deletion after 12 months; this script is the only thing making that true, so it exits non-zero rather than shrugging.

- **Storage first, rows second.** The row is the only index of where the photos live — drop it first and a failed storage call strands JPEGs nothing points at.
- **Three objects per sample**, not one: the rectified card (`image_path`), `_raw` (the full camera frame) and `_strip` (the approach filmstrip). The last two are in `debug.rawPath` / `debug.stripPath`. Miss them and you delete the crop while keeping the wider shot — backwards, privacy-wise.
- `--user <uuid>` is the erasure path (account deletion, or "delete my photos but keep the feature"). Also sweeps the account's storage folder for orphans — an upload whose row insert failed, the class migration 105 fixed.

### Storage cost + the abuse cap (migration 115)

**Every scan is ~400 KB** — three storage objects at ~149 KB each. Four allowlisted testers put **500 MB** in the bucket before launch. Budget for public traffic accordingly; this is the scanner's main running cost, and the 12-month retention job is what stops it compounding.

- **1000 rows / user / rolling 24h**, enforced by TWO triggers on `scan_samples`. The BEFORE ROW one is the cheap common path; the AFTER STATEMENT one is the backstop, because rows from the same command aren't visible to a BEFORE trigger and PostgREST accepts bulk array bodies — without it, one `insert … select generate_series` walks straight through.
- Chosen against real data: the largest genuine session on record is **343** scans, so the cap is ~3x that. Don't tighten it below ~500 without checking `scan_samples` daily maxima first — throttling a tester running physical binders is the exact behaviour we want.
- Hitting it is invisible to the user: `uploadSample` swallows insert errors, identification is local, and the collection-save path never touches `scan_samples`. Under abuse the flywheel is the right thing to shed.
- **If storage becomes the problem**, the lever is the `_raw` frame + `_strip` filmstrip — they're 2/3 of the objects and only the rectified crop is needed for matcher replay. But raw frames are what detection tuning runs on (the #1 remaining accuracy lever), so sample them, don't drop them.

### Where the user-facing copy lives

Three places, keep them consistent: the in-scanner notice (`consentPanel` — and `guestPanel`, the signed-out version it returns when there is no account), **privacy.html `#scanner`**, and the Help page's "Card scanner (beta)" section. `test_scanner_guest.mjs` checks all three still say nothing is uploaded while signed out. `Permissions-Policy: camera=(self)` in `_headers` already allows the camera — don't tighten it.
