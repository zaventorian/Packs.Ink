// Guard: the card matcher must not regress.
//
//   node scripts/test_scanner_matcher.mjs
//
// Replays 400 REAL recorded OCR reads (scripts/scanner/replay_baseline.json, frozen
// from scan_samples) through the REAL scanner.js identify(), and fails if either
// accuracy count drops OR any individual row that used to answer correctly stops
// doing so. Offline, no network, no photos - the reads and their human/image-verified
// truth labels are committed.
//
// WHY the per-row set and not just the totals: a matcher change that fixes three cards
// and breaks three others leaves every total identical. That swap is exactly the thing
// worth catching, and it is invisible to a scalar floor.
//
// When a change legitimately IMPROVES things, re-freeze deliberately:
//   python scripts/scanner/pull_replay_corpus.py      (needs .env; optional - refreshes rows)
//   node scripts/scanner/freeze_replay_baseline.mjs
// Re-freezing to silence a failure blesses the regression, so read the named rows first.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadScanner, scoreRows, cardsById, describe } from "./scanner/replay_common.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..");
const BASE = path.join(HERE, "scanner", "replay_baseline.json");

let fails = 0;
const fail = (m) => { console.log(`  FAIL  ${m}`); fails++; };
const ok = (m) => console.log(`  ok    ${m}`);

const base = JSON.parse(fs.readFileSync(BASE, "utf8"));
const CS = loadScanner(REPO, path.join(REPO, "scanner.js"));
await CS.loadText();
try { await CS.load(); } catch (e) { console.error("colour index load failed:", e.message); process.exit(1); }

const res = scoreRows(CS, base.rows, REPO);
const byId = cardsById(REPO);

console.log(`scanner matcher replay - ${base.rows.length} recorded reads, frozen ${base.frozen_at} at build ${base.scanner_build}`);
console.log(`  now: card_id-exact ${res.idOk}/${res.idN}   name+version ${res.nvOk}/${res.nvN}`);
console.log(`  was: card_id-exact ${base.counts.card_id_exact}/${base.counts.card_id_total}   name+version ${base.counts.name_version}/${base.counts.name_version_total}`);

// 1. the denominators must not move - a row that stops producing ANY answer would
//    otherwise quietly shrink the total and make the accuracy ratio look better.
if (res.idN !== base.counts.card_id_total) fail(`card_id denominator moved ${base.counts.card_id_total} -> ${res.idN} (rows stopped answering?)`);
else ok(`card_id denominator steady at ${res.idN}`);
if (res.nvN !== base.counts.name_version_total) fail(`name+version denominator moved ${base.counts.name_version_total} -> ${res.nvN}`);
else ok(`name+version denominator steady at ${res.nvN}`);

// 2. neither accuracy count may drop
if (res.idOk < base.counts.card_id_exact) fail(`card_id-exact dropped ${base.counts.card_id_exact} -> ${res.idOk}`);
else ok(`card_id-exact ${res.idOk} >= ${base.counts.card_id_exact}`);
if (res.nvOk < base.counts.name_version) fail(`name+version dropped ${base.counts.name_version} -> ${res.nvOk}`);
else ok(`name+version ${res.nvOk} >= ${base.counts.name_version}`);

// 3. no individual row may go from right to wrong
const nowPass = new Set(res.passIds);
const lost = base.pass_ids.filter((id) => !nowPass.has(id));
if (lost.length) {
  fail(`${lost.length} row(s) regressed from correct to wrong:`);
  const rowById = new Map(base.rows.map((r) => [r.id, r]));
  for (const id of lost.slice(0, 20)) {
    const row = rowById.get(id);
    const truth = row.truth_id ? describe(byId, row.truth_id) : (row.truth_nv || []).join(" - ");
    console.log(`          #${id} [${row.build}|${row.source}]  truth: ${truth}`);
    console.log(`             now: ${describe(byId, res.verdicts[id])}`);
    console.log(`             read: ${JSON.stringify(row.lines).slice(0, 110)}`);
  }
  if (lost.length > 20) console.log(`          ... and ${lost.length - 20} more`);
} else ok(`all ${base.pass_ids.length} previously-correct rows still correct`);

// 4. gained rows are reported, never failed - they are the reason to re-freeze
const gained = res.passIds.filter((id) => !base.pass_ids.includes(id));
if (gained.length) console.log(`  note  ${gained.length} row(s) newly correct - re-freeze the baseline to pin the gain`);

console.log(fails ? `\nFAILED (${fails})` : "\nPASS");
process.exit(fails ? 1 : 0);
