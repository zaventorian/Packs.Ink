// test_event_map.mjs — guards the multi-pin map's geometry.
//
//     node scripts/test_event_map.mjs
//
// Extracts the real functions out of Index.html, house pattern, so they cannot
// drift from what ships.
//
// Every case below is a SILENT failure. A map with a bad centre or zoom still
// renders a perfectly good picture of the wrong part of the world, and a pin
// whose index has drifted opens the wrong event while looking entirely normal.
// None of it throws, and none of it is visible in a screenshot unless you
// already know where the events were supposed to be.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const NL = String.fromCharCode(10);
const grab = (a, b) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error("missing marker: " + a);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error("missing end: " + b);
  return src.slice(i, j + b.length);
};
const grabLine = (p) => {
  const l = src.split(/\r?\n/).find((x) => x.startsWith(p));
  if (!l) throw new Error("missing line: " + p);
  return l;
};

const mod = await import("data:text/javascript," + encodeURIComponent([
  grabLine("const OSM_TILE_PX = "),
  grabLine("const OSM_LAT_MAX = "),
  grab("const osmWorldFrac = (lat, lng) => {", NL + "};"),
  grabLine("const osmFracLat = "),
  grab("const osmTileLayout = (lat, lng, zoom, w, h) => {", NL + "};"),
  grabLine("const OSM_FIT_PAD = "),
  grab("const osmFitLayout = (points, w, h, opts) => {", NL + "};"),
  grabLine("const SC_PIN_MERGE_PX = "),
  grab("const scMergePins = (pins) => {", NL + "};"),
  grabLine("const SC_PIN_R = "),
  grabLine("const SC_LBL_GAP = "),
  grabLine("const SC_LBL_H = "),
  grabLine("const SC_LBL_PAD = "),
  grabLine("const SC_LBL_CHAR = "),
  grabLine("const SC_LBL_BLEED = "),
  grab("const scLabelW = (text) => {", NL + "};"),
  grabLine("const SC_PIN_MIN_W = "),
  grab("const scPinR = (count) => {", NL + "};"),
  grab("const scPanCenter = (center, zoom, dx, dy) => {", NL + "};"),
  grabLine("const _scBoxHit = "),
  grab("const scPlacePinLabels = (pins, w, h) => {", NL + "};"),
  grabLine("const CAL_MAP_FOCUS_Z = "),
  grabLine("const CAL_MAP_ANY_LABEL = "),
  grabLine("const CAL_MAP_LABEL_MAX = "),
  grab("const calParseMapFocus = (raw) => {", NL + "};"),
  grab("const calMapFocusParam = (f) => {", NL + "};"),
  "export {osmWorldFrac, osmFracLat, osmTileLayout, osmFitLayout, OSM_FIT_PAD,"
  + " scMergePins, SC_PIN_MERGE_PX, scLabelW, scPlacePinLabels,"
  + " SC_PIN_R, SC_LBL_GAP, SC_LBL_H, scPinR, scPanCenter,"
  + " calParseMapFocus, calMapFocusParam, CAL_MAP_ANY_LABEL,"
  + " CAL_MAP_FOCUS_MIN, CAL_MAP_FOCUS_MAX, CAL_MAP_LABEL_MAX};",
].join(NL)));

const { osmWorldFrac, osmFracLat, osmTileLayout, osmFitLayout, OSM_FIT_PAD,
        scMergePins, SC_PIN_MERGE_PX, scLabelW, scPlacePinLabels,
        SC_PIN_R, SC_LBL_GAP, SC_LBL_H, scPinR, scPanCenter,
        calParseMapFocus, calMapFocusParam, CAL_MAP_ANY_LABEL,
        CAL_MAP_FOCUS_MIN, CAL_MAP_FOCUS_MAX, CAL_MAP_LABEL_MAX } = mod;

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) { pass++; } else { fail++; console.log("  FAIL: " + msg); } };
const near = (a, b, eps, msg) => ok(Math.abs(a - b) <= eps, msg + " (got " + a + ", want ~" + b + ")");
const section = (s) => console.log("\n" + s);

const W = 600, H = 360;
const P = (lat, lng) => ({ lat, lng });

// 1. The projection itself
section("1. osmWorldFrac / osmFracLat");
{
  const nullIsland = osmWorldFrac(0, 0);
  near(nullIsland.fx, 0.5, 1e-12, "lng 0 is half way across the world");
  near(nullIsland.fy, 0.5, 1e-12, "lat 0 is half way down the world");
  near(osmWorldFrac(0, -180).fx, 0, 1e-12, "lng -180 is the west edge");
  near(osmWorldFrac(0, 180).fx, 1, 1e-12, "lng 180 is the east edge");
  ok(osmWorldFrac(85, 0).fy < osmWorldFrac(-85, 0).fy, "north is above south");
  // The clamp is what stops a pole becoming Infinity and taking the whole map
  // with it — Mercator has no north pole.
  ok(isFinite(osmWorldFrac(90, 0).fy), "lat 90 is clamped, not Infinity");
  ok(isFinite(osmWorldFrac(-90, 0).fy), "lat -90 is clamped, not Infinity");
  // Round trip: the fit turns a projected centre back into a latitude.
  for (const lat of [-72, -33.9, 0, 21.3, 51.5, 78]) {
    near(osmFracLat(osmWorldFrac(lat, 0).fy), lat, 1e-9, "round trip lat " + lat);
  }
}

