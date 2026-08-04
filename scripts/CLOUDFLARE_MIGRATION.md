# Netlify → Cloudflare migration runbook

**Status: NOT STARTED.** packs.ink is 100% Netlify. The code below is built and
verified against a real `wrangler dev`, but nothing is deployed and no DNS has
changed.

**Why:** Netlify builds + bandwidth are metered on limited credits — that is the
entire reason for the commit-only push policy. Cloudflare is free and unlimited,
and this is a zero-build static site, so a deploy is a file upload. DDoS
protection matters mostly because on Netlify an attack costs *money*.

**What Cloudflare will NOT protect:** the browser talks to
`umwqowkiatjjltologrd.supabase.co` directly. Cloudflare never sees reads, writes
or auth. RLS + per-IP RPC limits stay the only guard on the data layer.

## Free-tier ceiling (know this before cutover)

Static asset requests are **free and unlimited** — a request only counts when it
invokes the Worker. So `Index.html`, `styles.css`, `Logos/`, `vendor/`,
`scanner/` are unmetered forever.

The Worker IS invoked on asset misses: **SPA deep links** (`/decks`) and **every
`/img-proxy/*` / `/tcg-img-proxy/*` request**. Those count against **100,000/day**
on the free plan. Card art is the heavy route.

**Crucially, exceeding it rate-limits (error 1015) — it does not bill.** There is
no overage meter, so the Netlify-style surprise-invoice scenario cannot happen.
If we need headroom the paid Workers plan is a flat **$5/mo for 10M requests**,
still cheaper than Netlify and still not an overage cliff.

Mitigations already in place: the proxy sets `Cache-Control: max-age=2592000,
immutable`, and `packsink-img-v1` caches art in the service worker — so most
image loads never reach the edge at all. Watch the Workers request graph for the
first week after cutover; if proxy invocations trend near the cap, either move to
the $5 plan or add a zone Cache Rule for the proxy prefixes.

---

## Phase 0 — prep (zero risk, nothing changes)

