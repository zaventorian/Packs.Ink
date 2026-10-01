# /picks — the unlisted affiliate page (2026-09-10)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

`picks.html`, a **standalone page like `/swiss` and `/ticker`**, not an SPA view: it is a
personal link page rather than part of the product, so it has no business inside
Index.html, the nav, or the sitemap. Wired in `dev_server.py`, `build_dist.mjs` and
`robots.txt`; **no worker route** — Workers Assets' pretty-URL handling serves it, the
same fall-through `/ticker` relies on.

- **⚠ "Unlisted" is THREE mechanisms and losing any one quietly puts it in Google**: a
  `noindex,nofollow` meta, a `robots.txt` Disallow on both `/picks` and `/picks.html`,
  and nothing linking to it. Two of the three are checkable and the test checks them.
- **Undiscoverable is NOT access-controlled.** Anyone with the address can open it, so
  nothing sensitive goes on it — and the page says so in its own footer, because a
  reader who thinks it is private will treat the link as safer than it is. Same posture
  as swiss.html.
- **⚠ Every link is a tagged SEARCH, and for this page that is the whole design.** A
  hand-picked list of "popular games" rots within weeks — the Switch 2's price moved
  from $449 to $500 on 2026-09-01, ten days before this shipped — while a category
  search always shows what is current, in stock and at today's price. It also sidesteps
  the ASIN-verification problem entirely. The page says this out loud rather than
  letting it read as missing product pages.
- **⚠ `AMAZON_TAG` is DUPLICATED from Index.html** because a standalone page cannot
  reach the app's module. A drifted or dropped tag produces links that work perfectly,
  land on the right products and earn nothing, with no error anywhere — so
  `scripts/test_picks_page.mjs` reads the tag out of **both** files and fails if they
  disagree. Same guard shape as the Discord digest vs `priceStanding`.
- **`i=` (search department) is per section** — `videogames` / `electronics` /
  `toys-and-games`. A typo'd slug is the quiet failure: Amazon serves the page anyway,
  filtered to a category the product isn't in, so the link looks fine and returns
  nothing useful. The test pins the set of valid slugs.
- **The disclosure matters MORE here, not less.** This page exists to be handed to
  people, so the required verbatim string ("As an Amazon Associate I earn from
  qualifying purchases") sits above the links in its own bordered block, and the test
  asserts it byte-for-byte. Every anchor is `rel="noopener nofollow sponsored"`.
- **⚠ Send the PAGE, never the product links.** Amazon's Operating Agreement bans
  Special Links in printed material, ebooks and oral solicitation outright; since March
  2024 email/DM/social sharing is allowed only into **solicited** communications the
  recipient opted into and can opt out of. A page URL is unambiguously a website link
  and carries the disclosure with it, which is exactly why this page is the compliant
  shape for "something I can send to people". The **Copy this page's link** button
  forces the canonical `https://packs.ink/picks` for that reason — opened from disk,
  `location.href` is a `file:///` path useless to anybody else.
  **⚠ Sources are secondary**: affiliate-program.amazon.com is egress-blocked here, so
  this was assembled from search results quoting the licence. Confirm in Associates
  Central before leaning on the March-2024 relaxation.
- Content is ordered by who is most likely to have been handed the link, so cards lead.
- **Cards, with photos where we have them (2026-09-10).** An item may carry `tcg` (a
  TCGplayer product id) or `rav` (a Ravensburger SKU), and `photoUrl()` builds the image;
  everything else — consoles, games, streaming gear — gets a drawn glyph from `ICONS`, tinted
  by the section's `hue`. Never an Amazon image: the test checks every photo host.

Guarded by `node scripts/test_picks_page.mjs`.

### The grading queue is the one high-intent placement (2026-09-10)

Everything else Amazon-shaped on the site sits where somebody might browse. The
**grading queue** (`GradingQueueSection`) is different: a card with `status` other than
`at_grader` is one the user has explicitly said they are about to pack and send. That is
the highest-intent moment on the site for submission supplies, and PSA publishes an exact
spec for them — so the note is **reporting a packing list, not recommending a brand**,
which is what lets it exist under the state-the-spec-never-rank rule.

- **⚠ It is gated on `toSubmit > 0`, and that gate is the whole difference between a fact
  and an advert.** Once every card is AT the grader the packing question is answered, and
  a shopping line there is just a promo box on somebody's collection page. Nothing errors
  if the gate inverts or is dropped — it simply starts reading as an ad — so
  `test_amazon_links.mjs` pins both the gate and that it is derived from the row's
  `status`, never from the queue's length.
- **The toploader warning is the reason it earns its place.** Reaching for a toploader is
  the common mistake and graders cannot safely open one, which delays a submission; the
  semi-rigid dimensions (3 5/16″ × 4 7/8″) are PSA's own.
- Quiet by design — a hairline rule, not a filled card — and it carries its own Associate
  disclosure, because the FTC wants that near the link rather than only in a footer.
- The block is JSX inside a component rather than a pure function, so the guard is
  source-text over the extracted component (bounded: ~4.4k chars, verified not to leak
  into the next component, or the assertions would pass for the wrong reason).