// 2. osmTileLayout still behaves as it always did
section("2. osmTileLayout (regression — it was refactored onto osmWorldFrac)");
{
  const l = osmTileLayout(41.88, -87.63, 11, W, H);
  ok(l !== null, "Chicago at z11 produces a layout");
  ok(l.pinLeft === W / 2 && l.pinTop === H / 2, "the single pin is the box centre");
  ok(l.zoom === 11, "zoom is honoured");
  ok(l.tiles.length > 0, "tiles cover the box");
  ok(typeof l.originX === "number" && typeof l.originY === "number",
     "originX/originY are exposed for callers placing their own pins");
  // Every tile index must be a real tile at that zoom, or the CDN 404s and the
  // map renders as holes.
  const n = Math.pow(2, l.zoom);
  ok(l.tiles.every((t) => t.x >= 0 && t.x < n && t.y >= 0 && t.y < n),
     "every tile index is inside the world");
  ok(osmTileLayout(NaN, 0, 11, W, H) === null, "NaN latitude is refused");
  ok(osmTileLayout(0, undefined, 11, W, H) === null, "missing longitude is refused");
  // x WRAPS at the antimeridian; y is clamped (there is no tile above the pole).
  const edge = osmTileLayout(0, 179.99, 6, W, H);
  ok(edge.tiles.every((t) => t.x >= 0 && t.x < Math.pow(2, 6)),
     "a box straddling the antimeridian still asks for real tile indices");
  const pole = osmTileLayout(85, 0, 3, W, H);
  ok(pole.tiles.every((t) => t.y >= 0 && t.y < Math.pow(2, 3)),
     "a box at the pole does not ask for a tile above the world");
}

// 3. The fit's core promise: every pin is actually on the map
section("3. osmFitLayout — every pin lands inside the box");
{
  const chicagoland = [
    P(41.88, -87.63), P(42.05, -87.68), P(41.52, -88.08),
    P(41.76, -88.32), P(42.34, -87.95), P(41.30, -87.85),
  ];
  const l = osmFitLayout(chicagoland, W, H);
  ok(l !== null, "a real cluster produces a layout");
  ok(l.pins.length === chicagoland.length, "one pin per point");
  ok(l.pins.every((p) => p.left >= 0 && p.left <= W && p.top >= 0 && p.top <= H),
     "every pin is inside the box");
  // Stronger: inside the PADDED box, so no pin is half-clipped by the edge.
  ok(l.pins.every((p) =>
       p.left >= OSM_FIT_PAD - 1 && p.left <= W - OSM_FIT_PAD + 1 &&
       p.top >= OSM_FIT_PAD - 1 && p.top <= H - OSM_FIT_PAD + 1),
     "every pin clears the padding, so none is clipped by the edge");
}

// 4. The centre is the BOUNDING BOX's, not the mean
section("4. one outlier is not averaged away");
{
  // Twenty events in one town and a single one far north. A mean centre sits
  // almost on top of the cluster and pushes the outlier off the map — and the
  // outlier is usually the whole reason someone opened a map.
  const pts = [];
  for (let i = 0; i < 20; i++) pts.push(P(41.88 + i * 0.001, -87.63 + i * 0.001));
  pts.push(P(45.5, -87.0));
  const l = osmFitLayout(pts, W, H);
  ok(l.pins.every((p) => p.top >= 0 && p.top <= H), "the outlier is still on the map");
  ok(Math.abs(l.center.lat - (41.88 + 45.5) / 2) < 0.6,
     "centre is between the extremes, not on the cluster (got " + l.center.lat.toFixed(2) + ")");
}

// 5. Latitude is centred in PROJECTED space, not degrees
section("5. Mercator is nonlinear in latitude");
{
  // Two points, same longitude, far apart in latitude. Centred correctly they
  // are equidistant from the box's middle. Centred on the degree mean they are
  // not, and the error grows the further from the equator you look.
  const l = osmFitLayout([P(60, 10), P(0, 10)], W, H);
  const [a, b] = l.pins;
  near(Math.abs(a.top - H / 2), Math.abs(b.top - H / 2), 1.5,
       "both pins sit the same distance from the vertical centre");
  // The degree mean would be 30; the projected centre is ~35.3.
  ok(Math.abs(l.center.lat - 30) > 3,
     "centre latitude is not the degree mean (got " + l.center.lat.toFixed(2) + ")");
  near(l.center.lat, 35.28, 0.1, "centre latitude is the projected midpoint");
}

