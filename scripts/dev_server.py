"""
SPA-fallback dev server for Packs.Ink.

Drop-in replacement for `python -m http.server`. Defaults to port 8766
to dodge a clash with AnkiConnect (which squats on 8765). Serves static
files normally, but routes that don't match a real file fall back to
/Index.html with a 200 — so reloading on /decks, /screener,
/decks?deck=<uuid>, etc. works locally just like it does on Netlify.

Usage:
    python scripts/dev_server.py            # http://localhost:8766/
    python scripts/dev_server.py 8000       # custom port

Real subfolders that ship as part of the deploy keep serving their own
files (Logos, scripts, supabase, _redirects) so e.g. ink-shield PNGs
still resolve.
"""
import http.server
import os
import socketserver
import sys
import urllib.parse
import urllib.request

# Folders that must serve their own files (and 404 if a child is missing).
# Match the same list as _redirects so dev mirrors prod.
PASSTHROUGH_FOLDERS = ("Logos", "scripts", "supabase", ".github")


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    # Force no-cache for Index.html / styles.css / logo.js so live edits
    # actually show up after a normal reload. Browsers (especially Chrome)
    # otherwise serve stale copies via the disk cache even when mtime
    # changed. Production Netlify cache rules don't run locally, so we
    # bypass entirely here.
    def end_headers(self):
        url_path = urllib.parse.urlsplit(self.path).path or "/"
        if url_path == "/" or url_path.endswith((".html", ".css", ".js")):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def _proxy_lorcast(self, path: str) -> None:
        """Mirror Netlify's /img-proxy/* → cards.lorcast.io rewrite so the
        Export Deck Image feature can draw images to a canvas locally too."""
        # Reject path-traversal attempts before building the upstream URL —
        # a "../" segment could be used to coax the proxy into fetching off
        # the intended host.
        if ".." in path:
            self.send_error(400, "bad proxy path")
            return
        upstream = "https://cards.lorcast.io/" + path.lstrip("/")
        try:
            req = urllib.request.Request(upstream, headers={"User-Agent": "packs.ink-dev/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "image/avif"))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(resp.read())
        except Exception as e:
            self.send_error(502, f"proxy failure: {e}")

    def do_GET(self):  # noqa: N802 - stdlib API
        parsed = urllib.parse.urlsplit(self.path)
        url_path = parsed.path or "/"
        if url_path.startswith("/img-proxy/"):
            return self._proxy_lorcast(url_path[len("/img-proxy/"):])
        # Mirror Netlify's pretty URL: /privacy serves the static privacy.html.
        if url_path == "/privacy":
            self.path = "/privacy.html"
            return super().do_GET()
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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    # Bind to loopback only — this is a local dev server; there's no reason to
    # expose it on the LAN / all interfaces.
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), SPAHandler) as httpd:
        print(f"Packs.Ink dev server: http://localhost:{port}/")
        print("SPA fallback active — try /decks, /screener, etc. directly.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()
