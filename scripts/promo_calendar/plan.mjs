/* The shot list for the desktop cut, authored against the MARKS capture.mjs
 * writes (promo/calendar/clips/<clip>.marks.json): every time and box below is
 * "the moment X happened" / "where X was on screen", not a hand-typed guess,
 * so re-recording shifts the edit with it.
 *
 * A shot is built from `segs` — [clipFrom, clipTo, speed] — which becomes a
 * piecewise speed ramp: waits run 2-4x, the payoff runs near 1x. `at(clipT)`
 * converts a clip time to this shot's output time, so cameras and callouts
 * are keyed to marks too.
 *
 * Clip px: desktop clips are 2880x1800 (1440x900 CSS at 2x). */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLIPS = path.resolve(HERE, "..", "..", "promo", "calendar", "clips");
const MK = {};
const marks = (c) => (MK[c] ||= JSON.parse(fs.readFileSync(path.join(CLIPS, c + ".marks.json"), "utf8")));
const M = (c, n) => { const m = marks(c).find((x) => x.name === n); if (!m) throw new Error(`no mark ${c}.${n}`); return m; };
const T = (c, n) => M(c, n).t;
const R = (c, n, grow = {}) => { const r = M(c, n).r; if (!r) throw new Error(`no box ${c}.${n}`);
  return { x: r.x + (grow.x || 0), y: r.y + (grow.y || 0), w: r.w + (grow.w || 0), h: r.h + (grow.h || 0) }; };
const ctr = (r, w, dx = 0, dy = 0) => [r.x + r.w / 2 + dx, r.y + r.h / 2 + dy, w];

/* Global pace. Every speed in the list is multiplied by this, so the whole
 * cut can be made snappier or calmer in one place. */
const PACE = 1.08;
function shot(clip, segs, build) {
  const map = [];
  let o = 0;
  for (const [a, b, sp] of segs) {
    if (!map.length) map.push([0, a]);
    o += (b - a) / (sp * PACE);
    map.push([+o.toFixed(4), b]);
  }
  const at = (ct) => {
    for (let i = 1; i < map.length; i++) {
      const [o0, c0] = map[i - 1], [o1, c1] = map[i];
      if (ct <= c1) return Math.max(0, o0 + ((ct - c0) / (c1 - c0 || 1)) * (o1 - o0));
    }
    return map[map.length - 1][0];
  };
  const extra = build ? build(at, o) : {};
  if (extra.cam) extra.cam = extra.cam.map(([t, v]) => [t === "end" ? o : t, ...v]);
  return { clip, map, dur: +o.toFixed(4), ...extra };
}
const call = (from, to, r, label, side = "below", more = {}) => ({ from, to, r, label, side, ...more });

const CH = ["At a glance", "Four views", "Go local", "Plan the season", "Find anything", "Every event", "Yours"];
const FULL = [1440, 900, 2300];

const D = [];
// ── 0 · hook ───────────────────────────────────────────────────────────────
D.push({ card: { kind: "hook", per: 0.55, lines: ["Every set release.", "Every Challenge.", "Every Set Champ near you."] }, dur: 3.4 });

// ── 1 · glance: the home tile ─────────────────────────────────────────────
{
  const c = "c_home", tile = R(c, "tile");
  D.push(shot(c, [[0.6, 2.4, 2.2], [2.4, 5.2, 1.15], [5.2, 6.4, 3], [6.4, 8.4, 1.3], [8.4, 11.9, 2.8], [11.9, 13.6, 1.2]], (at, end) => ({
    ch: 0, url: "/",
    cam: [[0, [1440, 800, 2880]], [at(2.3), ctr(tile, 1500, -160, 60)], [at(6.4), ctr(tile, 1500, -160, 60)], [at(8.0), ctr(tile, 1500, -160, 160)], ["end", ctr(tile, 1500, -160, 180)]],
    calls: [
      call(at(T(c, "group") + 0.1), at(5.1), R(c, "group"), "Busy day? It folds to one mark", "above", { dim: false }),
      call(at(T(c, "flip") - 0.1), at(7.8), R(c, "flip"), "Flip to a list", "below"),
      call(at(T(c, "page") - 0.1), end - 0.05, R(c, "page"), "Page through the season", "below"),
    ],
    cap: { chapter: "01 · At a glance", title: "Right on the home page", sub: "Hover any day for the details." },
  })));
}

