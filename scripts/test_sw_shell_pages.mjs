// test_sw_shell_pages.mjs — a standalone page must never become the offline app shell.
//
//     node scripts/test_sw_shell_pages.mjs
//
// sw.js saves every successful dot-free navigation as the offline shell
// (/Index.html) unless its path is in NON_SHELL_PAGES. /picks and /box are
// standalone documents that were missing from that list (found 2026-10-06), so
// opening either one replaced the app shell and every route showed that page
// offline. This reads the deploy include-list in scripts/build_dist.mjs and
// fails when it ships a standalone .html page whose pretty path is not listed.
import { readFileSync } from "node:fs";

const sw = readFileSync(new URL("../sw.js", import.meta.url), "utf8");
const build = readFileSync(new URL("./build_dist.mjs", import.meta.url), "utf8");

let failed = 0;
const check = (name, ok) => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}`); };

const m = /const NON_SHELL_PAGES = (\[[^\]]*\]);/.exec(sw);
check("sw.js declares NON_SHELL_PAGES", !!m);
const listed = m ? JSON.parse(m[1].replace(/'/g, '"')) : [];

const filesBlock = build.slice(build.indexOf("const FILES = ["), build.indexOf("];", build.indexOf("const FILES = [")));
const pages = [...filesBlock.matchAll(/"([A-Za-z0-9_-]+)\.html"/g)].map(x => x[1]).filter(n => n.toLowerCase() !== "index");
check("build_dist ships standalone pages (sanity)", pages.length >= 4);
for (const p of pages) check(`/${p} is never saved as the offline shell`, listed.includes("/" + p));

check("the navigation branch consults the list",
  /if \(res\.ok && !url\.pathname\.includes\('\.'\) && !NON_SHELL_PAGES\.includes\(url\.pathname\)\)/.test(sw));

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