// 6. Longitude is a circle
section("6. the antimeridian");
{
  // Tokyo, Auckland, Honolulu span ~30 degrees of longitude ACROSS the Pacific.
  // Averaging their degrees puts the centre near Arabia and forces a zoom that
  // shows the whole planet in order to "fit" three neighbours.
  const pac = [P(35.68, 139.65), P(-36.85, 174.76), P(21.31, -157.86)];
  const l = osmFitLayout(pac, W, H);
  ok(l.pins.every((p) => p.left >= 0 && p.left <= W && p.top >= 0 && p.top <= H),
     "all three Pacific pins are on the map");
  const lng = ((l.center.lng + 540) % 360) - 180;
  ok(Math.abs(lng) > 150, "centre is in the Pacific, not Arabia (got " + lng.toFixed(1) + ")");
  ok(l.zoom >= 2, "zoom is a Pacific view, not the whole planet (got " + l.zoom + ")");

  // The same shape moved so it does NOT cross the antimeridian must behave the
  // same — otherwise the wrap handling is doing something only it understands.
  const noCross = [P(35.68, 9.65), P(-36.85, 44.76), P(21.31, 22.0)];
  const l2 = osmFitLayout(noCross, W, H);
  ok(l2.pins.every((p) => p.left >= 0 && p.left <= W && p.top >= 0 && p.top <= H),
     "a non-crossing set of the same shape also fits");
  ok(l2.zoom === l.zoom, "and fits at the same zoom (got " + l2.zoom + " vs " + l.zoom + ")");
}

// 7. Degenerate spans
section("7. one point, and several at one address");
{
  const one = osmFitLayout([P(41.88, -87.63)], W, H, { fallbackZoom: 12 });
  ok(one.pins.length === 1, "a single point produces a single pin");
  ok(one.zoom === 12, "a zero-size box falls back rather than dividing by zero");
  near(one.pins[0].left, W / 2, 1, "the lone pin is centred horizontally");
  near(one.pins[0].top, H / 2, 1, "the lone pin is centred vertically");

  // Three events at one shop is the COMMON case here, not an edge case.
  const same = osmFitLayout([P(41.88, -87.63), P(41.88, -87.63), P(41.88, -87.63)], W, H,
                            { fallbackZoom: 13 });
  ok(same.zoom === 13, "identical points fall back too");
  ok(same.pins.every((p) => Math.abs(p.left - W / 2) <= 1 && Math.abs(p.top - H / 2) <= 1),
     "identical points stack at the centre");
}

// 8. Zoom clamps
section("8. zoom stays in range");
{
  // Two events a few metres apart would otherwise compute an absurd zoom, and
  // OSM has no tiles past 19.
  const tight = osmFitLayout([P(41.88, -87.63), P(41.8801, -87.6301)], W, H, { maxZoom: 15 });
  ok(tight.zoom <= 15, "maxZoom is honoured (got " + tight.zoom + ")");
  const world = osmFitLayout([P(-40, -170), P(60, 170)], W, H, { minZoom: 1 });
  ok(world.zoom >= 0 && world.zoom <= 19, "a world-spanning set stays in range (got " + world.zoom + ")");
  ok(world.pins.every((p) => p.left >= 0 && p.left <= W && p.top >= 0 && p.top <= H),
     "a world-spanning set still fits its pins");
}

// 9. Bad input, and the index that maps a pin back to its event
section("9. invalid points, and pin -> event identity");
{
  ok(osmFitLayout([], W, H) === null, "no points is null, not a crash");
  ok(osmFitLayout(null, W, H) === null, "null input is null");
  ok(osmFitLayout([P(NaN, 1), P(2, NaN), {}, null], W, H) === null,
     "all-invalid is null rather than a map of nowhere");

  // The worst silent failure available here: a pin whose index has drifted
  // opens a different event than the one it is drawn on. An event with no
  // coordinates must be skipped WITHOUT renumbering the ones around it.
  const mixed = [P(41.88, -87.63), P(NaN, -87.0), P(42.05, -87.68), null, P(41.52, -88.08)];
  const l = osmFitLayout(mixed, W, H);
  ok(l.pins.length === 3, "the two unplaceable events are dropped");
  ok(l.pins.map((p) => p.i).join(",") === "0,2,4",
     "each pin keeps its ORIGINAL index (got " + l.pins.map((p) => p.i).join(",") + ")");
  ok(l.pins.every((p) => p.lat === mixed[p.i].lat && p.lng === mixed[p.i].lng),
     "each pin's coordinates match the event it points at");
  // Out-of-range coordinates are data errors, not places.
  ok(osmFitLayout([P(41.88, -87.63), P(91, 0), P(0, 181)], W, H).pins.length === 1,
     "impossible coordinates are dropped");

  // Null Island. This is the shape the DATABASE hands us — lorcana_events
  // .latitude is nullable and a curated calendar row is legitimately
  // ungeocoded — and Number(null) is 0, not NaN. Unguarded, every event we
  // cannot place is drawn in the Atlantic off Ghana as an ordinary pin.
  const nulls = osmFitLayout([P(41.88, -87.63), { lat: null, lng: null },
                              { lat: 42.05, lng: null }, { lng: -87.68 }], W, H);
  ok(nulls.pins.length === 1, "null coordinates are dropped, not read as zero");
  ok(nulls.pins[0].i === 0, "and the survivor keeps its index");
  ok(osmFitLayout([{ lat: null, lng: null }], W, H) === null,
     "a set with only null coordinates is null, never a map of Null Island");
  // Empty strings arrive the same way out of a form or a CSV, and coerce to 0 too.
  ok(osmFitLayout([{ lat: "", lng: "" }], W, H) === null, "empty strings are not zero");
  // But a numeric STRING is a real coordinate — PostgREST hands back numerics
  // as strings often enough that rejecting them would empty the map.
  const strs = osmFitLayout([{ lat: "41.88", lng: "-87.63" }, { lat: "42.05", lng: "-87.68" }], W, H);
  ok(strs !== null && strs.pins.length === 2, "numeric strings are real coordinates");
}

