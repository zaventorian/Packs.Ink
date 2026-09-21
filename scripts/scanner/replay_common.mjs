// Shared loader + scorer for the OCR-replay harness, so the freezer
// (freeze_replay_baseline.mjs) and the guard (scripts/test_scanner_matcher.mjs)
// can never disagree about what "correct" means.
//
// Lifted verbatim in behaviour from replay_lines.mjs, which stays the interactive
// A/B tool (it diffs two builds and prints every changed verdict).
import fs from "node:fs";
import path from "node:path";

// Loads the REAL scanner.js and hands back window.CardScanner. The scanner fetches
// its index files at runtime, so those are stubbed from disk.
//
// The colour index is loaded for a reason: baseGuard's sibling test asks whether two
// reference vectors are near-twins, and without color.bin every pair takes the
// "cannot separate" branch, which overstates accuracy.
export function loadScanner(REPO, jsPath) {
  const src = fs.readFileSync(jsPath, "utf8");
  const textRaw = fs.readFileSync(path.join(REPO, "scanner", "text.json"), "utf8");
  const idxRaw = fs.readFileSync(path.join(REPO, "scanner", "index.json"), "utf8");
  const colBin = fs.readFileSync(path.join(REPO, "scanner", "color.bin"));
  const dhBin = fs.readFileSync(path.join(REPO, "scanner", "dhash.bin"));
  const toAB = (b) => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
  const documentStub = { createElement: () => ({ getContext: () => ({}), width: 0, height: 0 }) };
  const win = {};
  const fetchStub = (u) => {
    const url = String(u);
    // fresh JSON.parse per call - the scanner SORTS text.cards in place
    if (url.includes("index.json")) return Promise.resolve({ json: () => Promise.resolve(JSON.parse(idxRaw)) });
    if (url.includes("color.bin")) return Promise.resolve({ arrayBuffer: () => Promise.resolve(toAB(colBin)) });
    if (url.includes("dhash.bin")) return Promise.resolve({ arrayBuffer: () => Promise.resolve(toAB(dhBin)) });
    return Promise.resolve({ json: () => Promise.resolve(JSON.parse(textRaw)) });
  };
  new Function("window", "document", "fetch", src)(win, documentStub, fetchStub);
  return win.CardScanner;
}

export function cardsById(REPO) {
  const raw = fs.readFileSync(path.join(REPO, "scanner", "text.json"), "utf8");
  const byId = {};
  for (const c of JSON.parse(raw)) byId[c.id] = c;
  return byId;
}

// Replays every row and returns the counts plus the ids that answered correctly.
// A row counts as correct on the card_id axis when truth_id matches exactly, and on
// the name+version axis when the chosen card's (n, v) matches - the weaker axis, kept
// because the image-verified historical truth table is only (name, version)-level.
export function scoreRows(CS, rows, REPO) {
  const byId = cardsById(REPO);
  let idOk = 0, idN = 0, nvOk = 0, nvN = 0;
  const passIds = [];
  const verdicts = {};
  for (const row of rows) {
    if (!row.lines || !row.lines.length) continue;
    const r = CS.identify({ lines: row.lines, cnNum: null, cnSet: null, colourRanked: row.colour || [] });
    const top1 = (r.top3 && r.top3[0]) || null;
    verdicts[row.id] = top1;
    if (!top1) continue;
    let ok = false;
    if (row.truth_id) { idN++; if (top1 === row.truth_id) { idOk++; ok = true; } }
    if (row.truth_nv) {
      nvN++;
      const c = byId[top1];
      const hit = c && c.n === row.truth_nv[0] && (c.v || "") === (row.truth_nv[1] || "");
      if (hit) { nvOk++; if (!row.truth_id) ok = true; }
      // when BOTH truths exist the card_id axis is the stricter one and already decided `ok`
    }
    if (ok) passIds.push(row.id);
  }
  return { idOk, idN, nvOk, nvN, passIds, verdicts };
}

export function describe(byId, id) {
  const c = byId[id];
  return c ? `${c.n}${c.v ? " - " + c.v : ""} [${c.r || "?"} ${c.s || "?"}#${c.cn || "?"}]` : String(id);
}
