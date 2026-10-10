// kaylee.js — a joke. /kaylee shows Kaylee's "season stats" and a button that
// opens an Attack of the Vine! pack that ALWAYS holds an Enchanted. The stats
// are invented; the pack is the real simulator with one slot rigged. Temporary:
// delete this file, its command, and the two hooks in interactions.js to retire.
import { openPacks, packMessage, packPools } from "./set.js";

export const KAYLEE_ID = "kay|1";
export const isKayleeId = (id) => id === KAYLEE_ID;

const SET_QUERY = "attack of the vine";

export function kayleeStats() {
  return {
    embeds: [{
      title: "Kaylee's season stats",
      color: 0xc77dff,
      description: "**101** packs opened\n**13** Enchanteds pulled\n\n13% Enchanted rate. The rest of us are at about 1 in 72 (1.4%).\n*Are you kidding me??*",
      footer: { text: "Statistics are 100% real and not at all rigged" },
    }],
    components: [{ type: 1, components: [{ type: 2, style: 1, label: "Open a Kaylee pack", custom_id: KAYLEE_ID }] }],
  };
}

// A normal pack from the set, with its foil slot swapped for an Enchanted when
// the roll didn't already hold one.
export function kayleePack(R, index, origin, opener) {
  const si = R.resolveSet(SET_QUERY);
  if (si < 0) return { content: "Kaylee's pack isn't available right now.", embeds: [], components: [] };
  const result = openPacks(R, si, 1);
  if (!result.pulls.some((e) => e.p.r === "Enchanted")) {
    const enc = packPools(R, si).enc;
    if (enc.length) {
      const pick = enc[Math.floor(Math.random() * enc.length)];
      const isFoil = (e) => e.p.r === "Epic" || e.p.r === "Iconic" || ((e.p.f[e.fi] || [])[0] || "N") !== "N";
      let at = result.pulls.findIndex(isFoil);
      if (at < 0) at = result.pulls.length - 1;
      result.pulls[at] = { ...pick, pack: 0 };
      result.total = result.pulls.reduce((s, e) => s + (e.price || 0), 0);
    }
  }
  const m = packMessage(R, index, si, result, { origin, who: "Kaylee" });
  // The buttons that came with it open ordinary packs; this one only opens hers.
  const rows = m.components.slice(0, 1);
  rows.push({ type: 1, components: [{ type: 2, style: 1, label: "Open another Kaylee pack", custom_id: KAYLEE_ID }] });
  // Discord labels a button reply with the app, not the person, so say who pressed it.
  const who = String(opener || "").slice(0, 32).replace(/[*_~`|>\\]/g, "\\$&");
  return { ...m, ...(who ? { content: `${who} opened Kaylee's pack:` } : {}), components: rows };
}
