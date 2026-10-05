// Link previews for packs.ink/tierlist?... (Discord, iMessage, Slack...).
// A tier list link carries the whole list in its query (see the Tier List in
// Index.html), so a preview bot can be told what is in it without any table:
// the set, the title, which cards sit in which tier, and the top card's art.
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

export function tierLabels(tt) {
  if (!tt) return DEFAULT_LABELS.slice();
  const parts = String(tt).split("_").slice(0, DEFAULT_LABELS.length).map((x) => x.trim().slice(0, 12));
  return DEFAULT_LABELS.map((d, i) => parts[i] || d);
}

const clip = (s, n) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);

// `rows` = the set's chase cards: {name, version, collector_number, rarity,
// image_large, image_normal, tcgplayer_product_id}. Pure, so it is testable.
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
  const labels = tierLabels(q.get("tt"));
  const title = (q.get("tn") || "").slice(0, 60) || `${set} Chase Card Tier List`;
  const lines = [];
  tiers.forEach((t, i) => {
    const names = t.map((n) => byNum.get(n)).filter(Boolean).map((r) => r.name);
    if (names.length) lines.push(`${labels[i]}: ${names.join(", ")}`);
  });
  const ench = [...byNum.values()].filter((r) => r.rarity === "Enchanted").length;
  const icon = [...byNum.values()].filter((r) => r.rarity === "Iconic").length;
  const desc = lines.length
    ? clip(lines.join(" · "), 280)
    : `Rank ${set}'s ${ench} Enchanted${icon ? ` and ${icon} Iconic` : ""} cards and share the picture.`;
  // The top-ranked card is the picture. Only formats every preview bot draws:
  // TCGplayer's JPEG when the card is listed, or our own JPEG/PNG/WebP art.
  // Otherwise the site's own preview image stays.
  // The highest-ranked card that HAS such a picture wins: an unreleased
  // Lorcast card is AVIF only, and skipping it beats losing the art entirely.
  let image = null, w = 0, h = 0;
  for (const r of tiers.flat().map((n) => byNum.get(n)).filter(Boolean)) {
    if (r.tcgplayer_product_id) {
      image = `https://tcgplayer-cdn.tcgplayer.com/product/${r.tcgplayer_product_id}_in_1000x1000.jpg`; w = 1000; h = 1000;
      break;
    }
    const src = r.image_large || r.image_normal || "";
    if (/\.(jpe?g|png|webp)(\?|$)/i.test(src)) { image = src; w = 734; h = 1024; break; }
  }
  return {
    title: title + " | Packs.Ink",
    desc,
    image, w, h,
    url: "https://packs.ink/tierlist" + (search && search !== "?" ? search : ""),
  };
}

export async function tierPreview(search, sbGet) {
  const q = new URLSearchParams(search);
  const si = parseInt(q.get("ts") || "", 10);
  const set = si >= 1 && si <= TIER_SETS.length ? TIER_SETS[si - 1] : null;
  if (!set) return null;
  const rows = await sbGet(
    "cards?select=name,version,collector_number,rarity,image_large,image_normal,tcgplayer_product_id,sets!inner(name)"
    + `&sets.name=eq.${encodeURIComponent(set)}&rarity=in.(Enchanted,Iconic)&limit=60`);
  return tierPreviewFrom(search, rows);
}
