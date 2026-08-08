// test_tournament_deck_names.mjs — guards "a blank tournament deck name stays blank".
//
//     node scripts/test_tournament_deck_names.mjs
//
// The regression this locks down: the three tournament write paths used to
// replace a blank "Deck name" field with a generated string before calling the
// RPC — inks.join("/"), else "<Player>'s deck", else "Untitled deck". Because
// the generated value was PERSISTED, clearing the field and saving appeared to
// do nothing: reopening the edit modal showed it pre-filled again.
//
// It looked server-side (migration 36 really does have the SQL) but 37 dropped
// that signature. The browser was the only thing writing it.
//
// Reads deckDisplayTitle straight out of Index.html so it cannot drift from
// what ships. There is no client-side CI, so this is manual — run it after
// touching TournamentBulkUploadModal / TournamentDeckEditModal /
// TournamentBulkEditModal / deckDisplayTitle.
import { readFileSync } from "node:fs";

const src = readFileSync("C:/Users/zaven/OneDrive/Desktop/Packs.Ink/Index.html", "utf8");

function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("not found: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("end not found for: " + startMarker);
  return src.slice(a, b);
}

const mod = new Function(
  grab("const deckDisplayTitle", "\n// Deck poster export") +
  "\nreturn {deckDisplayTitle};"
)();
const { deckDisplayTitle } = mod;

let fails = 0;
const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fails++; console.log(`  FAIL ${name}\n    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
};
const assert = (name, cond) => {
  if (!cond) { fails++; console.log(`  FAIL ${name}`); }
  else console.log(`  ok   ${name}`);
};

// ── THE REGRESSION: no write path may synthesise a deck name ──
console.log("write paths");
assert("no `<player>'s deck` template survives anywhere",
  !src.includes("'s deck`"));
assert("bulk upload sends a blank name through as null",
  src.includes("deck_name: r.deck_name.trim() || null"));
assert("single add/edit sends a blank name through as null",
  src.includes("const effectiveDeckName = deckName.trim() || null;"));
assert("bulk edit sends a blank name through as null",
  src.includes("const effectiveDeckName = r.deck_name.trim() || null;"));
assert("no write path falls back to the 'Untitled deck' placeholder",
  !/effectiveDeckName\s*=.*"Untitled deck"/.test(src));

// ── display fallback ──
console.log("deckDisplayTitle");
const TC = {tournament_name: "Nerf's Locals", place: "Top 8", player_name: "Nerf"};

eq("real name wins over tournament context",
  deckDisplayTitle({name: "Ruby Sapphire Control"}, TC), "Ruby Sapphire Control");
eq("null name falls back to event + placement",
  deckDisplayTitle({name: null}, TC), "Nerf's Locals — Top 8");
eq("blank name falls back too",
  deckDisplayTitle({name: "   "}, TC), "Nerf's Locals — Top 8");
eq("no placement → event alone",
  deckDisplayTitle({name: null}, {tournament_name: "Nerf's Locals"}), "Nerf's Locals");
eq("no tournament context → neutral placeholder",
  deckDisplayTitle({name: null}, null), "Untitled deck");
eq("missing deck object does not throw",
  deckDisplayTitle(null, null), "Untitled deck");

// The whole point: the player's name must never become the deck's name.
assert("fallback never contains the bare player name as a deck title",
  !deckDisplayTitle({name: null}, TC).endsWith("'s deck"));

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
