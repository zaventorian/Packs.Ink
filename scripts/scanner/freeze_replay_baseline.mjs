// Freeze the truth-labelled slice of data/replay_corpus.json (gitignored, built by
// pull_replay_corpus.py) into scripts/scanner/replay_baseline.json, which IS committed
// and is what scripts/test_scanner_matcher.mjs guards against.
//
//   node scripts/scanner/freeze_replay_baseline.mjs
//
// Writes the corpus rows AND the set of rows the CURRENT working-tree scanner.js
// answers correctly. The test fails when a row in that set stops being correct, so a
// swap (fix one, break one) can't hide behind an unchanged total.
//
// Re-freeze ONLY as a deliberate act: it re-baselines whatever the matcher does today,
// so running it to "fix" a failing test silently blesses the regression.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadScanner, scoreRows } from "./replay_common.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const SRC = path.join(HERE, "data", "replay_corpus.json");
const OUT = path.join(HERE, "replay_baseline.json");

if (!fs.existsSync(SRC)) {
  console.error(`missing ${SRC}\nrun: python scripts/scanner/pull_replay_corpus.py`);
  process.exit(1);
}
const all = JSON.parse(fs.readFileSync(SRC, "utf8"));
// keep only what the guard can judge: a recorded read plus a human/image truth
const rows = all
  .filter((r) => r.lines && r.lines.length && (r.truth_id || r.truth_nv))
  .map((r) => ({
    id: r.id, build: r.build, source: r.source, lines: r.lines,
    colour: r.colour || [], truth_id: r.truth_id || null, truth_nv: r.truth_nv || null,
  })); // `user` and `pred` are deliberately dropped - not needed to judge, and `user` is an account id

const CS = loadScanner(REPO, path.join(REPO, "scanner.js"));
await CS.loadText();
try { await CS.load(); } catch (e) { console.error("colour index load failed:", e.message); }
const { idOk, idN, nvOk, nvN, passIds } = scoreRows(CS, rows, REPO);

fs.writeFileSync(OUT, JSON.stringify({
  note: "Frozen by scripts/scanner/freeze_replay_baseline.mjs. Guarded by scripts/test_scanner_matcher.mjs.",
  frozen_at: new Date().toISOString().slice(0, 10),
  scanner_build: (fs.readFileSync(path.join(REPO, "Index.html"), "utf8").match(/SCANNER_BUILD\s*=\s*"([^"]+)"/) || [])[1] || "?",
  counts: { card_id_exact: idOk, card_id_total: idN, name_version: nvOk, name_version_total: nvN },
  pass_ids: passIds.sort(),
  rows,
}, null, 1) + "\n");

console.log(`froze ${rows.length} rows -> ${path.relative(REPO, OUT)}`);
console.log(`  card_id-exact ${idOk}/${idN}   name+version ${nvOk}/${nvN}   pinned pass rows: ${passIds.length}`);
console.log(`  ${(fs.statSync(OUT).size / 1024).toFixed(0)} KB`);