// 10. Merging overlapping pins must never lose an event
section("10. scMergePins");
{
  const pin = (i, left, top) => ({ i, left, top });
  // Two shops a few hundred metres apart land on the same pixel at city zoom.
  // The merge is the only reason the second one is reachable at all — so the
  // invariant is total: every input pin is in exactly one output group.
  const pins = [pin(0, 100, 100), pin(1, 103, 102), pin(2, 300, 200),
                pin(3, 100, 100), pin(4, 305, 205), pin(5, 500, 50)];
  const groups = scMergePins(pins);
  const seen = groups.flatMap((g) => g.items.map((p) => p.i)).sort((a, b) => a - b);
  ok(seen.join(",") === "0,1,2,3,4,5", "every pin survives the merge exactly once");
  ok(groups.length < pins.length, "co-located pins actually merged");
  ok(groups.every((g) => g.items.length > 0), "no empty group");
  // A group's position must be one of its own members', not an average that
  // could drift the marker off the shops it stands for.
  ok(groups.every((g) => g.items.some((p) => p.left === g.left && p.top === g.top)),
     "each group sits on one of its own pins");

  // Nothing within the threshold is left separate, and nothing beyond it is
  // swallowed: a merge that is too eager hides events under a pin that is not
  // where they are.
  const far = scMergePins([pin(0, 0, 0), pin(1, SC_PIN_MERGE_PX + 4, 0)]);
  ok(far.length === 2, "pins beyond the threshold stay separate");
  const close = scMergePins([pin(0, 0, 0), pin(1, SC_PIN_MERGE_PX - 1, 0)]);
  ok(close.length === 1, "pins inside the threshold merge");

  ok(scMergePins([]).length === 0, "no pins is no groups");

  // End to end: a real cluster's groups still account for every placed event.
  const l = osmFitLayout([P(41.88, -87.63), P(41.881, -87.631), P(42.34, -87.95)], W, H);
  const g2 = scMergePins(l.pins);
  ok(g2.reduce((n, g) => n + g.items.length, 0) === l.pins.length,
     "grouped pin count equals placed pin count");
}

