# /box — the invite-only Ink.Box page (2026-10-02)

`box.html`, a **standalone page like `/picks`**: the phone companion for Ink.Box, Zaven's
thermal card printer (its own repo, `Desktop/Ink.Box`; start with `docs/SCOPE.md` there).
A signed-in, allow-listed account can pair a box and send it print jobs (cards, decks,
packs) from anywhere.

- **⚠ `box.html` is GENERATED — do not edit it here.** It is `app/index.html` from the
  Ink.Box repo with this site's `SUPABASE_URL` / `SUPABASE_KEY` / `DECK_ENC_KEY_B64`
  inlined and `/vendor/supabase.js` loaded (so it shares the site's sign-in). Rebuild with
  `python tools/packsink.py build` in Ink.Box and copy `dist/box.html` over. Rotating any
  of those three constants in `Index.html` means rebuilding it; `scripts/test_box_page.mjs`
  goes red until you do.
- **Not for normal people (Zaven, 2026-10-02).** Four separate mechanisms, all guarded by
  that test: `noindex` meta, `robots.txt` Disallow, nothing links to it, and the page shows
  only a "for Ink.Box owners" card unless `is_inkbox_user()` says the signed-in account is
  on the allow-list. The database enforces the same list, so the page gate is cosmetic and
  the RPC gate is the real one.
- **Database: migration 177** (`inkbox_testers`, `inkbox_devices`, `inkbox_jobs` + RPCs).
  `inkbox_testers` is email-keyed like `scanner_testers`; rows live only in the DB:
  `insert into public.inkbox_testers (email) values ('...') on conflict do nothing;`
  Removing a row switches everything off for that account, including a box it had paired.
- The box itself is not a signed-in user: it calls `inkbox_register_device` /
  `inkbox_claim_jobs` / `inkbox_finish_job` with the publishable key plus its own device
  secret (stored hashed). Those three are anon-callable by design and show up in the
  security advisor's definer-function list alongside the share-link RPCs.
- Behaviour test for the migration lives in the Ink.Box repo (`cloud/test_migration.mjs`,
  PGlite, 60 checks).
