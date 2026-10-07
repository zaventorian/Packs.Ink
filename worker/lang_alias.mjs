// Language links: /ja/… /de/… /fr/… /it/… /en/… (and /jp/…, which is what
// people type for Japanese) open the same page in that language. The prefix is
// a SHORTCUT, not a second copy of the site: it redirects to the same path with
// ?hl=<lang>, the preview the app already understands (a link may choose the
// language for you, never over you, and ?hl= rides along through in-app
// navigation so a refresh stays in it).
//
// A real /ja/ prefix kept in the address bar was considered and not built: a
// two-segment path breaks every relative asset URL in Index.html (the
// documented /t/<token> crash) and every URL the app writes would need it.
//
// 302, not 301: a browser keeps a 301 forever, which would stand in the way of
// ever making /ja/ the Japanese site's real address.
export const LANG_PREFIXES = { ja: "ja", jp: "ja", de: "de", fr: "fr", it: "it", en: "en" };

// The redirect target for a language-prefixed URL, or null when the path does
// not start with one. The rest of the query is kept VERBATIM (re-serialising
// it would percent-encode the ~ ; : , that the ?g= and ?v= codecs use).
export function langAliasTarget(url) {
  const m = /^\/([A-Za-z]{2})(?=\/|$)(.*)$/.exec(url.pathname);
  if (!m) return null;
  const lang = LANG_PREFIXES[m[1].toLowerCase()];
  if (!lang) return null;
  // "/ja//evil.com" must not become the protocol-relative "//evil.com".
  const path = "/" + m[2].replace(/^[/\\]+/, "");
  const kept = url.search.replace(/^\?/, "").split("&")
    .filter((p) => p && p !== "hl" && !p.startsWith("hl="));
  kept.push("hl=" + lang);
  const target = new URL(path + "?" + kept.join("&"), url.origin);
  return target.origin === url.origin ? target.toString() : null;
}