// 11. scPlacePinLabels — the date chip beside the dot
//
// Every failure here is silent in the way the rest of this file is about: a
// label drawn over another label is unreadable but present, a label drawn over
// a DOT hides something clickable, and a label drawn past the edge of the frame
// is simply gone with nothing on screen to say it existed.
section("11. scPlacePinLabels");
{
  const lp = (left, top, text, rank) => ({ left, top, text, rank });
  const CHIP = (text) => scLabelW(text);
  const DAY = "Sep 27";
  const wide = 800, tall = 400;

  ok(scLabelW("") === 0 && scLabelW(null) === 0 && scLabelW(undefined) === 0,
     "no text is no width, so a pin with no date is never placed");
  ok(scLabelW("Sep 7") < scLabelW("Sep 27"), "width grows with the label");

  const one = scPlacePinLabels([lp(400, 200, DAY, 0)], wide, tall);
  ok(one.length === 1 && one[0] === "r", "a lone pin is labelled to its right");

  // Against the right edge it flips rather than clipping — the whole point of
  // trying two sides.
  const atRight = scPlacePinLabels([lp(wide - 20, 200, DAY, 0)], wide, tall);
  ok(atRight[0] === "l", "a pin near the right edge flips its label to the left");

  // In a frame too narrow for either side it is DROPPED, not clipped.
  const noRoom = scPlacePinLabels([lp(20, 20, DAY, 0)], 40, 40);
  ok(noRoom[0] === null, "a label with no room on either side is dropped");

  // ⚠ Two pins side by side is NOT a clash — the second simply takes the other
  // side, which is what having two sides is for. A real clash needs one side
  // already occupied and the other off the frame: two shops a few streets apart
  // near the left edge, which is an ordinary cluster and not a contrived one.
  const narrow = 380;
  const clash = scPlacePinLabels([lp(60, 200, DAY, 0), lp(60, 215, DAY, 1)], narrow, tall);
  ok(clash.filter(Boolean).length === 1, "two labels that would overlap do not both draw");
  ok(clash[0] === "r" && clash[1] === null,
     "the first-ranked pin is the one that keeps its label");

  // Rank, not array order, decides who wins.
  const ranked = scPlacePinLabels([lp(60, 200, DAY, 9), lp(60, 215, DAY, 0)], narrow, tall);
  ok(ranked[1] !== null && ranked[0] === null,
     "the better-ranked pin keeps its label whatever order it arrives in");

  // And the loser is still a PIN — losing a label never loses an event, which
  // is the whole licence for dropping one.
  ok(clash.length === 2, "a dropped label still has its pin in the answer");

  // ⚠ A MERGED pin is physically wider than a plain one — it carries a count —
  // and reserving the plain width for it lets a neighbour's chip clip its edge.
  // Found live at 2.5px, which is invisible in a screenshot and still covers a
  // click target.
  ok(scPinR(1) === SC_PIN_R, "a single pin reserves the plain radius");
  ok(scPinR(12) > SC_PIN_R, "a two-digit count reserves more than a plain pin");
  ok(scPinR(120) > scPinR(12), "and a three-digit count more again");
  ok(scPinR(0) === SC_PIN_R && scPinR(undefined) === SC_PIN_R,
     "no count is the plain radius, never NaN");
  {
    // A chip that just clears a PLAIN neighbour must be refused once that
    // neighbour is merged and therefore wider.
    const gap = SC_PIN_R + SC_LBL_GAP;
    const mk = (r) => scPlacePinLabels(
      [lp(300, 200, DAY, 0), Object.assign(lp(300 - gap - CHIP(DAY) - SC_PIN_R, 200, "", 1), { r })],
      wide, tall);
    ok(mk(SC_PIN_R)[0] !== null, "the chip fits beside a plain neighbour");
    ok(mk(scPinR(12))[0] !== "l", "and is refused that side once the neighbour is merged");
  }

  // A chip may never cover another event's DOT, labelled or not — that hides a
  // click target. Put a second, label-less pin exactly where the first pin's
  // right-hand chip would go.
  const overDot = scPlacePinLabels(
    [lp(300, 200, DAY, 0), lp(300 + SC_PIN_R + SC_LBL_GAP + 10, 200, "", 1)], wide, tall);
  ok(overDot[0] === "l", "a chip that would cover another pin's dot goes the other way");

  // Clear in y, both draw: the placement is a 2D fit, not a column test.
  const stacked = scPlacePinLabels([lp(300, 100, DAY, 0), lp(300, 100 + SC_LBL_H + 4, DAY, 1)],
                                   wide, tall);
  ok(stacked.every(Boolean), "labels clear in y both draw");

  // Degenerate inputs must not throw — the map renders before it is measured.
  ok(scPlacePinLabels([], 0, 0).length === 0, "no pins, no sides");
  ok(scPlacePinLabels([lp(10, 10, DAY, 0)], 0, 400)[0] === null, "an unmeasured box places nothing");
  ok(scPlacePinLabels(null, wide, tall).length === 0, "null pins is an empty answer");
  ok(scPlacePinLabels([lp(10, 10, DAY)], wide, tall).length === 1,
     "a missing rank falls back to array order rather than NaN");

  // End to end over a real layout: no placed chip overlaps another chip, any
  // dot, or the edge of the frame.
  const pts = [P(41.88, -87.63), P(41.95, -87.68), P(42.05, -88.0), P(41.7, -87.7),
               P(41.9, -88.3), P(42.2, -87.8)];
  const lay = osmFitLayout(pts, W, H);
  const gs = scMergePins(lay.pins);
  const cand = gs.map((g, i) => lp(g.left, g.top, DAY, i));
  const sides = scPlacePinLabels(cand, W, H);
  const boxes = [];
  sides.forEach((side, i) => {
    if (!side) return;
    const tw = CHIP(DAY), q = cand[i];
    const x0 = side === "r" ? q.left + SC_PIN_R + SC_LBL_GAP
                            : q.left - SC_PIN_R - SC_LBL_GAP - tw;
    boxes.push([x0, q.top - SC_LBL_H / 2, x0 + tw, q.top + SC_LBL_H / 2]);
  });
  const hit = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
  let bad = 0;
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) if (hit(boxes[i], boxes[j])) bad++;
    for (const q of cand) {
      const dot = [q.left - SC_PIN_R, q.top - SC_PIN_R, q.left + SC_PIN_R, q.top + SC_PIN_R];
      if (hit(boxes[i], dot)) bad++;
    }
  }
  ok(bad === 0, "over a real layout no chip overlaps another chip or any dot");
  ok(boxes.every((b) => b[0] >= 0 && b[1] >= 0 && b[2] <= W && b[3] <= H),
     "every placed chip is fully inside the frame");
  ok(sides.some(Boolean), "a real layout still labels something");
}

