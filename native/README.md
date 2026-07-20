# Packs.Ink native app (Capacitor)

Groundwork laid 2026-07-17. Android first; iOS is a later `npx cap add ios` away
(same bundle, same shims — see "iOS pathway" below).

## The decision (and why)

**Capacitor shell around the existing zero-build web app, with assets BUNDLED
on-device** (not a remote-URL wrapper, not a TWA, not a rewrite).

- **Not a TWA** (Trusted Web Activity): a TWA is literally Chrome rendering
  packs.ink — fastest possible Play listing, but it stays "just the website,"
  has no native API surface to grow into (native camera scanner, push
  notifications, widgets), and dead-ends for iOS (no TWA equivalent exists;
  Apple rejects thin wrappers under guideline 4.2). Rejected per Zaven's
  "don't want just a wrapper" call — the earlier "Play Store = TWA later"
  note is superseded.
- **Not a rewrite**: Index.html is ~1.9 MB of working product. React Native /
  Flutter would be a multi-month re-implementation for zero user-visible gain.
- **Bundled assets, not `server.url: packs.ink`**: bundling makes the app work
  offline natively (no service worker needed), removes Apple's
  "repackaged website" review risk for the iOS build later, and pins app
  behavior to a tested snapshot instead of whatever deploy is live. The cost —
  app releases must ship through the store — is acceptable at our release
  cadence, and live-update tooling (Capgo) exists if that ever hurts.

Data flow is unchanged: the bundled app talks to Supabase exactly like the
website (PostgREST sends `Access-Control-Allow-Origin: *`, so the app's
`https://localhost` origin is fine).

## How it fits together

```
Index.html + styles.css + vendor/ + Logos/   (the real app, unchanged)
        │  native/sync.mjs  (include-list copy; renames Index.html → index.html)
        ▼
native/www/            (generated bundle — gitignored, rebuild any time)
        │  npx cap sync android
        ▼
android/               (committed Capacitor project; opens in Android Studio)
```

### Native shims inside Index.html (all inert on the web)

`IS_NATIVE_APP` (true when Capacitor's injected bridge reports a native
platform) drives five adaptations:

1. **Service worker never registers** — assets are on-device; a SW would only
   add a stale-copy failure mode. `sw.js` is also excluded from the bundle.