// ── 2 · four views ─────────────────────────────────────────────────────────
{
  const c = "c_views";
  D.push(shot(c, [[1.0, 2.2, 2], [2.2, 3.4, 1.3], [3.4, 5.1, 3], [5.1, 6.6, 1.3], [6.6, 8.2, 3], [8.2, 10.6, 1.3]], (at, end) => ({
    ch: 1, url: "/calendar", cam: [[0, FULL]],
    calls: [
      call(0.05, at(2.3), R(c, "list", { x: 150, w: 20 }), "Month", "above", { dim: false }),
      call(at(T(c, "list") - 0.05), at(5.1), R(c, "list"), "List", "above", { dim: false }),
      call(at(T(c, "timeline") + 0.35), at(8.1), R(c, "timelineAfter"), "Timeline", "above", { dim: false }),
      call(at(T(c, "map") + 0.35), end - 0.05, R(c, "mapAfter"), "Map", "above", { dim: false }),
    ],
    cap: { chapter: "02 · Four views", title: "Month · List · Timeline · Map" },
  })));
}

// ── 3 · go local (the centrepiece) ────────────────────────────────────────
{
  const c = "c_local", fin = R(c, "finder"), chip = R(c, "nearChip");
  const L = (title, sub) => ({ chapter: "03 · Go local", title, sub, right: true });
  const FIN = (dy, w = 1750) => ctr(fin, w, 0, dy);
  // a · the chip opens the finder
  D.push(shot(c, [[1.2, 2.9, 1.2], [2.9, 4.5, 1.6]], (at) => ({
    ch: 2, url: "/calendar",
    cam: [[0, [1440, 800, 2500]], [at(2.3), ctr(chip, 1900, 0, -40)], [at(3.6), FIN(260)], ["end", FIN(260)]],
    calls: [call(at(T(c, "nearChip") - 0.1), at(3.1), chip, "SCs near me", "below")],
    cap: L("Find events near you", "Tap SCs near me to open the event finder."),
  })));
  // b · type a town
  D.push(shot(c, [[5.4, 7.3, 1.9], [7.3, 8.5, 1.3], [8.5, 11.1, 2.6]], (at) => ({
    ch: 2, url: "/calendar", cont: true,
    cam: [[0, FIN(260)], [at(9.6), FIN(260)], ["end", FIN(560)]],
    calls: [call(0.05, at(7.5), R(c, "zip"), "ZIP or town", "below"), call(at(T(c, "search")), at(8.7), R(c, "search"), null)],
    cap: L("Type your town", "Every Lorcana event near you, straight from Ravensburger Play."),
  })));
  // c · set champs
  D.push(shot(c, [[11.1, 13.4, 1.05]], (at, end) => ({
    ch: 2, url: "/calendar", cont: true, cam: [[0, FIN(560)]],
    calls: [call(0.1, end - 0.05, { x: 844, y: 130, w: 200, h: 55 }, null, "below", { dim: false }),
      call(0.25, end - 0.05, R(c, "scTile"), "Set Championship near you", "above")],
    cap: L("Set Champs", "The shops near you running one — and when."),
  })));
  // d · prereleases
  D.push(shot(c, [[14.2, 15.6, 1.3], [15.6, 17.4, 2.6], [17.4, 19.4, 1.1]], (at, end) => ({
    ch: 2, url: "/calendar", cont: true, cam: [[0, FIN(560)], [at(16.6), FIN(820)], ["end", FIN(820)]],
    calls: [call(at(T(c, "modePre") - 0.1), end - 0.05, R(c, "modePre"), "+ Prereleases", "below", { dim: false })],
    cap: L("Prereleases", "Hyperia City weekends at every shop around you."),
  })));
  // e · locals, and a weekly collapsed to one row
  D.push(shot(c, [[20.0, 21.6, 1.3], [21.6, 23.5, 2.6], [23.5, 26.6, 1.1]], (at, end) => ({
    ch: 2, url: "/calendar", cont: true, cam: [[0, FIN(560)], [at(23.4), FIN(640)], ["end", FIN(640)]],
    calls: [
      call(at(T(c, "modeLocals") - 0.1), at(22.6), R(c, "modeLocals"), "+ Locals", "below", { dim: false }),
      call(at(T(c, "series") - 0.1), at(25.0), R(c, "series"), "A weekly night is one row", "below"),
      call(at(25.2), end - 0.05, R(c, "seriesOpen"), "…tap for every date", "below", { dim: false }),
    ],
    cap: L("Weekly locals", "League nights and drafts — one row per weekly."),
  })));
  // f · follow the store
  const pop = R(c, "popDone");
  D.push(shot(c, [[28.8, 30.8, 2.4], [30.8, 31.8, 2.4], [31.8, 34.2, 1.25], [34.2, 35.9, 1.15], [35.9, 36.8, 2.2], [36.8, 39.2, 1.1]], (at, end) => ({
    ch: 2, url: "/calendar",
    cam: [[0, FIN(620)], [at(32.2), FIN(620)], [at(33.4), ctr(pop, 1500, -250, 40)], ["end", ctr(pop, 1500, -250, 40)]],
    calls: [
      call(at(T(c, "addBtn") - 0.1), at(33.2), R(c, "addBtn"), "Add to calendar", "left"),
      call(at(T(c, "follow") - 0.1), at(36.6), R(c, "follow"), "Follow this store", "left"),
      call(at(T(c, "untick") - 0.1), end - 0.05, R(c, "untick"), "Skip the weeklies", "left"),
    ],
    cap: L("Follow your store", "Every event it runs lands on your calendar — you pick which."),
  })));
  // g · the finder's map
  D.push(shot(c, [[41.9, 43.4, 1.3], [43.4, 46.8, 2.3]], (at) => ({
    ch: 2, url: "/calendar", cam: [[0, FIN(560, 1900)], [at(43.6), FIN(900, 1900)], ["end", FIN(900, 1900)]],
    calls: [call(at(T(c, "finderMap") - 0.1), at(43.4), R(c, "finderMap"), "Map", "below")],
    cap: L("…or on a map"),
  })));
  // h · back on the calendar
  D.push(shot(c, [[51.6, 52.8, 1.2], [52.8, 53.3, 2], [53.3, 55.2, 1.3], [55.2, 56.3, 2.4], [56.3, 60.6, 1.2]], (at) => ({
    ch: 2, url: "/calendar",
    cam: [[0, [1440, 780, 2300]], [at(56.8), [1440, 780, 2300]], [at(57.8), [1440, 1150, 2250]], ["end", [1440, 1150, 2250]]],
    calls: [
      call(0.15, at(52.9), R(c, "myStoresChip"), "Your store — already on", "below"),
      call(at(T(c, "nearOn") - 0.1), at(55.4), R(c, "nearOn"), "+ every SC within 50 mi", "below"),
    ],
    cap: L("Now it's on your calendar", "Your store's Set Champ and prerelease, right on the month."),
  })));
  // i · the calendar's own map, zoomed to town
  {
    const m = "c_map";
    D.push(shot(m, [[1.0, 2.4, 1.3], [2.4, 4.0, 3], [4.0, 5.6, 1.9], [5.6, 7.0, 1.3], [7.0, 10.3, 2.6], [10.3, 11.3, 1.2], [11.3, 12.0, 1.3], [12.0, 15.1, 2.6], [15.1, 16.9, 1.3], [16.9, 18.4, 2.6], [18.4, 20.8, 1.1]], (at, end) => ({
      ch: 2, url: "/calendar?cv=map",
      cam: [[0, [1440, 1150, 2350]]],
      calls: [
        call(at(T(m, "place")), at(5.8), R(m, "place"), "Type a town", "below"),
        call(at(T(m, "zoomGo") - 0.1), at(7.2), R(m, "zoomGo"), null),
        call(at(T(m, "mapLocalsOff") - 0.1), at(17.0), R(m, "mapLocalsOff"), "Filter by kind", "below"),
        call(at(T(m, "pin") - 0.1), end - 0.05, R(m, "pin"), "Every pin is dated", "above"),
      ],
      cap: L("Every event, on a map", "Zoom to your town and it all appears."),
    })));
  }
}