// 12. osmFitLayout's FOCUS override — "zoom to this postal code"
//
// The calendar's map opens on a whole season across four continents; a focus is
// how you get from that to your own town. It shares every line of the pin maths
// with the fit deliberately, so what is tested here is that it overrides the two
// things it should and nothing else.
section("12. osmFitLayout focus");
{
  const CHI = { lat: 41.88, lng: -87.63 };
  const TOK = { lat: 35.68, lng: 139.77 };
  const pts = [P(CHI.lat, CHI.lng), P(TOK.lat, TOK.lng), P(-33.87, 151.21)];

  const fitted = osmFitLayout(pts, W, H);
  const focused = osmFitLayout(pts, W, H, { focus: { lat: CHI.lat, lng: CHI.lng, zoom: 9 } });
  ok(focused.zoom === 9, "the focus's zoom wins over the fitted one");
  ok(focused.zoom !== fitted.zoom, "and it really is a different zoom to the fit");
  near(focused.center.lat, CHI.lat, 1e-6, "the centre is the focus, not the cluster");
  near(focused.center.lng, CHI.lng, 1e-6, "same for longitude");

  // The focused point lands in the middle of the box — which is the whole
  // promise of "zoom here", and the one thing a second copy of the pin
  // subtraction would silently break.
  const chiPin = focused.pins.find((q) => q.i === 0);
  near(chiPin.left, W / 2, 1.5, "the focused point sits at the box's centre, x");
  near(chiPin.top, H / 2, 1.5, "the focused point sits at the box's centre, y");

  // ⚠ The fit's clamps are the FIT's business. A person who pressed + chose
  // that zoom, so minZoom/maxZoom must not quietly overrule them.
  const past = osmFitLayout(pts, W, H, { minZoom: 2, maxZoom: 4, focus: { lat: CHI.lat, lng: CHI.lng, zoom: 12 } });
  ok(past.zoom === 12, "a focus zoom past maxZoom is honoured, not clamped to the fit's cap");

  // ...but tiles only exist for 0..19.
  const silly = osmFitLayout(pts, W, H, { focus: { lat: CHI.lat, lng: CHI.lng, zoom: 99 } });
  ok(silly.zoom >= 0 && silly.zoom <= 19, "an absurd zoom is bounded to what tiles exist");

  // A half-built focus must fall back to the fit rather than to Null Island —
  // the same trap the coordinate reader itself carries.
  for (const bad of [{ lat: null, lng: -87.63, zoom: 9 }, { lat: 41.88, lng: null, zoom: 9 },
                     { lat: "", lng: "", zoom: 9 }, { lat: 999, lng: -87.63, zoom: 9 }]) {
    const f = osmFitLayout(pts, W, H, { focus: bad });
    ok(f.zoom === fitted.zoom && Math.abs(f.center.lng - fitted.center.lng) < 1e-9,
       "an unusable focus falls back to the fit (" + JSON.stringify(bad) + ")");
  }
  const noZoom = osmFitLayout(pts, W, H, { focus: { lat: CHI.lat, lng: CHI.lng } });
  ok(noZoom.zoom === fitted.zoom, "a focus with no zoom keeps the fitted zoom");
  near(noZoom.center.lat, CHI.lat, 1e-6, "but still moves the centre");

  // ⚠ The antimeridian wrap has to follow the FOCUS, not the cluster's centre:
  // focused on Tokyo, Sydney is a neighbour and must not be drawn a world away.
  const jp = osmFitLayout([P(TOK.lat, TOK.lng), P(-33.87, 151.21), P(CHI.lat, CHI.lng)],
                          W, H, { focus: { lat: TOK.lat, lng: TOK.lng, zoom: 4 } });
  const syd = jp.pins.find((q) => q.i === 1);
  const world = Math.pow(2, jp.zoom) * 256;
  ok(Math.abs(syd.left - W / 2) < world / 2,
     "a neighbour of the focus is drawn near it, not at the far copy of the world");

  // Every event still comes back, in frame or not — the box clips, the layout
  // does not drop.
  ok(focused.pins.length === fitted.pins.length, "a focus hides nothing from the layout");
}

