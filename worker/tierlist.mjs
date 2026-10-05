// Link previews for packs.ink/tierlist?... (Discord, iMessage, Slack...).
// A tier list link carries the whole list in its query (see the Tier List in
// Index.html), so a preview bot can be told which set and title it is.
//
// ⚠ The preview is deliberately BARE: a title and one short line, no picture.
// A tier list link is nearly always posted beside the copied image of that
// list, and the first version (tier-by-tier names plus a full-size card)
// repeated all of it in a second, bigger block under the message (Zaven,
// 2026-10-05: "remove all this excess"). The link's own picture is the
// exported image the person pastes, not one the preview picks.
//
// ⚠ TIER_SETS must stay identical to MAINLINE_SETS in Index.html — `ts=` is an
// index into it. scripts/test_tier_list.mjs checks the two lists agree and
// that this decoder reads the client's own codes.

export const TIER_SETS = [
  "The First Chapter", "Rise of the Floodborn", "Into the Inklands",
  "Ursula's Return", "Shimmering Skies", "Azurite Sea", "Archazia's Island",
  "Reign of Jafar", "Fabled", "Whispers in the Well", "Winterspell",
  "Wilds Unknown", "Attack of the Vine!", "Hyperia City",
];
const DEFAULT_LABELS = ["S", "A", "B", "C", "D"];

// A code is "<base>-<tiers>" (offsets from collector number <base>, one
// base-36 character a card, tiers split by "."), or a bare "<tiers>" from the
// first day, read against the set's first chase card. Returns tiers of
// collector NUMBERS.
export function tierDecodeNums(code, firstNum) {
  const tiers = DEFAULT_LABELS.map(() => []);
  if (!code) return tiers;
  const m = /^(\d{1,4})-(.*)$/.exec(String(code));
  const base = m ? Number(m[1]) : firstNum;
  if (!Number.isFinite(base)) return tiers;
  const seen = new Set();
  (m ? m[2] : String(code)).split(".").slice(0, tiers.length).forEach((grp, i) => {
    for (const ch of grp) {
      const off = parseInt(ch, 36);
      if (!Number.isFinite(off)) continue;
      const n = base + off;
      if (!seen.has(n)) { seen.add(n); tiers[i].push(n); }
    }
  });
  return tiers;
}

// `rows` = the set's chase cards: {collector_number, rarity,
// tcgplayer_product_id}. Pure, so it is testable.
export function tierPreviewFrom(search, rows) {
  const q = new URLSearchParams(search);
  const si = parseInt(q.get("ts") || "", 10);
  const set = si >= 1 && si <= TIER_SETS.length ? TIER_SETS[si - 1] : null;
  if (!set) return null;
  const byNum = new Map();
  for (const r of rows || []) {
    const n = parseInt(String(r.collector_number || "").split("/")[0], 10);
    if (!Number.isFinite(n)) continue;
    const prev = byNum.get(n);
    if (!prev || (!prev.tcgplayer_product_id && r.tcgplayer_product_id)) byNum.set(n, r);
  }
  const nums = [...byNum.keys()].sort((a, b) => a - b);
  const tiers = tierDecodeNums(q.get("tl") || "", nums[0]);
  const ranked = tiers.flat().filter((n) => byNum.has(n)).length;
  // Site name ("Packs.Ink") is already shown above the title by every app
  // that draws one, so the title does not repeat it.
  const title = (q.get("tn") || "").slice(0, 60) || `${set} Chase Card Tier List`;
  const ench = [...byNum.values()].filter((r) => r.rarity === "Enchanted").length;
  const icon = [...byNum.values()].filter((r) => r.rarity === "Iconic").length;
  const count = `${ench} Enchanted${icon ? ` · ${icon} Iconic` : ""}`;
  const desc = ranked
    ? `${count} · make your own at packs.ink/tierlist`
    : `Rank ${set}'s ${ench} Enchanted${icon ? ` and ${icon} Iconic` : ""} cards and share the picture.`;
  return {
    title,
    desc,
    bare: true,
    url: "https://packs.ink/tierlist" + (search && search !== "?" ? search : ""),
  };
}

export async function tierPreview(search, sbGet) {
  const q = new URLSearchParams(search);
  const si = parseInt(q.get("ts") || "", 10);
  const set = si >= 1 && si <= TIER_SETS.length ? TIER_SETS[si - 1] : null;
  if (!set) return null;
  const rows = await sbGet(
    "cards?select=collector_number,rarity,tcgplayer_product_id,sets!inner(name)"
    + `&sets.name=eq.${encodeURIComponent(set)}&rarity=in.(Enchanted,Iconic)&limit=60`);
  return tierPreviewFrom(search, rows);
}