// ── 4 · plan the season ───────────────────────────────────────────────────
{
  const c = "c_timeline";
  D.push(shot(c, [[0.8, 2.8, 1.7], [2.8, 4.6, 1.2], [4.6, 5.3, 2], [5.3, 7.4, 1.2], [7.4, 8.7, 2.6], [8.7, 10.8, 1.2], [10.8, 12.2, 3], [12.2, 14.4, 1.2]], (at) => ({
    ch: 3, url: "/calendar?cv=timeline",
    cam: [[0, [1440, 1150, 2650]], [at(8.6), [1440, 1150, 2650]], [at(10.0), [1440, 1200, 2750]], ["end", [1440, 1200, 2750]]],
    calls: [
      call(at(T(c, "byRegion") - 0.1), at(7.4), R(c, "byRegion"), "By region", "below", { dim: false }),
      call(at(T(c, "span24") - 0.1), at(10.8), R(c, "span24"), "Up to 24 months", "below", { dim: false }),
    ],
    cap: { chapter: "04 · Plan the season", title: "The whole season on one line", sub: "Challenges, qualifiers and set releases — spot the gaps before you book travel." },
  })));
}

// ── 5 · find anything ─────────────────────────────────────────────────────
{
  const c = "c_filter", d = R(c, "chipDlc"), q = R(c, "chipCcq");
  D.push(shot(c, [[1.7, 3.5, 1.3], [3.5, 4.6, 2.2], [4.6, 6.2, 1.3], [6.2, 11.2, 4.5], [11.2, 13.0, 1.7], [13.0, 15.4, 1.2]], (at, end) => ({
    ch: 4, url: "/calendar?cv=list", cam: [[0, [1440, 900, 2300]]],
    calls: [
      call(at(T(c, "chipDlc") - 0.1), at(6.0), { x: d.x, y: d.y, w: q.x + q.w - d.x, h: d.h }, "Show or hide each kind", "below"),
      call(at(T(c, "search") - 0.05), end - 0.05, R(c, "search"), "Search events, stores, cities", "below"),
    ],
    cap: { chapter: "05 · Find anything", title: "Filter. Search. Done.", right: true },
  })));
}

