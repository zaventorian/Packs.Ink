// text.js — normalisation and edit distance for the resolver.
//
// Deliberately NOT the site's searchNorm: that one feeds a FILTER, where an
// exact substring is the contract. This feeds a resolver that has to forgive
// "mogli" and "stich", so it folds harder (every non-alphanumeric becomes a
// space) and leaves the forgiving to dl() below.

const MARKS = /[̀-ͯ]/g;

// "Te Kā" -> "te ka", "Andy's Room" -> "andys room", "Hunny, Why Aren't…" ->
// "hunny why arent". Apostrophes are DROPPED rather than spaced so a possessive
// stays one token, which is how people type it ("ursulas return").
export function norm(s) {
  return String(s || "")
    .normalize("NFKD").replace(MARKS, "")
    .toLowerCase()
    .replace(/[‘’ʼ`´']/g, "")
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export const tokens = (s) => {
  const n = norm(s);
  return n ? n.split(" ") : [];
};

// Optimal-string-alignment Damerau-Levenshtein, bounded: returns max+1 as soon
// as the answer is known to exceed max. A transposition ("rapunzle") costs 1,
// which is the single most common typo in a name typed from memory.
export function dl(a, b, max) {
  const la = a.length, lb = b.length;
  if (Math.abs(la - lb) > max) return max + 1;
  if (a === b) return 0;
  let prev2 = null;
  let prev = new Array(lb + 1);
  for (let j = 0; j <= lb; j++) prev[j] = j;
  for (let i = 1; i <= la; i++) {
    const cur = new Array(lb + 1);
    cur[0] = i;
    let rowMin = cur[0];
    const ca = a.charCodeAt(i - 1);
    for (let j = 1; j <= lb; j++) {
      const cb = b.charCodeAt(j - 1);
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca === cb ? 0 : 1));
      if (prev2 && i > 1 && j > 1 && ca === b.charCodeAt(j - 2) && a.charCodeAt(i - 2) === cb) {
        v = Math.min(v, prev2[j - 2] + 1);
      }
      cur[j] = v;
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > max) return max + 1;
    prev2 = prev;
    prev = cur;
  }
  return prev[lb] <= max ? prev[lb] : max + 1;
}

// Words that carry no identity at all. Removed outright on the first pass;
// the resolver retries with them kept, because a few are genuinely card-name
// words ("Card Soldiers", "Market" in a location name) and removal must never
// be the thing that makes a real name unfindable.
export const FILLER = new Set((
  "how much whats what worth price prices priced pricing value values valued cost costs costing " +
  "going goes currently current rn today now right card cards lorcana disney tcg tcgplayer tcgp " +
  "pc check checking show lookup look find get please pls plz thanks thx thank hey yo hi hello " +
  "bot packs packsink anyone anybody someone know does do did can could would should sell selling " +
  "sold buy buying bought market mkt avg average about like these those some any ones copy copies " +
  "version ver same guys lol ok okay are was were been have has had got gonna wanna want need needs " +
  "looking trade trading tell me pull pulled open opened hit worthit really actually just still " +
  "cheapest cheap expensive set sets"
).split(/\s+/));

// Words that DO occur in card names but say almost nothing about which card
// ("Let It Go", "A Whole New World"). Kept as name tokens at a tiny weight.
export const STOP = new Set((
  "the a an of to in on and for with at from by is it its be as or up out all no not so go " +
  "my your our me you we i this that into over under one his her their who"
).split(/\s+/));
