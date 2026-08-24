// test_deck_versions.mjs — guards the deck version-history diff.
//
//     node scripts/test_deck_versions.mjs
//
// Extracts diffDeckVersions + deckCardsSignature out of Index.html so they
// can't drift from what ships.
//
// The signature is the more dangerous of the two. It decides whether an editing
// session gets written to history at all, and both ways of being wrong are
// silent: too sensitive and every Done writes a version with an empty changelog
// until the retention cap chews through the real history; not sensitive enough
// and a genuine edit vanishes with nothing to show it ever happened. Card
// arrays arrive from PostgREST in no guaranteed order, so order-independence is
// the property that actually matters.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const NL = String.fromCharCode(10);

function grab(start, end) {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
}

// One whole line beginning with `prefix` — for the single-line consts.
function grabLine(prefix) {
  // split on NL, not a regex: a trailing CR can't affect startsWith.
  const line = src.split(NL).find((l) => l.startsWith(prefix));
  if (!line) throw new Error("missing line: " + prefix);
  return line;
}

const moduleSrc = [
  grabLine("const DECK_VER_SEP = "),
  grabLine("const deckVerKey = "),
  grab("const deckCardsSignature = (cards) =>", '.sort().join("|");'),
  grab("const diffDeckVersions = (fromCards, toCards) => {", NL + "};"),
  "export {diffDeckVersions, deckCardsSignature, deckVerKey};",
].join(NL);

const { diffDeckVersions, deckCardsSignature } =
  await import("data:text/javascript," + encodeURIComponent(moduleSrc));

let failed = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(
    (ok ? "PASS  " : "FAIL  ") + name +
    (ok ? "" : "  (got " + JSON.stringify(got) + ", want " + JSON.stringify(want) + ")"),
  );
};

const c = (card_id, quantity, printing = "Normal") => ({ card_id, printing, quantity });

// ── deckCardsSignature: "did this session change anything?" ──────────────
const base = [c("a", 4), c("b", 2), c("d", 1, "Cold Foil")];

check("identical lists match", deckCardsSignature(base) === deckCardsSignature(base.slice()), true);
check("order does not matter",
  deckCardsSignature(base) === deckCardsSignature([base[2], base[0], base[1]]), true);
check("a quantity change is detected",
  deckCardsSignature(base) === deckCardsSignature([c("a", 3), c("b", 2), c("d", 1, "Cold Foil")]), false);
check("an added card is detected",
  deckCardsSignature(base) === deckCardsSignature(base.concat([c("z", 1)])), false);
check("a removed card is detected",
  deckCardsSignature(base) === deckCardsSignature(base.slice(0, 2)), false);
// Printing is part of the deck_cards PK, so the same card in a different
// finish is a different row and a real edit.
check("swapping a printing is detected",
  deckCardsSignature([c("a", 4)]) === deckCardsSignature([c("a", 4, "Cold Foil")]), false);
check("empty lists match", deckCardsSignature([]) === deckCardsSignature([]), true);
check("null is treated as empty", deckCardsSignature(null) === deckCardsSignature([]), true);

// ── diffDeckVersions ─────────────────────────────────────────────────────
const noChange = diffDeckVersions(base, base.slice());
check("no changes reports empty", noChange.isEmpty, true);
check("no changes has no rows",
  [noChange.added.length, noChange.removed.length, noChange.changed.length], [0, 0, 0]);

const d1 = diffDeckVersions([c("a", 4), c("b", 2)], [c("a", 4), c("c", 3)]);
check("added card", d1.added, [{ card_id: "c", printing: "Normal", qty: 3 }]);
check("removed card", d1.removed, [{ card_id: "b", printing: "Normal", qty: 2 }]);
check("nothing spuriously changed", d1.changed, []);
check("not empty", d1.isEmpty, false);

const d2 = diffDeckVersions([c("a", 4)], [c("a", 1)]);
check("quantity down", d2.changed, [{ card_id: "a", printing: "Normal", from: 4, to: 1 }]);
const d3 = diffDeckVersions([c("a", 1)], [c("a", 4)]);
check("quantity up", d3.changed, [{ card_id: "a", printing: "Normal", from: 1, to: 4 }]);

// A finish swap is one card out and one in — that is what happened to the
// deck, and collapsing it to "no change" would hide a real decision.
const d4 = diffDeckVersions([c("a", 4)], [c("a", 4, "Cold Foil")]);
check("printing swap is out + in",
  [d4.removed.length, d4.added.length, d4.changed.length], [1, 1, 0]);

const d5 = diffDeckVersions([], [c("a", 4), c("b", 2)]);
check("from empty, everything is added", d5.added.length, 2);
check("from empty, card totals", [d5.fromCount, d5.toCount], [0, 6]);

const d6 = diffDeckVersions([c("a", 4)], []);
check("to empty, everything is removed", d6.removed.length, 1);

check("null inputs don't throw", diffDeckVersions(null, null).isEmpty, true);

// Counts are the header line of the changelog; an off-by-one there reads as a
// broken deck rather than a broken label.
const d7 = diffDeckVersions([c("a", 4), c("b", 2)], [c("a", 2), c("b", 2), c("c", 1)]);
check("counts total quantities, not rows", [d7.fromCount, d7.toCount], [6, 5]);

// Deterministic ordering — the changelog is read top to bottom, and a list
// that reshuffles between renders is unreadable.
const shuffled = diffDeckVersions([], [c("c", 1), c("a", 1), c("b", 1)]);
check("added rows are sorted", shuffled.added.map((x) => x.card_id), ["a", "b", "c"]);

console.log(failed ? NL + failed + " FAILED" : NL + "all passed");
process.exit(failed ? 1 : 0);
