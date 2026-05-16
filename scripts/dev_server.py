"""
SPA-fallback dev server for Packs.Ink.

Drop-in replacement for `python -m http.server 8765`. Same default port,
serves static files normally, but routes that don't match a real file
fall back to /Index.html with a 200 — so reloading on /decks, /screener,
/decks?deck=<uuid>, etc. works locally just like it does on Netlify.

Usage:
    python scripts/dev_server.py
    python scripts/dev_server.py 8000    # custom port

Real subfolders that ship as part of the deploy keep serving their own
files (Logos, scripts, supabase, _redirects) so e.g. ink-shield PNGs
still resolve.
"""
import http.server
import os
import socketserver
import sys
import urllib.parse

# Folders that must serve their own files (and 404 if a child is missing).
# Match the same list as _redirects so dev mirrors prod.
PASSTHROUGH_FOLDERS = ("Logos", "scripts", "supabase", ".github")


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib API
        parsed = urllib.parse.urlsplit(self.path)
        url_path = parsed.path or "/"
        # Strip query string when checking on-disk; reattach when rewriting.
        rel = url_path.lstrip("/")
        disk = os.path.join(os.getcwd(), rel) if rel else os.path.join(os.getcwd(), "Index.html")

        # File exists OR it's a known passthrough folder → let the default
        # handler do its thing (it'll 404 inside passthrough folders for
        # missing files, which is the same behavior as Netlify).
        first = rel.split("/", 1)[0] if rel else ""
        is_passthrough = first in PASSTHROUGH_FOLDERS
        if os.path.exists(disk) or is_passthrough or rel == "":
            return super().do_GET()

        # SPA fallback — rewrite to Index.html, keep the query so the client
        # can read window.location.pathname + search after loading.
        self.path = "/Index.html"
        if parsed.query:
            self.path += "?" + parsed.query
        return super().do_GET()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    with socketserver.ThreadingTCPServer(("", port), SPAHandler) as httpd:
        print(f"Packs.Ink dev server: http://localhost:{port}/")
        print("SPA fallback active — try /decks, /screener, etc. directly.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()
