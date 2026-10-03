# Shareable sub-tab URLs — `?s=` / `?f=` / `?m=` / `?c=`

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Decks' sections and the Screener's mode were localStorage-only, so every one of them lived at `/decks` or `/screener` and **none could be linked to** — "here's the Coconut feed" was not a sendable thing. Now:

- **`/decks?s=<section>`** — `yours|favorites|following|discover|tournaments` (`DECK_SECTION_KEYS`).
- **`/decks?f=<format>`** — `core|infinity|coconut`; implies Discover, so `/decks?f=coconut` alone is the short share link.
- **`/screener?m=<mode>`** — `raw|graded|sealed` (`SCREENER_MODES`).
- **`/collection?c=<section>`** — `cards|sealed|graded|pins|playmats` (`COLLECTION_SECTIONS`, added 2026-08-24; `pins` = Pins & Counters, 2026-09-11; `playmats`, 2026-09-27). Same rules as the rest; `cards` is the default so it's omitted. In viewer mode the tab hrefs keep `?collection=`+`?token=` (`collectionSectionHref`) — drop the token and you hand someone a link that dead-ends on "this collection is private", which the owner can never reproduce.

Rules that keep this from fighting the rest of the URL machinery:

- **Register every new param in BOTH `dirtyParams` and `VIEW_OWNED`** (App's view-sync effect). Owned params survive a same-view strip; unregistered ones are wiped on the next view sync, which is exactly what would make a deep link appear to work and then silently reset.
- **Defaults are omitted.** The default section depends on sign-in state, so writing it would give two people two different URLs for the same tab.
- **`replaceState`, never push.** Decks stacks real pages on top of a section (deck / tournament / creator profile), each pushing its own entry; a filter that also pushed would interleave and make Back step sideways through tab changes instead of out of the page you opened. The Screener's mode is a filter for the same reason. (Analytics' `?a=` does push — it has no leaf pages under it.)
- **A leaf page owns the URL while it's open.** The decks mirror early-returns when a deck / tournament / creator is open, or it would strip their deep-link params; DecksView's popstate handler restores section + format from the URL when you back out of one.
- **A `?f=` link counts as "user touched the format".** Otherwise Discover's auto-fallback (land on a format that has decks) can quietly move a shared Coconut link onto Core.
- Both tab rows are `<a href>` + `navHandler` now that the URLs exist, so modifier-click and "Copy link address" work — same convention as the Analytics sub-tabs. Their CSS needed `text-decoration:none` and nothing else. Collection's section tabs went the same way (they also needed `display:inline-flex` + `line-height`, which `<button>` had given for free).

### "Copy link to this page"

Every view and sub-tab mirrors itself into the URL, so the address bar is always right — **except in the installed app, where there is no address bar**, which made the one place people live the only place they couldn't share from.

- `currentShareUrl()` reads `window.location` rather than reconstructing anything, so it inherits every deep link the app already writes (`?deck=` `?set=` `?tourney=` `?card=` `?a=` `?s=` `?f=` `?m=` `?c=`) with no second source of truth. Origin is forced to `SITE_ORIGIN` so a native build copies packs.ink, not `capacitor://`.
- `shareUrlLabel()` names what it caught — "Link to **Decks · Tournaments** copied". A bare "Link copied" leaves you unsure whether it got the deck you had open or the tab behind it. Leaf params (deck / tournament / collection / user / card / trade / set) win over the section behind them.
- Two entry points: a 🔗 bubble in the top nav **only when `isStandalone || IS_NATIVE_APP`**, and a row in the settings popover always. The bubble sits in right-cluster row 1 — the slot the install bubble vacates once installed, so the two are mutually exclusive by construction and row 2 never grows to the 3 bubbles that used to push ANALYTICS off the edge at ≤420px.
- Guarded by `node scripts/test_share_links.mjs` (extracts both helpers out of Index.html). Both failure modes are silent — a dropped share token, or a label that starts claiming the wrong page as params are added.

**Do links open the installed app?** Android: yes. Chrome installs a PWA as a WebAPK that registers intent filters for the manifest `scope`, which is `/` here, so any packs.ink link opens the app. Nothing to configure. iOS: no — a home-screen PWA gets no URL handling, links always open in Safari. The native Capacitor shell: no — its only intent filter is the custom `ink.packs.app://auth-callback` OAuth scheme, and there's no `/.well-known/assetlinks.json` or `apple-app-site-association`. Adding those needs the app published and its signing-cert SHA-256, so it belongs with the phase-2 native work.
