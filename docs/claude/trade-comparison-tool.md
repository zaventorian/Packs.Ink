# Trade Comparison tool (Analytics » Trade Compare)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

`TradeView` (Index.html). Two-sided card-value comparison for working out a trade between two people. Search routes through the canonical `matchesCardFilter` (so the same smart-search works). Each side is a `[{key, qN, qF}]` array; the tool sums Low + NM Market and shows the difference.

- **Group key**: `tradeGroupKey(g)` = `card_id` (+ `::Normal`/`::Foil` suffix for SPLIT_BY_PRINTING_SETS cards). Cards re-resolve from a `groupByKey` Map so a stale cache can't carry dead references.
- **Default quantities on add**: a card with BOTH printings starts at **0/0** (the adder can't know which the other party means — they pick). Single-printing cards (chase: Epic/Enchanted/Iconic/Promo, or normal-only) default that one printing to **1**.
- **Per-card controls**: ± per printing, a **move-to-other-side** (⇄) button (merges quantities if the card already sits on the destination), remove (×). Header has per-side **Clear** + a **Clear all**. Clicking the card art/name opens the standard `CardDetailModal` (TradeView receives `theme/user/collection/updateQty/onSignIn` from MarketView for this).
- **Layouts** (`packsink:trade:layout` = `cards`|`compact`): compact drops the image + set/ink line and lays the two printings **side-by-side** (one condensed row) on all widths. The mobile (≤760px) breakpoint also forces side-by-side printings for every card.
- **Sort** (`packsink:trade:sort` = `added`|`price-desc`|`price-asc`|`name`|`release`): display-only, never mutates the side's stored order (so "Added" is restorable). Unpriced cards sink to the bottom for price sorts.
- **Tooltips + links**: Low/NM tags use the shared `Tip` (`TIP_LOW`/`TIP_MARKET`); each printing has a `↗` per-SKU TCGplayer affiliate link via `tcgUrl(pid, printing)`.

### Shareable trade links (DB-backed)

The trade is **persisted in the `trades` table keyed by a token**, not stuffed into the URL — the old inline `?trade=<base64>` blob blew past Discord's 2000-char message cap (~16 cards/side). Now the link is a fixed ~45 chars regardless of trade size.

- **Migration 54** (`supabase/54_trade_share_links.sql`): `trades(token pk, payload jsonb, user_id, created_at)`. RLS **on with no policies** — all access via two SECURITY DEFINER RPCs granted to anon+authenticated: `create_trade(p_token, p_payload)` (validates token shape `^[A-Za-z0-9_-]{16,64}$`, caps payload <100KB) and `get_trade(p_token)`.
- **Share** (`shareTrade`): generates a 22-char token client-side (so the clipboard write is **synchronous** inside the click — reliable in Safari), copies `packs.ink/?t=<token>`, and persists via `saveTradeRecord` in the background. Payload = `{a:[[key,qN,qF],...], b, n:[nameA,nameB]}` (`tradePayloadObj`).
- **URL form is `?t=<token>`, NOT `/t/<token>`.** A two-segment path breaks every **relative** asset URL (`styles.css`, `logo.js`, ink-icon preloads) — the browser resolves them against `/t/` → SPA fallback serves HTML → `LOGO_B64 is not defined` crash. The single-segment `?t=` keeps the path at `/` so relative assets resolve. (To ever use the pretty `/t/` path, every asset URL must first be made root-absolute.)
- **Open**: `App.initialUrlParams.tradeToken` (via `getTradeShareToken()`, captured in `useMemo` before the URL-cleanup effect runs) forces `view="market"`; `marketSub` inits to `"trade"`; `TradeView` fetches via `get_trade`, hydrates, and the App view-sync effect cleans the path to `/analytics`. Token is passed down as a **prop** (`shareToken`) — NOT re-read from the URL in the hydration effect, because the catalog loads async and the URL is cleaned before then. Legacy `?trade=` blobs still decode (`decodeTrade`).
- **Analytics sub-tab routing**: `marketSub` lives in App, mirrored to `?a=<sub>` (added to `dirtyParams` so it's stripped when leaving Analytics). First sync uses `replaceState`, user tab clicks use `pushState` (Back/Forward step through tabs); a popstate handler syncs `marketSub` from `?a=`. This is why refresh keeps the tab. The `if(cur===want) return` guard in the sync effect prevents the popstate→setState→push loop.
- **localStorage**: `packsink:trade:v1` (`{a,b,nameA,nameB}`) auto-saves the in-progress trade locally; a `?t=` share link takes precedence over it on load.
- **Rate limits: per bucket, then a per-POOL backstop with a fair share (migration 190, 2026-10-06).**
  `create_trade` and `_feedback_rate_limit()` (submit_feedback + reply_my_feedback) bucket a signed-in
  caller by ACCOUNT and an anonymous one by address (`_rate_bucket`: `_client_ip()`, i.e. Cloudflare's
  `cf-connecting-ip`, which a caller cannot forge; IPv6 folded to its /64). Per bucket: 30 trades / 10
  feedback an hour. The global backstop counts signed-in and anonymous writes as two separate pools, and past
  half its cap only buckets with fewer than 2 writes this hour get in, up to the hard cap (300 / 120, the old
  global). Before 190 one pool held everybody, so 10 addresses (12 for feedback) locked the whole site out,
  signed-in users included, for the rest of every hour; now filling a pool takes ~80 / 36 addresses, and an
  anonymous attacker never reaches the signed-in pool. A refused attempt is never counted. The messages are
  unchanged (the em dash is `chr(8212)` so the migration stays ASCII). Guarded by
  `node scripts/test_anon_write_limits.mjs`.

### Promo sets are named by the PRINTED suffix (2026-09-18, Zaven)

A promo belongs to the set its card face says: `12/P4` is Promo Set 4 #12, `5/PD1` is PD1 #5,
`4/DIS` is Magical Places Promos #4. **Read the number off the card image**, never off TCGplayer:
its "Disney Lorcana Promo Cards" group files every promo under a bare number with no suffix,
so #7 there is five different cards.

- **Every promo printing gets its own priced tile** (Zaven, 2026-09-30) — the `promo-printing-policy`
  review is settled. A promo TCGplayer lists and we lack is a `REPRINT_PROMOS` row, not an ack.
- **Challenge Year 3 (C2) runs #11-#18, and 11-14 are the FOILS of 15-18.** Lorcast indexes only the
  non-foils (#15-#18, with null pids — linked through `TCG_PID_OVERRIDES` 2026-09-30); #11 Stand Out,
  #12 Down in New Orleans and #14 Tinker Bell - Insistent Fairy are `REPRINT_PROMOS` clones
  (`crd_c2_1N_*_foil`), declared foil in `YEAR3_PRINTING_BY_NUMBER`. **#13 is not known**: the
  "Mother Knows Best (Foil) #13" TCGplayer lists beside them is printed `13/C3`.
- **C3 (the 2026-27 Challenge season) is OUR OWN set row**, `set_challenge_c3` (migration 178), named
  "Lorcana Challenge Promo (C3)" directly, with code NULL so `load_lorcast` still takes the real set the
  day Lorcast indexes it — at which point its cards arrive under Lorcast's id and the two have to be
  converged (the CC1 situation). It holds Mother Knows Best `1/C3` (711519, non-foil) and `13/C3`
  (711520, foil), `REPRINT_PROMOS` clones of Fabled #99. `CHALLENGE_PRINTING_BY_NUMBER` is the ghost-row
  table for both C2 and C3; C3 is wired wherever C2 is, except `SET_DISPLAY_NAMES` (no rename needed).
- **Promo Set 4 (P4)** — Lorcast indexed it 2026-09-18 with null pids; `TCG_PID_OVERRIDES` (both
  copies) links #9-16. #1-6 aren't indexed yet.
- **PD1** — product/prerelease promos: #1-8 printed `/PD1` (checked 2026-09-18), #15 Pegasus
  (Lorebook), #16 With a Few Good Friends (Q3), #17 The Beanstalk, **#18 Sulley - Protective
  Monster / #19 Violet Parr - Super Resilient** (Best Buddies Bundle, 2026-09-19; TCGplayer
  719967 / 719968 since 2026-09-24).
- **A promo TCGplayer has not listed yet is a `REPRINT_PROMOS` entry with a NULL pid** (2026-09-20).
  That tuple grew an optional 6th field: `(base_pid, set_id, cn, new_id, promo_pid[, art])`. A null
  `promo_pid` leaves the row unpriced — already the handled case, `NUMBERED_PROMO_SETS` emits one
  placeholder printing — and `art` carries a repo-local scan, because the image would otherwise
  fall back to the BOOSTER printing's picture, which is the wrong art on a promo tile. Filling the
  pid in later and deleting the art path updates the row **in place**: same `card_id`, so nobody's
  collection mark moves. That is the reason to use this script rather than a one-off migration —
  and it re-applies after every Lorcast load instead of being a single insert that can drift.
  PD1 #18/#19 were the first to graduate (listed 2026-09-24, filled in 2026-09-27).
  - **⚠ A filled-in pid reaches the `cards` rows only when the script runs FROM `main`.** The
    21:00 UTC metadata job (etl.yml) re-runs it daily from `main`'s checkout, so a run from a
    branch is reverted within the day — let the merge carry it, or run it by hand right after.
  - **⚠ Delete a retired `art` file only AFTER the rows point at TCGplayer** — read
    `cards.image_normal` for the ids first. Deleted in the same deploy, the image 404s from the
    deploy until the next run. That is why `sulley-protective-monster-pd1-18.jpg` and
    `violet-parr-super-resilient-pd1-19.jpg` stayed in `Logos/cards/` after the switch; they
    were deleted 2026-09-28, once a metadata run from main had pointed both rows at TCGplayer
    (719967 / 719968, `image_normal` on tcgplayer-cdn, prices live). The scanner index's
    `art_key` still names them, and that is fine: it is an identity key, not a URL.
- **⚠ Check Lorcast before hand-writing any promo's stats.** #18/#19 turned out to be promo
  printings of Attack of the Vine! #128 and #176, so cloning those rows gave exact cost / ink /
  stats / lore / classifications / ability text instead of a blurry photo's best guess. A promo
  packed in a product is USUALLY a reprint of a booster card; read the photo only to confirm it.
- **"Attack of the Vine! Promos" is gone.** It was a hand-made stand-in that flattened P4, PD1 and
  DIS into invented numbers (Tigger sat at #10, Meilin Lee's real number). `supabase/160` moved its
  last three cards onto P4 #12/#15/#16. `SET_PARENT` is now empty but the mechanism stays.
- **`SUPPRESSED_CARD_IDS`** drops Lorcast rows we refuse to carry — deleting them from `cards`
  doesn't stick, the daily Lorcast load re-inserts them. Today: Lorcast's P4 #7/#8 Daisy Duck -
  Paranormal Investigator (printed `JA`); that card's promos are P3 #23/#24. And Lorcast's
  Into the Inklands #223 Piglet (2026-10-03), a duplicate of `crd_custom_544487_piglet_pooh`.
  - **⚠ The graded matcher reads the list too** (`terapeak_match.fetch_catalog`). A suppressed
    row that duplicates a card we carry goes in `SUPPRESSED_ALIASES` there, so its index entry
    survives under OUR id: sellers title the Piglet "Into the Inklands #223", Lorcast's filing,
    and dropped outright those titles match nothing. Before this the daily rematch had moved 4
    Piglet sales onto the hidden row. Guarded by `python scripts/test_suppressed_aliases.py`.
- **P3 runs to #63.** #58 Sulley / #60 Woody are REPRINT_PROMOS clones; #61/#62 are Japan's Fabled
  SC pair (Maleficent - Monstrous Dragon), unpriced synthetic rows from `supabase/160` labelled via
  `REGIONAL_EXCLUSIVE_LABEL`; #63 JP Buzz IS on TCGplayer (714954), so it keeps its price and gets
  its label from `PRICED_REGIONAL_LABEL_BY_ID`.
- **P4 #17 is Japan's Hyperia City box promo** (2026-09-30): Minnie Mouse - Urban Visionary, printed
  `17/P4 · JA · 14`, packed in Takara Tomy's booster box. The English buy-a-box printing is a
  different number, `4/RPH` (set "Ravensburger Play Hub Promos"). The row is the prestage
  `crd_prestage_p4_17` with the JP card as its own art, labelled through `REGIONAL_EXCLUSIVE_LABEL`.
- **The ink drop counter cards in that box are Extras & Oddities entries under Hyperia City**
  (`CUSTOM_CARDS`, ids `extras:ink-drop-ja-baymax` / `-merlin`, bucket "Japanese Box Bonus"). One
  of the two comes per Japanese box; they are printed `JA · 14` with no collector number and say
  on their face that they are not cards, which is why they are not in the set. Art is the FRONT
  only, from Takara Tomy's box-bonus graphic (`card-art/extras/`); the Baymax and Merlin backs are
  still wanted. **⚠ Nothing official says they are foil** (checked 2026-09-30): English packs carry
  the same two designs in the marketing slot and Ravensburger said there are no foil ink drops yet;
  Takara Tomy's renders show a sparkle texture the English ones lack, and Zaven heard they are
  Japan-only foils. Keep "foil" off the tile until a source says it.
- **A single-printing promo gets exactly ONE row** — one add box — whatever emitted it.
  `collapsePromoPrintings` runs last in `transformSupabaseData` over every `UNIFIED_TILE_SETS` set and
  keeps the priced row, then foil over Normal. Reported 2026-09-18: unpriced PD1 cards rendered a
  Non-Foil AND a Foil box. C1/C2 are deliberately outside it. Guarded by
  `node scripts/test_promo_single_printing.mjs`.
- **Every promo set shows one "Promos" counter** on its Collection tile (`UNIFIED_TILE_SETS`), and
  the grid rules them off from the booster sets with `.collection-sets-divider`.