// ── 6 · every event ───────────────────────────────────────────────────────
{
  const c = "c_detail", modal = R(c, "modal");
  D.push(shot(c, [[4.4, 6.2, 2.2], [6.2, 7.4, 1.3], [7.4, 8.6, 2], [8.6, 11.4, 1.1], [11.4, 12.6, 2.2], [12.6, 15.0, 1.15]], (at, end) => ({
    ch: 5, url: "/calendar",
    cam: [[0, [1440, 900, 2300]], [at(7.6), [1440, 900, 2300]], [at(8.6), ctr(modal, 1900, 0, -170)], [at(11.6), ctr(modal, 1900, 0, -170)], [at(12.7), ctr(modal, 1900, 0, 230)], ["end", ctr(modal, 1900, 0, 230)]],
    calls: [
      call(at(T(c, "row") - 0.1), at(6.7), R(c, "row"), null),
      call(at(9.0), at(11.5), R(c, "products", { h: 300 }), "What's out that day — with prices", "right", { dim: false }),
      call(at(T(c, "add") - 0.1), end - 0.05, R(c, "add"), "Add to my calendar", "right"),
    ],
    cap: { chapter: "06 · Every event", title: "Everything about the day", sub: "Dates, countdown, venue and map — plus Google Calendar and .ics in one tap." },
  })));
}

// ── 7 · yours ─────────────────────────────────────────────────────────────
{
  const c = "c_mine";
  D.push(shot(c, [[1.4, 3.0, 1.3], [3.0, 5.0, 1.4], [5.0, 7.6, 1.2]], (at, end) => ({
    ch: 6, url: "/calendar", cam: [[0, [1440, 700, 2300]], [at(3.0), [1440, 900, 2300]], ["end", [1440, 900, 2300]]],
    calls: [
      call(at(T(c, "drawer") - 0.1), at(3.0), R(c, "drawer"), null),
      call(at(3.1), at(5.2), R(c, "drawerBody"), "Your stores, and which events you want", "above", { dim: false }),
      call(at(T(c, "export") - 0.05), end - 0.05, R(c, "export"), "Export to any calendar app", "below"),
    ],
    cap: { chapter: "07 · Yours", title: "Your stores, your season", sub: "Follow, save, hide — then send it to your phone's calendar." },
  })));
  D.push(shot("c_phone", [[0.6, 8.6, 2.2]], () => ({
    ch: 6, phone: true, cap: { chapter: "07 · Yours", title: "…and in your pocket", right: true },
  })));
}

// ── CTA ───────────────────────────────────────────────────────────────────
D.push({ card: { big: "Lorcana <span class='gold'>Calendar</span>", url: "packs.ink/calendar" }, dur: 3.4 });

function finalize(shots) {
  let at = 0;
  for (const s of shots) { s.at = +at.toFixed(4); at += s.dur; }
  return { shots, total: +at.toFixed(3), chapters: CH };
}
export const PLANS = { desktop: finalize(D) };