2. **`PROXY_ORIGIN`** — `lorcastToProxy` / `proxyImg` emit
   `https://packs.ink/img-proxy/...` absolute URLs instead of relative paths
   (which would 404 against the app's internal origin). This keeps the
   "Lorcast sees one origin" invariant, rides Netlify's 30-day immutable edge
   cache (the WebView HTTP cache honors it), and keeps canvas exports
   untainted (`_headers` pins `Access-Control-Allow-Origin: *` on BOTH proxy
   routes — the `/tcg-img-proxy/*` block ships with the next deploy).
3. **`SITE_ORIGIN`** — every user-facing copied link (trade `?t=`, deck
   `?deck=`, collection `?collection=`, SC box) says `https://packs.ink`, never
   the app-internal origin.
4. **Sign-in is stubbed with a toast** — Google refuses OAuth inside WebViews
   (`disallowed_useragent`). Real fix is Phase 2 (below).
5. **Sentry keeps native errors** — the localhost dev-noise filter exempts
   native builds and tags events `native_app: android|ios`.

`native/sync.mjs` refuses to build if these markers vanish from Index.html.

## Day-to-day commands

```
npm run app:sync     # rebuild native/www from repo files + cap sync android
npm run app:open     # open the Android project in Android Studio
npm run app:assets   # regenerate launcher icons/splashes from native/assets/logo.png
```

After ANY edit to Index.html / styles.css / logo.js / vendor / Logos, run
`npm run app:sync` before building the app again.

## Update SOP — "we changed packs.ink, now what?"

Mental model: **the app is a snapshot of the web files + the same Supabase
backend.** Data flows to the app live; code ships per-surface. Decision:

**1. Backend / data / content only** — ETL, SQL migrations, Supabase, new cards
or prices, tournament uploads. → Deploy the web as usual. **The app updates
itself automatically** (same backend, same image proxies). Nothing to do for the
app.

**2. Web UI / logic** — any edit to `Index.html` / `styles.css` / `logo.js`.
→ (a) Ship to web the normal way (commit, then push per the CLAUDE.md push
policy — ask first). (b) The installed app does NOT get it from a Netlify
deploy. To push it to app users, cut an **app release** (recipe below). You do
NOT have to release the app for every web tweak — batch them.

**3. Native shell** — new Capacitor plugin, `AndroidManifest`, permission,
`capacitor.config.json`, native OAuth/scanner plumbing, app icon/splash.
→ **Must** be an app release (recipe below). This can never ship over-the-air,
even if Capgo is later turned on.

### App-release recipe

```
npm run app:sync                       # rebuild native/www + cap sync
# bump versionCode (+1, integer) and versionName in android/app/build.gradle
```

Then build + test locally (JBR + SDK env — this machine has no global JAVA_HOME):

```
cd android
JAVA_HOME="C:\Program Files\Android\Android Studio\jbr" \
ANDROID_HOME="$LOCALAPPDATA\Android\Sdk" ./gradlew.bat assembleDebug
# install to a plugged-in phone or the packsink_test emulator:
"$LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r \
  app/build/outputs/apk/debug/app-debug.apk
```

For the **Play Store**, build a signed AAB instead (`./gradlew bundleRelease`)
and upload to the Play Console (internal-testing track first). That needs the
one-time signing setup — see Phase 3 (keystore + Play App Signing), not yet done.

### Cadence

Deploy the web continuously; cut an app release **periodically** (when
meaningful UI changes accumulate, or a native change lands). The website is
always current; the app trailing by a release is expected and fine. Each Play
upload MUST have a higher `versionCode` than the last.

### Chosen update strategy (2026-07-17)

**Store-releases-only.** Capgo (`@capacitor/capacitor-updater`) is installed but
**dormant** (`autoUpdate:false` in `capacitor.config.json`) — zero cost, zero
network calls. Capgo cloud has no free tier ($14/mo Solo = 2k MAU). If instant
OTA ever becomes worth it, the cheap path is **self-hosting** the bundle on
Cloudflare R2 + a tiny worker (the plugin points at your own endpoint) — free at
our scale. Until then, free Play releases are sufficient (OTA is convenience,
not necessity; the app is secondary to the always-current website).

## First build (one-time setup — the only thing missing on this machine)

1. Install **Android Studio** (bundles the JDK and SDK): https://developer.android.com/studio
2. `npm run app:open` (or open the `android/` folder in Android Studio).
3. Let Gradle sync finish (first run downloads ~1 GB of SDK/Gradle bits).
4. Plug in a phone with USB debugging enabled (or make an emulator) → **Run ▶**.
   Debug builds need no signing.

CLI equivalent once the SDK exists: `cd android && ./gradlew assembleDebug`
→ APK at `android/app/build/outputs/apk/debug/`.

> OneDrive note: the repo lives inside OneDrive, and `node_modules/` +
> `android/` build outputs generate heavy file churn. If OneDrive sync gets
> noisy, exclude those folders (OneDrive Settings → Sync and backup → Advanced
> → choose folders), or just let it churn — it's cosmetic.

## Phase roadmap

### Phase 1 — scaffold (DONE 2026-07-17)
Everything above. App ID **`ink.packs.app`** — this becomes PERMANENT the
moment the first bundle is uploaded to Play; rename before then or never.

### Phase 2 — make it store-worthy
- **Native Google sign-in** (the one hard problem): add `@capacitor/browser` +
  `@capacitor/app`; `signInWithOAuth({ skipBrowserRedirect: true })` → open the
  URL in a system Custom Tab → redirect back via deep link (either a custom
  scheme `ink.packs.app://auth-callback` allow-listed in Supabase's redirect
  URLs, or an HTTPS App Link on packs.ink) → `exchangeCodeForSession(code)`
  (PKCE) inside the app. Google's WebView ban only applies to the embedded
  view — Custom Tabs are fully supported.
- **Device QA sweep**: external links (TCGPlayer affiliate `target="_blank"`)
  must open the system browser; hardware back vs the app's pushState history;
  status-bar color vs the 6 themes (`@capacitor/status-bar`); `/privacy` link
  behavior; keyboard vs the deck-notes textarea.
- **Deep links**: register `https://packs.ink` App Links (assetlinks.json on
  the site + intent filter) so shared `?deck=` / `?t=` URLs open the app.
- Camera permission plumbing for the scanner (AndroidManifest + Capacitor
  grants getUserMedia when the app holds `CAMERA`) — only when the scanner
  leaves admin-gating.

### Phase 3 — Play Store
- Google Play Console account ($25 once) → create app `ink.packs.app`.
- **Internal testing track first** (instant review, up to 100 testers).
- Release build: Android Studio → Generate Signed Bundle (AAB); let **Play App
  Signing** hold the release key (Google manages it; keep the upload key in a
  password manager).
- Listing needs: privacy policy URL (`https://packs.ink/privacy` ✓ already
  live), Data Safety form (declares: email + user ID collected for auth,
  collection data stored, no ads SDK, no data sold), content rating
  questionnaire, screenshots (phone + 7" tablet), 512px icon + 1024×500
  feature graphic.
- Each release: bump `versionCode` (integer, monotonic) + `versionName` in
  `android/app/build.gradle`.
- Note for later: if premium features ever become PAID, in-app purchase rules
  apply (Play Billing / Apple IAP) — currently premium is manually granted, so
  it's a non-issue.

### Phase 4 — iOS pathway (preserved by construction)
- `npm i @capacitor/ios && npx cap add ios` — same `native/www` bundle, same
  shims (`IS_NATIVE_APP` covers both platforms; `capacitor://localhost` origin
  behaves the same for our purposes). Needs a Mac (or a cloud Mac service) +
  Apple Developer account ($99/yr).
- WKWebView facts that already check out: IndexedDB ✓ (catalog cache),
  localStorage ✓ (auth/prefs), getUserMedia ✓ (iOS 14.3+, scanner),
  WASM ✓ — and no service worker needed since assets are local.
- **Apple guideline 4.2** (minimum functionality) is the review risk for any
  web-wrapped app. Mitigation = ship native-feeling capabilities WITH v1:
  push notifications (price alerts — F7 on the roadmap), native share sheet,
  haptics, camera scanner. The existing safe-area work (env(safe-area-inset-*))
  already makes it look right on notched iPhones.

## Known native limitations (accepted for now)

- **Sign-in disabled** (toast explains) → the app is a read-only market
  browser until Phase 2. Don't ship to a store track before fixing.
- **Scanner models excluded** from the bundle (16 MB, admin-gated feature);
  scanner UI would fail at model fetch. Decide in Phase 2: fetch from
  packs.ink at runtime vs bundle.
- **No offline image packs** (that's SW machinery) — the WebView's HTTP cache
  plus the 30-day immutable proxy headers give partial offline art instead.
  Catalog/user-data offline (IndexedDB) works fully.
- **App updates ship via store releases**, not deploys. The web site remains
  the always-current surface.