1. **Commit the migration files** (no push — they don't affect a Netlify build):
   `scripts/build_dist.mjs`, `worker/index.js`, `wrangler.toml`, `.gitignore`.

2. **Create a Cloudflare account** and **Add a site** → `packs.ink` → Free plan.
   This changes nothing. It exists to hand you two assigned nameservers, which
   you need before step 4.

3. **Check the DNS records Cloudflare imported.** It scans the current zone; the
   scan is not always complete. Confirm exactly:
   - `A  packs.ink → 98.84.224.111`
   - `A  packs.ink → 18.208.88.157`
   - `TXT packs.ink → google-site-verification=aLOt4whGHTTOGe5-...` ← Search Console dies without this
   - **No MX records** — correct, packs.ink has no email, so there is no mail to break.

   **Set every record to grey cloud (DNS only)** before going further. Orange
   cloud now would put Cloudflare in front of Netlify, which breaks Netlify's
   Let's Encrypt renewal. We skip that state entirely.

4. **Open the Netlify support ticket to change nameservers.** For a
   Netlify-*registered* domain this is NOT self-serve (there is no nameserver
   editor in the dashboard) — support does it, free, 1–3 days. **This is the
   critical path; open it first and do Phase 1 while waiting.**

   ⚠️ **We want NAMESERVER DELEGATION, not a REGISTRAR TRANSFER.** Netlify's
   "Transfer a Netlify-Registered Domain to Another Registrar" doc (Name.com,
   account codes, ICANN 60-day rule) is a *different, slower* process we do not
   need. Registration stays with Netlify; only the NS records move. Say so
   explicitly or support may start a transfer.

   Ticket template:

   > Subject: Set custom nameservers for Netlify-registered domain packs.ink
   >
   > packs.ink is registered through Netlify and currently uses Netlify DNS. I'd
   > like to keep the registration with Netlify but delegate DNS to Cloudflare.
   >
   > Please set the nameservers to:
   >   <name1>.ns.cloudflare.com
   >   <name2>.ns.cloudflare.com
   >
   > I am not requesting a registrar transfer. DNSSEC is not enabled on this
   > domain.

   **DNSSEC: verified NOT enabled** (2026-08-04 — no DS at the `.ink` parent, no
   DNSKEY, AD=false). This matters because delegating nameservers while DNSSEC is
   on breaks resolution outright — the domain goes dark, not degraded. Do not
   enable DNSSEC anywhere until after cutover is stable.

   Optional and unrelated: moving the *registration* off Netlify (→ Name.com →
   optionally Cloudflare Registrar, which sells at cost) can happen any time
   after cutover. Do not bundle it with this migration.

---

## Phase 1 — build and test off to the side (while the ticket sits)

Nothing here touches packs.ink.

5. **Local check:**
   ```
   node scripts/build_dist.mjs
   npx wrangler@4 dev --port 8787 --local
   ```
   Wrangler holds a file lock on `dist/` — always build BEFORE starting it, and
   kill the `node`+`workerd` process chain before rebuilding (`TaskStop` alone
   leaves orphans that keep the lock).

6. **Deploy to `*.workers.dev`** (`npx wrangler deploy`) — real Cloudflare, real
   edge, still nothing pointed at packs.ink.

   ⚠️ Wrangler auto-loads `.env`, which holds `SUPABASE_SERVICE_KEY`. The worker
   needs no secrets at all — check what a deploy uploads before running it.

7. **Verify on the workers.dev URL:**
   - [ ] Home renders, no console errors
   - [ ] Card art loads (that's `/img-proxy/*` working)
   - [ ] Sealed art loads (`/tcg-img-proxy/*`)
   - [ ] Deep links: `/decks`, `/screener`, `?deck=<id>&token=<x>`
   - [ ] `/privacy` serves the real static file, not the app shell
   - [ ] PWA installs; offline mode works after one online visit
   - [ ] A deck/card poster export produces a non-blank image (proves canvas isn't tainted)

8. **Stage the `sw.js` fix as its own commit — do not push.** See "Must ride the
   cutover" below. It only makes sense on cutover day.

---

## Phase 2 — flip nameservers (reversible, expect a no-op)

9. Netlify support moves NS → Cloudflare. Records still point at Netlify, still
   grey-clouded. **The site should behave identically** — Cloudflare is only
   answering DNS at this point.

10. Verify and then **let it sit a day or two**:
    ```
    nslookup -type=NS packs.ink        # expect *.ns.cloudflare.com
    nslookup packs.ink                 # expect the same two Netlify IPs
    curl -sI https://packs.ink | head -1
    ```
    - [ ] Site loads normally
    - [ ] HTTPS valid
    - [ ] Google Search Console still verified

    **Rollback:** change nameservers back. Nothing is committed to yet.

---

## Phase 3 — cutover (the real switch)

Do this on a day you can watch it. Not before a weekend.

11. Point `packs.ink` at the Worker (Workers route / custom domain), **orange
    cloud** it, SSL/TLS mode **Full (strict)**.

12. **Same deploy carries the `sw.js` fix** + `CACHE_VERSION` bump + the lockstep
    `styles.css?v=N` / `logo.js?v=N` bumps.

13. **Verify on packs.ink:**
    - [ ] Everything from step 7, on the real domain
    - [ ] **Android app still loads card art** — it points at packs.ink, so it
          follows automatically; no store release needed, but confirm it
    - [ ] Google OAuth sign-in works
    - [ ] `synthetic_monitor.py` passes
    - [ ] UptimeRobot green
    - [ ] Hard-refresh + PWA force-quit twice, confirm the new SW takes over

14. **Leave Netlify running ~2 weeks.** Rollback = point the A records back at
    `98.84.224.111` / `18.208.88.157` and grey cloud. Minutes, not hours.

---

## Phase 4 — harden, then decommission

Only once prod has been boring for a week.

15. **DO NOT enable Bot Fight Mode.** ⚠️ Corrected 2026-08-04 — earlier guidance
    here said "enable it with skip rules for the proxy paths." **That is not
    possible on the Free plan.** Cloudflare's docs are explicit that free Bot
    Fight Mode "cannot be customized, adjusted, or reconfigured via custom rules"
    and "cannot be bypassed with custom rule Skip actions." Skip actions require
    **Super** Bot Fight Mode, which is Pro ($20/mo) and up.

    So on Free it is all-or-nothing, and "all" breaks us:
    - `/img-proxy/*` + `/tcg-img-proxy/*` — the native app loads these as `<img>`
      from `https://localhost`. A challenge returns HTML where a JPEG should be →
      **broken card art in the Android app** and blank canvas exports. An `<img>`
      cannot solve a JS challenge.
    - `synthetic_monitor.py` (headless `requests.get`, every 2h) and UptimeRobot
      (every 5 min) both get challenged → permanent false alarms.

    Use a **rate limiting rule** instead (1 free rule, IP-based, 10s window),
    scoped by expression to the two proxy prefixes. That defends the one
    genuinely expensive route without touching real users, the native app, or the
    monitors. Re-run the step 13 checklist after adding it.

    Revisit Pro only if real attack traffic shows up. At current scale it isn't
    close to justified.

16. **"Checking your browser" = Under Attack Mode.** A toggle you flip *during*
    an incident, not an always-on setting. Know where it is; leave it off.

17. **DDoS protection needs no configuration** — it is automatic from the moment
    you are orange-clouded in step 11.

18. **Turn off the Netlify site.**

19. **Relax the push policy in `CLAUDE.md`.** That's the payoff — builds are free
    and instant now.

---

## Must ride the cutover deploy

`sw.js` `CORE_ASSETS` lists `/Index.html`. Cloudflare 307-redirects that to `/`,
and `cache.add()` rejects redirected responses — so it silently fails into its
existing `.catch(() => null)`. `sw.js:121`'s offline fallback matches the key
`/Index.html`, which only `sw.js:117` populates, and only on an *intercepted*
navigation. The install-time navigation isn't intercepted, so there's a window
between "SW installs" and "user navigates once more while online" with no offline
shell. Fix: fall back to `/` when the `/Index.html` key misses.

Harmless on Netlify, so it *can* ship early — but it forces a `CACHE_VERSION` +
`?v=N` lockstep bump, which is why it's cheaper to bundle into the cutover.

---

## Gotchas already paid for (don't rediscover)

- Cloudflare `_redirects` supports **neither** external proxies **nor** 200
  rewrites. That's why `worker/index.js` owns all routing.
- Cloudflare 307s `/Index.html` → `/`, making the capital-I file unreachable and
  the SPA fallback serve blank pages. `build_dist.mjs` publishes it lowercase
  (same fix `native/sync.mjs` uses); the worker fetches `/`, not `/index.html`.
- `cpSync` copies from **disk, not git** — it was shipping untracked
  `Logos/PacksInk.ai` (18.6 MB). Hence `excludeExt`.
- Do **not** add a `build` script to `package.json` before cutover. It could make
  Netlify start running a build it isn't running today, and builds cost money.
- The old `_redirects` `404!` rules were a DENY list with holes: 83 files are
  publicly served from packs.ink today (the whole `android/` project, `native/`,
  `package.json`, `capacitor.config.json`). Verified **no secrets** — no keystore
  tracked, no `signingConfigs`, `gradle.properties` is boilerplate. The
  include-list in `build_dist.mjs` deletes the whole category at cutover, so this
  is not worth a metered Netlify build to patch sooner.