// 13. scPanCenter — dragging the map
//
// Silent failures again: a sign error pans the wrong way (which reads as the
// map fighting you), degrees instead of world pixels drifts worse the further
// from the equator you are, and an unwrapped longitude comes out at -181, which
// osmFitLayout rejects as out of range — so a drag west past the antimeridian
// would empty the map of every pin rather than erroring.
section("13. scPanCenter");
{
  const CHI = { lat: 41.88, lng: -87.63 };
  const Z = 9;

  ok(scPanCenter(null, Z, 10, 10) === null, "no centre, no answer");
  ok(scPanCenter(CHI, NaN, 10, 10) === null, "no zoom, no answer");

  const still = scPanCenter(CHI, Z, 0, 0);
  near(still.lat, CHI.lat, 1e-9, "a zero drag does not move the centre");
  near(still.lng, CHI.lng, 1e-9, "in either axis");

  // ⚠ Dragging the tiles RIGHT shows what was to the WEST, so the centre's
  // longitude DECREASES. Getting this backwards is a map that fights the hand.
  const right = scPanCenter(CHI, Z, 120, 0);
  ok(right.lng < CHI.lng, "dragging right moves the centre west");
  const down = scPanCenter(CHI, Z, 0, 120);
  ok(down.lat > CHI.lat, "dragging down moves the centre north");

  // The same pixel drag is worth FOUR times as much world at four times the
  // scale — this is why it is done in world pixels, not degrees.
  const coarse = scPanCenter(CHI, Z - 2, 120, 0);
  near((CHI.lng - coarse.lng) / (CHI.lng - right.lng), 4, 0.01,
       "two zoom levels out, one pixel is worth four times the longitude");

  // A pixel of drag round-trips: pan out and back lands where it started.
  const there = scPanCenter(CHI, Z, 200, -90);
  const back = scPanCenter(there, Z, -200, 90);
  near(back.lat, CHI.lat, 1e-6, "panning back returns the latitude");
  near(back.lng, CHI.lng, 1e-6, "and the longitude");

  // ⚠ The antimeridian. A drag west from Tokyo must come out a legal longitude,
  // or osmFitLayout drops every pin and the map goes blank.
  const tok = { lat: 35.68, lng: 139.77 };
  let c = tok;
  for (let i = 0; i < 40; i++) c = scPanCenter(c, 4, -400, 0);
  ok(c.lng >= -180 && c.lng <= 180, "longitude stays legal across the antimeridian");
  ok(Math.abs(c.lat) <= 90, "and latitude stays legal");

  // ⚠ Latitude CLAMPS instead of wrapping — there is nothing past the pole, and
  // Mercator has no tiles there.
  let p2 = { lat: 60, lng: 0 };
  for (let i = 0; i < 60; i++) p2 = scPanCenter(p2, 3, 0, 600);
  ok(p2.lat <= 90 && p2.lat >= -90, "dragging past the pole stays on the planet");
  ok(isFinite(p2.lat) && isFinite(p2.lng), "and never goes non-finite");

  // End to end: the panned centre is one osmFitLayout will actually accept.
  const l = osmFitLayout([P(CHI.lat, CHI.lng)], W, H,
                         { focus: { lat: c.lat, lng: c.lng, zoom: 4 } });
  ok(!!l && l.pins.length === 1, "a panned centre is a focus osmFitLayout accepts");
}

