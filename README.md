# Packs.Ink

Daily TCGplayer prices, price history, collection tracking, deck building and
tournament results for Disney Lorcana — https://packs.ink. An unofficial fan
site: not affiliated with, endorsed by, or sponsored by Disney or Ravensburger.

- **Site**: `Index.html` + `styles.css` (React via `htm`, no build step), the
  service worker `sw.js`, the standalone `swiss.html` / `ticker.html` /
  `privacy.html`, and the on-device card scanner (`scanner*.js`, `scanner/`).
- **Edge**: Cloudflare Worker `worker/index.js` serving `dist/`, which
  `scripts/build_dist.mjs` assembles from an include-list.
- **Data**: Supabase (Postgres + PostgREST). Schema and policies are the
  numbered migrations in `supabase/`; the daily ETL and helpers live in
  `scripts/` and run from `.github/workflows/`.
- **Native shell**: `native/` + `android/` (Capacitor) — see `native/README.md`.

Local preview: `python scripts/dev_server.py` then open http://localhost:8766/.
Guard tests: `for t in scripts/test_*.mjs; do node "$t"; done` and
`python scripts/test_*.py`.

Card data and art via Lorcast; prices via TCGCSV / TCGplayer. Third-party
library notices are in `vendor/LICENSES.md`. Security reports: `SECURITY.md`.
