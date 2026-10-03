// CLAUDE.md is loaded into every session, so it stays an index of rules; the
// long notes live in docs/claude/. This fails when a stub points at a file
// that is gone, when a doc is orphaned, or when CLAUDE.md swells again.
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const md = readFileSync(join(root, "CLAUDE.md"), "utf8");
let fails = 0;
const check = (ok, msg) => { if (!ok) { fails++; console.log("FAIL", msg); } };

const refs = [...new Set([...md.matchAll(/docs\/claude\/[a-z0-9-]+\.md/g)].map(m => m[0]))];
check(refs.length >= 40, `CLAUDE.md points at its feature notes (${refs.length})`);
for (const r of refs) check(existsSync(join(root, r)), `${r} exists`);
for (const f of readdirSync(join(root, "docs", "claude"))) {
  check(refs.includes(`docs/claude/${f}`), `docs/claude/${f} is linked from CLAUDE.md`);
}
const kb = statSync(join(root, "CLAUDE.md")).size / 1024;
check(kb < 200, `CLAUDE.md is under 200 KB (${kb.toFixed(0)} KB): move the write-up to docs/claude/ and keep the rule`);
console.log(fails ? `FAILS: ${fails}` : `ok: ${refs.length} notes linked, CLAUDE.md ${kb.toFixed(0)} KB`);
process.exit(fails ? 1 : 0);