// 14. A map you can SEND -- the ?cmap codec
//
// Zaven: "can we make maps shareable via link? like if i want to share a map at
// a zipcode for set champs so someone else can see". `?cv=map` alone only says
// "open the map", and the map opens on the whole season -- so the one thing the
// sender was showing is the one thing the link could not carry.
//
// Every failure here is silent and looks like a working map of the wrong place.
section("14. ?cmap share codec");
{
  const CHI = { lat: 41.8781, lng: -87.6298 };

  // /!\ Null Island, which this map has already shipped TWICE. Number("") and
  // Number(null) are both 0, not NaN, so a half-written param is a perfectly
  // finite point in the Atlantic that renders as an ordinary, empty map.
  for (const bad of ["", ",,", "41.88,,9", ",-87.63,9", "41.88,-87.63,",
                     "abc,def,9", "41.88,-87.63", null, undefined]) {
    ok(calParseMapFocus(bad) === null,
       "a blank or partial ?cmap is rejected, not read as 0N 0E: " + JSON.stringify(bad));
  }
  ok(calParseMapFocus("0,0,9") !== null, "but a DELIBERATE 0,0 is still a real point");

  ok(calParseMapFocus("91,0,9") === null, "a latitude past the Mercator limit is rejected");
  ok(calParseMapFocus("0,181,9") === null, "and so is a longitude off the planet");

  // /!\ The LABEL is last, and only the first three fields are split off,
  // because every American city name contains a comma. Splitting the whole
  // string and taking field 3 truncates "Chicago, IL" to "Chicago".
  const withState = calParseMapFocus("41.8781,-87.6298,9,Chicago, IL");
  ok(withState && withState.label === "Chicago, IL", "a place name keeps its comma");
  near(withState.lat, CHI.lat, 1e-9, "and the latitude still parses");
  near(withState.lng, CHI.lng, 1e-9, "and the longitude");

  // A coordinates-only link (what a DRAG produces) gets the shared any-label,
  // never an empty string: "No Lorcana events near " is a broken sentence.
  const bare = calParseMapFocus("41.8781,-87.6298,9");
  ok(bare && bare.label === CAL_MAP_ANY_LABEL, "a label-less focus says " + CAL_MAP_ANY_LABEL);
  ok(calParseMapFocus("41.8781,-87.6298,9,   ").label === CAL_MAP_ANY_LABEL,
     "and so does a whitespace-only label");

  // Zoom CLAMPS rather than rejecting -- a hand-edited z=40 should still show
  // you the place, at the closest zoom tiles exist for.
  ok(calParseMapFocus("41.88,-87.63,40").zoom === CAL_MAP_FOCUS_MAX, "a huge zoom clamps in");
  ok(calParseMapFocus("41.88,-87.63,-5").zoom === CAL_MAP_FOCUS_MIN, "a negative zoom clamps out");
  ok(calParseMapFocus("41.88,-87.63,9.6").zoom === 10, "a fractional zoom rounds to a real tile level");

  // /!\ Text off a URL renders into the toolbar and the empty-state line, so it
  // is length-capped -- an unbounded label is a layout break by hyperlink.
  const longLbl = calParseMapFocus("41.88,-87.63,9," + "x".repeat(400));
  ok(longLbl.label.length === CAL_MAP_LABEL_MAX, "a runaway label is capped");

  // -- ROUND TRIP: what the writer emits is what the reader gets back --------
  for (const f of [{ lat: 41.8781, lng: -87.6298, zoom: 9, label: "Chicago, IL" },
                   { lat: -33.8688, lng: 151.2093, zoom: 11, label: "Sydney" },
                   { lat: 35.6762, lng: 139.6503, zoom: 13, label: CAL_MAP_ANY_LABEL },
                   { lat: 0, lng: 0, zoom: 3, label: "" }]) {
    const back = calParseMapFocus(calMapFocusParam(f));
    ok(!!back, "a written focus reads back: " + (f.label || "(none)"));
    near(back.lat, f.lat, 1e-4, "  latitude survives the round trip");
    near(back.lng, f.lng, 1e-4, "  longitude survives the round trip");
    ok(back.zoom === f.zoom, "  zoom survives the round trip");
    ok(back.label === (f.label || CAL_MAP_ANY_LABEL), "  and the label");
  }

  // /!\ The any-label is OMITTED rather than written: a dragged map is the
  // common case and its link should not carry two words the parser supplies.
  ok(calMapFocusParam({ lat: 1, lng: 2, zoom: 9, label: CAL_MAP_ANY_LABEL }).split(",").length === 3,
     "a label-less focus writes three fields, not four");
  ok(calMapFocusParam(null) === "", "and no focus writes nothing at all");

  // The whole chain, not just the string: what the writer emits is a focus
  // osmFitLayout will actually draw.
  const l = osmFitLayout([P(CHI.lat, CHI.lng)], 800, 420,
                         { focus: calParseMapFocus(calMapFocusParam(
                             { lat: CHI.lat, lng: CHI.lng, zoom: 9, label: "Chicago, IL" })) });
  ok(!!l && l.pins.length === 1, "a link's focus is one the map can draw");
}

// 15. The registration rule, which fails silently
//
// /!\ CLAUDE.md's standing rule: a new deep-link param must be in BOTH
// `dirtyParams` and `VIEW_OWNED`. Unregistered, the link appears to work and
// then the view-sync effect strips it on the next render -- so it "works" for
// the sender, who is already there, and resets for everyone they send it to.
section("15. deep-link param registration");
{
  const dirty = grab("const dirtyParams = [", "];");
  const owned = grab("calendar:   new Set([", "]),");
  for (const k of ["cmap", "cmr", "cms", "cmk"]) {
    ok(dirty.includes('"' + k + '"'), k + " is registered in dirtyParams");
    ok(owned.includes('"' + k + '"'), k + " is owned by the calendar view");
  }

  // The finder's half. `scview` has to be in SC_DEEP_PARAMS or a bare
  // ?scview=map never opens the box at all, and buildShareUrl has to write it
  // or the Copy link button quietly shares a list.
  ok(grabLine("const SC_DEEP_PARAMS = ").includes('"scview"'),
     "scview is an event-finder deep-link param");
  ok(src.includes('u.searchParams.set("scview", "map")'),
     "and the finder's share link writes it");
  ok(src.includes('if(pView) return pView === "map";'),
     "and the map toggle reads it, so a shared map arrives as a map");

  // /!\ A seeded value must not be written back to localStorage: a link may
  // choose FOR the reader, never OVER them.
  ok(src.includes('usePrefWrite("packsink:scMap", mapOn ? "1" : "0", !!pView)'),
     "a link's view does not repoint the reader's saved preference");
  ok(src.includes("usePrefWrite(CAL_MAP_SCOPE_LS, mapScope, seed.cms != null)"),
     "nor its scope");
  ok(src.includes('usePrefWrite(CAL_MAP_KINDS_LS, mapStoreKinds.join(","), seed.cmk != null)'),
     "nor its kinds");

  // /!\ Written in map mode ONLY. A `cmap` left behind after switching to List
  // is a stale anchor that silently repoints the map on the way back.
  ok(src.includes('(onMap && mapFocus) ? url.searchParams.set("cmap"'),
     "cmap is written only in map mode");
  ok(src.includes('url.searchParams.delete("cmap")'), "and deleted otherwise");
}

console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
