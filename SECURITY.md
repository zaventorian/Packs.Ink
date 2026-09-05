# Security

Packs.Ink is a fan-made Disney Lorcana price and collection site run by one
person. If you find a vulnerability — in the site, the Cloudflare Worker, the
Supabase policies in `supabase/`, or the ETL scripts — please report it
privately rather than opening a public issue.

- DM **@packs_ink** or **@HighScoreZAP** on X (https://x.com/packs_ink).
- Include the URL or file, steps to reproduce, and what you were able to
  access. Share tokens (`?token=`, `?t=`) are secrets — redact them.

You will get a reply within 7 days. Please do not run automated scanners or
load tests against packs.ink; the data behind it is public and the site has
a request budget.

What is *not* a vulnerability: the publishable Supabase key in `Index.html`
(it is designed to be public; Row-Level Security is the access control), and
anything in `supabase/*.sql` (the policies are published on purpose).
