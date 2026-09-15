// Guards the one CSP rule that breaks silently: a cross-origin host the page
// loads as an IMAGE (or font, or stylesheet) must appear in connect-src too,
// because sw.js re-fetches every cross-origin request via fetch() and a fetch()
// from the service-worker context is classified as connect-src, NOT as the
// resource's own directive. _headers says this in prose; nothing checked it.
// It also pins that the page policies — /*, plus one per page the Analytics tab
// iframes (/swiss, /ticker) — stay byte-identical apart from frame-ancestors.
//
// It shipped broken exactly once, with the calendar's OpenStreetMap mini map:
// tile.openstreetmap.org went into img-src only, so the SW's fetch was blocked
// and the tiles came back a network error for every returning visitor. Both
// ways a person would normally catch that are blind here — _headers does not
// apply on the local dev server, and a FIRST load has no service worker yet, so
// the map renders perfectly until you reload.
//
// node scripts/test_csp_headers.mjs

import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../_headers", import.meta.url), "utf8");
let pass = 0;
const fail = [];
const ok = (label) => { pass++; console.log("PASS  " + label); };
const check = (cond, label, detail) => cond ? ok(label) : fail.push(detail ? `${label}\n        ${detail}` : label);

const policies = src
  .split("\n")
  .map((l) => l.trim())
  .filter((l) => l.startsWith("Content-Security-Policy:"))
  .map((l) => l.slice("Content-Security-Policy:".length).trim());

check(policies.length >= 3, `found the policies (${policies.length})`);

const directive = (policy, name) => {
  const m = policy.match(new RegExp(`(?:^|;)\\s*${name}\\s+([^;]*)`));
  return m ? m[1].trim().split(/\s+/) : null;
};
// Only real cross-origin hosts: 'self', data:, blob: and quoted keywords are
// not hosts and are never re-fetched by the SW as a named origin.
const hosts = (list) => (list || []).filter((v) => v.startsWith("https://") || v.startsWith("wss://"));

// A page policy is one that loads images. The /scanner-worker.js block is
// default-src 'none' with no img-src — a different context that renders nothing.
const pagePolicies = policies.filter((p) => directive(p, "img-src"));
check(
  pagePolicies.length === 3,
  `three page policies carry an img-src (/*, /swiss, /ticker), got ${pagePolicies.length}`,
  "a page block was added or lost — if it was added, its body must match /* apart from frame-ancestors."
);

// ── the rule ──────────────────────────────────────────────────────────────
// script-src is deliberately NOT checked: cdnjs.cloudflare.com sits there and
// not in connect-src, left over from before html2canvas was vendored under
// /vendor/. Adding it here would assert something nobody has verified.
for (const [i, policy] of pagePolicies.entries()) {
  const connect = hosts(directive(policy, "connect-src"));
  for (const name of ["img-src", "font-src", "style-src"]) {
    for (const host of hosts(directive(policy, name))) {
      check(
        connect.includes(host),
        `policy ${i + 1}: ${name} host ${host} is also in connect-src`,
        `sw.js re-fetches it, and a SW fetch() is connect-src. Add ${host} to connect-src in EVERY page policy in _headers.`
      );
    }
  }
}

// ── the regression this was written for ───────────────────────────────────
for (const [i, policy] of pagePolicies.entries()) {
  const img = hosts(directive(policy, "img-src"));
  const connect = hosts(directive(policy, "connect-src"));
  check(img.includes("https://tile.openstreetmap.org"), `policy ${i + 1}: the calendar map's tile host is in img-src`);
  check(connect.includes("https://tile.openstreetmap.org"), `policy ${i + 1}: the calendar map's tile host is in connect-src`);
}

// ── the page policies must not drift ──────────────────────────────────────
// _headers tells a reader to "add the origin to every copy"; they differ only
// by frame-ancestors ('none' on /*, 'self' on /swiss and /ticker so the
// Analytics tab can iframe them). Anything else diverging means one copy was
// edited alone — which is silent: the embedded page just loses that origin.
const strip = (p) => p.replace(/frame-ancestors\s+[^;]*;?\s*/, "");
const EMBEDS = ["/swiss (Swiss Odds)", "/ticker (Stream Ticker)"];
const embedName = (i) => EMBEDS[i - 1] || `page policy ${i + 1}`;
for (let i = 1; i < pagePolicies.length; i++) {
  check(
    strip(pagePolicies[0]) === strip(pagePolicies[i]),
    `the /* and ${embedName(i)} policies are identical apart from frame-ancestors`,
    "one copy was edited without the other."
  );
  check(
    /frame-ancestors\s+'self'/.test(pagePolicies[i]),
    `${embedName(i)} keeps frame-ancestors 'self' (the Analytics embed)`,
    "without it the tab renders the browser's gray broken-page icon."
  );
}
check(/frame-ancestors\s+'none'/.test(pagePolicies[0]), "/* keeps frame-ancestors 'none'");

console.log("");
if (fail.length) {
  console.error(`FAILED ${fail.length} check(s):`);
  for (const f of fail) console.error("  - " + f);
  process.exit(1);
}
console.log(`all ${pass} CSP header checks passed`);
