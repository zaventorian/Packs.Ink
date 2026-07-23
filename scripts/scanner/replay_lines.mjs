// Matcher A/B harness: replay every recorded field OCR read (replay_corpus.json,
// from pull_replay_corpus.py) through the REAL scanner.js identify() â€” old build
// vs working tree â€” and report accuracy + every changed verdict.
//
//   node replay_lines.mjs [--old <path-to-old-scanner.js>]
//
// Replays are lines-only (cnNum/cnSet/colourRanked absent), which reproduces the
// name/subtitle/body path faithfully; fusion rows that leaned on live colour are
// reported separately. Both sides load the SAME scanner/text.json (old code
// ignores the added `r` field).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const args = process.argv.slice(2);
const oldIdx = args.indexOf("--old");
const OLD_JS = oldIdx >= 0 ? args[oldIdx + 1] : null;
const NEW_JS = path.join(REPO, "scanner.js");
const CORPUS = path.resolve(HERE, "data", "replay_corpus.json");

const textRaw = fs.readFileSync(path.join(REPO, "scanner", "text.json"), "utf8");
const byId = {};
for (const c of JSON.parse(textRaw)) byId[c.id] = c;

function loadScanner(jsPath) {
  const src = fs.readFileSync(jsPath, "utf8");
  const ctxStub = () => ({ });
  const documentStub = { createElement: () => ({ getContext: ctxStub, width: 0, height: 0 }) };
  const win = {};
  // fresh JSON.parse per side â€” the new build SORTS text.cards in place
  const fetchStub = () => Promise.resolve({ json: () => Promise.resolve(JSON.parse(textRaw)) });
  new Function("window", "document", "fetch", src)(win, documentStub, fetchStub);
  return win.CardScanner;
}

const corpus = JSON.parse(fs.readFileSync(CORPUS, "utf8"));
const nv = (id) => { const c = byId[id]; return c ? `${c.n}|${c.v || ""}` : id; };
const disp = (id) => {
  const c = byId[id];
  return c ? `${c.n}${c.v ? " - " + c.v : ""} [${c.r || "?"} ${c.s || "?"}#${c.cn || "?"}]` : String(id);
};

async function runSide(jsPath) {
  const CS = loadScanner(jsPath);
  await CS.loadText();
  const out = {};
  for (const row of corpus) {
    if (!row.lines || !row.lines.length) continue;
    const r = CS.identify({ lines: row.lines, cnNum: null, cnSet: null, colourRanked: [] });
    out[row.id] = { top1: (r.top3 && r.top3[0]) || null, conf: r.conf, source: r.source, verBy: r.verBy || null };
  }
  return out;
}

const newOut = await runSide(NEW_JS);
const oldOut = OLD_JS ? await runSide(OLD_JS) : null;

function score(out) {
  let idOk = 0, idN = 0, nvOk = 0, nvN = 0;
  for (const row of corpus) {
    const o = out[row.id];
    if (!o || !o.top1) continue;
    if (row.truth_id) { idN++; if (o.top1 === row.truth_id) idOk++; }
    if (row.truth_nv) {
      nvN++;
      const c = byId[o.top1];
      if (c && c.n === row.truth_nv[0] && (c.v || "") === (row.truth_nv[1] || "")) nvOk++;
    }
  }
  return { idOk, idN, nvOk, nvN };
}

const sNew = score(newOut);
console.log(`corpus: ${corpus.length} snaps, replayed ${Object.keys(newOut).length}`);
console.log(`NEW  card_id-exact: ${sNew.idOk}/${sNew.idN}   name+version: ${sNew.nvOk}/${sNew.nvN}`);
if (oldOut) {
  const sOld = score(oldOut);
  console.log(`OLD  card_id-exact: ${sOld.idOk}/${sOld.idN}   name+version: ${sOld.nvOk}/${sOld.nvN}`);
  let changed = 0, regressions = 0;
  for (const row of corpus) {
    const o = oldOut[row.id], n = newOut[row.id];
    if (!o || !n || o.top1 === n.top1) continue;
    changed++;
    let flag = "";
    if (row.truth_id) {
      if (o.top1 !== row.truth_id && n.top1 === row.truth_id) flag = "FIXED";
      else if (o.top1 === row.truth_id && n.top1 !== row.truth_id) { flag = "REGRESSION"; regressions++; }
      else flag = "still-wrong";
    } else if (row.truth_nv) {
      const co = byId[o.top1], cn2 = byId[n.top1];
      const okO = co && co.n === row.truth_nv[0] && (co.v || "") === (row.truth_nv[1] || "");
      const okN = cn2 && cn2.n === row.truth_nv[0] && (cn2.v || "") === (row.truth_nv[1] || "");
      if (!okO && okN) flag = "FIXED(nv)";
      else if (okO && !okN) { flag = "REGRESSION(nv)"; regressions++; }
      else flag = "no-truth-change";
    } else {
      // no truth â€” same name+version swap (reprint reorder) is expected & benign
      flag = nv(o.top1) === nv(n.top1) ? "reprint-reorder" : "unlabeled-change";
    }
    console.log(`  #${row.id} [${row.build || "?"}|${row.source || "?"}] ${flag}\n     old: ${disp(o.top1)}\n     new: ${disp(n.top1)}`);
  }
  console.log(`changed: ${changed}   REGRESSIONS: ${regressions}`);
}
