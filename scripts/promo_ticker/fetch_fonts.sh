#!/usr/bin/env sh
# Download the two Google Fonts families the site uses into a local cache dir so
# record_promo.mjs can serve them to a browser with no egress to fonts.g*.com
# (the agent sandbox is exactly that case — see CLAUDE.md's "Fonts" note).
# Usage: sh scripts/promo_ticker/fetch_fonts.sh <outdir>
set -e
OUT="${1:?usage: fetch_fonts.sh <outdir>}"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
CSS="https://fonts.googleapis.com/css2?family=Cinzel:wght@400..700&family=Nunito+Sans:wght@300..800&display=swap"
mkdir -p "$OUT"
curl -sSf -A "$UA" "$CSS" -o "$OUT/fonts.css"
grep -o 'https://fonts.gstatic.com/[^)]*' "$OUT/fonts.css" | sort -u | while read -r u; do
  # Cache each woff2 under the basename the CSS asks for; the recorder matches on it.
  curl -sSf -A "$UA" "$u" -o "$OUT/$(basename "$u")"
done
echo "fonts cached in $OUT: $(ls "$OUT" | wc -l) files"
